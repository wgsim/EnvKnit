"""
Main CLI application for envknit.

Defines all command-line commands and their implementations.
"""

from pathlib import Path
from typing import Any

try:
    import click
    import yaml
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError as e:
    raise SystemExit(
        f"CLI dependencies not installed. Run: pip install envknit[cli]\n"
        f"Missing: {e.name}"
    ) from None

from envknit import __version__
from envknit.backends.base import Backend, PackageInfo
from envknit.backends.conda import CondaBackend
from envknit.backends.pip import PipBackend
from envknit.backends.poetry import PoetryBackend
from envknit.config.schema import BackendConfig, Config, EnvironmentConfig
from envknit.core.lock import Dependency, LockedPackage, LockFile
from envknit.core.resolver import PubGrubResolver
from envknit.storage.cache import PackageCache
from envknit.storage.store import EnvironmentStore, PackageMetadata

console = Console()

# Constants
CONFIG_FILE = "envknit.yaml"
LOCK_FILE = "envknit-lock.yaml"
DEFAULT_ENV = "default"


def _parse_dep_string(dep: str) -> Dependency:
    """Parse a dependency string into a Dependency object."""
    spec_chars = set("<>=!~")
    for i, char in enumerate(dep):
        if char in spec_chars:
            return Dependency(name=dep[:i].strip(), constraint=dep[i:].strip())
    return Dependency(name=dep.strip())


def get_config_path() -> Path:
    """Get the config file path."""
    return Path(CONFIG_FILE)


def get_lock_path() -> Path:
    """Get the lock file path."""
    return Path(LOCK_FILE)


def load_config() -> Config | None:
    """Load configuration from file."""
    config_path = get_config_path()
    if not config_path.exists():
        return None
    return Config.from_file(config_path)


def save_config(config: Config) -> None:
    """Save configuration to file."""
    config.to_file(get_config_path())


def load_lock() -> LockFile | None:
    """Load lock file if it exists."""
    lock_path = get_lock_path()
    if not lock_path.exists():
        return None
    return LockFile.from_file(lock_path)


def save_lock(lock: LockFile) -> None:
    """Save lock file."""
    lock.save()


def get_backend(config: Config | None = None, backend_type: str | None = None) -> Backend:
    """
    Get the configured backend.

    Args:
        config: Configuration object
        backend_type: Specific backend type ('conda', 'pip', 'poetry')

    Returns:
        Backend instance
    """
    # Determine backend type from config or parameter
    if backend_type is None:
        if config and config.backends:
            # Get the first configured backend type
            for _, backend_cfg in config.backends.items():
                backend_type = backend_cfg.type
                break

        if backend_type is None:
            backend_type = "conda"  # Default to conda

    # Get backend configuration
    backend_config = None
    if config and config.backends:
        for _, cfg in config.backends.items():
            if cfg.type == backend_type:
                backend_config = cfg
                break

    # Create backend instance based on type
    if backend_type == "conda":
        channels = ["conda-forge", "defaults"]
        if backend_config:
            channels = backend_config.channels
        return CondaBackend(channels=channels)

    elif backend_type == "pip":
        index_url = None
        extra_index_urls = []
        if backend_config and backend_config.options:
            index_url = backend_config.options.get("index_url")
            extra_index_urls = backend_config.options.get("extra_index_urls", [])
        return PipBackend(index_url=index_url, extra_index_urls=extra_index_urls)

    elif backend_type == "poetry":
        project_path = None
        if backend_config and backend_config.options:
            project_path = backend_config.options.get("project_path")
        return PoetryBackend(project_path=project_path)

    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


def parse_package_spec(spec: str) -> tuple[str, str]:
    """
    Parse a package specification into name and version constraint.

    Args:
        spec: Package specification (e.g., "numpy>=1.24,<2.0")

    Returns:
        Tuple of (name, version_constraint)
    """
    # Find where specifier starts
    spec_chars = set("<>=!~")
    spec_start = len(spec)
    for i, char in enumerate(spec):
        if char in spec_chars:
            spec_start = i
            break

    name = spec[:spec_start].strip()
    version = spec[spec_start:].strip()
    return name, version


def detect_existing_files() -> dict:
    """
    Detect existing dependency files in the current directory.

    Returns:
        Dictionary with detected file types and their contents
    """
    detected = {}

    # Check for requirements.txt
    req_path = Path("requirements.txt")
    if req_path.exists():
        with open(req_path) as f:
            packages = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        detected["requirements.txt"] = packages

    # Check for environment.yml
    env_path = Path("environment.yml")
    if env_path.exists():
        with open(env_path) as f:
            data = yaml.safe_load(f)
        if data:
            detected["environment.yml"] = data

    return detected


@click.group()
@click.version_option(version=__version__, prog_name="envknit")
@click.pass_context
def app(ctx: click.Context) -> None:
    """
    EnvKnit - Multi-environment package manager for Python.

    Manage isolated package environments within a single project.
    """
    ctx.ensure_object(dict)


# ============================================================================
# INIT COMMAND
# ============================================================================

@app.command()
@click.option("--path", type=click.Path(), default=".", help="Project path")
@click.option("--python", "-p", default="3.11", help="Python version")
@click.option("--name", "-n", default=None, help="Project name")
@click.option("--backend", "-b", type=click.Choice(["conda", "pip", "poetry"]), default="conda",
              help="Package manager backend (conda, pip, poetry)")
@click.option("--detect", is_flag=True, help="Detect existing requirements.txt/environment.yml")
@click.option("--interactive", "-i", is_flag=True, help="Interactive initialization")
def init(path: str, python: str, name: str | None, backend: str, detect: bool, interactive: bool) -> None:
    """
    Initialize a new envknit project.

    Creates an envknit.yaml configuration file in the specified directory.

    \b
    Examples:
        envknit init                    # Interactive initialization
        envknit init --python 3.11      # Python version specified
        envknit init --backend pip      # Use pip backend
        envknit init --backend poetry   # Use Poetry backend
        envknit init --detect           # Detect existing dependency files
        envknit init -n myproject -p 3.10 -b pip
    """
    project_path = Path(path).resolve()
    config_path = project_path / CONFIG_FILE

    if config_path.exists():
        console.print(f"[yellow]Warning:[/yellow] {CONFIG_FILE} already exists at {config_path}")
        if not Confirm.ask("Overwrite existing configuration?"):
            return

    # Determine project name
    if name is None:
        if interactive:
            name = Prompt.ask("Project name", default=project_path.name)
        else:
            name = project_path.name

    # Determine Python version
    if interactive:
        python = Prompt.ask("Python version", default=python)

    # Determine backend
    if interactive:
        backend = Prompt.ask(
            "Package manager backend",
            default=backend,
            choices=["conda", "pip", "poetry"]
        )

    # Initialize packages list
    packages = []

    # Detect existing files if requested
    if detect:
        detected = detect_existing_files()
        if detected:
            console.print("[blue]Detected existing dependency files:[/blue]")

            if "requirements.txt" in detected:
                console.print(f"  - requirements.txt ({len(detected['requirements.txt'])} packages)")
                if Confirm.ask("Import packages from requirements.txt?", default=True):
                    packages.extend(detected["requirements.txt"])

            if "environment.yml" in detected:
                env_data = detected["environment.yml"]
                deps = env_data.get("dependencies", [])
                pip_deps = []
                for dep in deps:
                    if isinstance(dep, str):
                        packages.append(dep)
                    elif isinstance(dep, dict) and "pip" in dep:
                        pip_deps.extend(dep["pip"])
                if pip_deps:
                    console.print(f"  - environment.yml pip dependencies ({len(pip_deps)} packages)")
                    if Confirm.ask("Import pip dependencies?", default=True):
                        packages.extend(pip_deps)

    # Create configuration
    config = Config(
        name=name,
        version="1.0.0",
        environments={
            DEFAULT_ENV: EnvironmentConfig(
                python=python,
                packages=packages,
                channels=["conda-forge"] if backend == "conda" else [],
            )
        },
        backends={
            backend: BackendConfig(
                type=backend,
                channels=["conda-forge", "defaults"] if backend == "conda" else [],
            )
        }
    )

    # Validate configuration
    errors = config.validate()
    if errors:
        for error in errors:
            console.print(f"[red]Validation error:[/red] {error}")
        raise SystemExit(1)

    # Save configuration
    config.to_file(config_path)
    console.print(f"[green]Created[/green] {config_path}")
    console.print(f"  Project: {name}")
    console.print(f"  Python: {python}")
    console.print(f"  Backend: {backend}")

    if packages:
        console.print(f"  Packages: {len(packages)} imported")


# ============================================================================
# ADD COMMAND
# ============================================================================

@app.command()
@click.argument("packages", nargs=-1, required=True)
@click.option("--env", "-e", default=DEFAULT_ENV, help="Target environment")
@click.option("--dev", is_flag=True, help="Add as development dependency")
def add(packages: tuple[str, ...], env: str, dev: bool) -> None:
    """
    Add packages to an environment.

    Packages can be specified with version constraints using standard
    Python package specifier syntax.

    \b
    Examples:
        envknit add numpy               # Latest version
        envknit add numpy>=1.24,<2.0    # Version constraint
        envknit add pandas tensorflow   # Multiple packages
        envknit add pytest --dev        # Development dependency
    """
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found. Run 'envknit init' first.")
        raise SystemExit(1)

    env_config = config.get_environment(env)
    if env_config is None:
        console.print(f"[red]Error:[/red] Environment '{env}' not found")
        console.print(f"Available environments: {', '.join(config.environments.keys())}")
        raise SystemExit(1)

    # Add packages
    added_count = 0
    for package in packages:
        # Validate package spec
        name, version = parse_package_spec(package)

        # Check if already exists
        existing = [p for p in env_config.packages if p.split(">=")[0].split("==")[0].split("<=")[0].split("<")[0].split(">")[0] == name]

        if existing:
            # Update existing package
            for old in existing:
                env_config.packages.remove(old)
            env_config.packages.append(package)
            console.print(f"[yellow]Updated[/yellow] {name}: {old} -> {package}")
            added_count += 1
        else:
            env_config.packages.append(package)
            console.print(f"[green]Added[/green] {package} to environment '{env}'")
            added_count += 1

    # Save configuration
    save_config(config)
    console.print(f"\n[blue]Summary:[/blue] {added_count} package(s) added to '{env}'")
    console.print("Run 'envknit resolve' to resolve dependencies")


# ============================================================================
# RESOLVE COMMAND
# ============================================================================

@app.command()
@click.option("--env", "-e", default=None, help="Specific environment to resolve")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--dry-run", is_flag=True, help="Show resolution without saving")
def resolve(env: str | None, verbose: bool, dry_run: bool) -> None:
    """
    Resolve dependencies for environments.

    Uses the PubGrub algorithm to find compatible versions for all
    packages and their dependencies.

    \b
    Examples:
        envknit resolve                 # Resolve all environments
        envknit resolve --env default   # Resolve specific environment
        envknit resolve --verbose       # Show detailed resolution steps
    """
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found. Run 'envknit init' first.")
        raise SystemExit(1)

    # Determine which environments to resolve
    if env:
        if env not in config.environments:
            console.print(f"[red]Error:[/red] Environment '{env}' not found")
            raise SystemExit(1)
        envs_to_resolve = {env: config.environments[env]}
    else:
        envs_to_resolve = config.environments

    if not envs_to_resolve:
        console.print("[yellow]No environments to resolve[/yellow]")
        return

    # Get backend
    backend = get_backend(config)

    # Check backend availability
    if not backend.is_available():
        console.print("[red]Error:[/red] Conda/mamba is not available")
        console.print("Install conda or mamba to use envknit")
        raise SystemExit(1)

    # Initialize lock file
    lock = LockFile(path=get_lock_path())

    # Resolve each environment
    all_success = True
    for env_name, env_config in envs_to_resolve.items():
        console.print(f"\n[blue]Resolving environment:[/blue] {env_name}")

        if not env_config.packages:
            console.print("  [yellow]No packages defined[/yellow]")
            continue

        # Create resolver (transitive deps handled by conda during install)
        resolver = PubGrubResolver(backend=backend, resolve_dependencies=False)

        # Add Python constraint
        requirements = list(env_config.packages)

        if verbose:
            console.print(f"  Requirements: {', '.join(requirements)}")

        # Resolve
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            _ = progress.add_task("Resolving dependencies...", total=None)
            result = resolver.resolve(requirements)

        if result.success:
            console.print("  [green]Resolution successful[/green]")

            # Display resolved packages
            table = Table(title=f"Resolved Packages ({env_name})")
            table.add_column("Package", style="cyan")
            table.add_column("Version", style="green")

            for pkg_name, pkg_version in sorted(result.packages.items()):
                table.add_row(pkg_name, pkg_version)

            if verbose or len(result.packages) <= 20:
                console.print(table)
            else:
                console.print(f"  Resolved {len(result.packages)} packages")
                if verbose:
                    console.print(table)

            # Add to lock file
            for pkg_name, pkg_version in result.packages.items():
                # Get dependencies from graph
                deps: list[Dependency] = []
                if result.graph:
                    node = result.graph.get_package(pkg_name)
                    if node:
                        deps = [_parse_dep_string(d) for d in node.dependencies]

                lock.add_package(
                    env_name,
                    LockedPackage(
                        name=pkg_name,
                        version=pkg_version,
                        source="conda",
                        dependencies=deps,
                    )
                )

            # Show resolution reason in verbose mode
            if verbose and result.decision_log:
                console.print("\n  [dim]Resolution steps:[/dim]")
                for i, step in enumerate(result.decision_log[:10], 1):
                    action = step.get("action", "unknown")
                    package = step.get("package", "")
                    reason = step.get("reason", "")
                    console.print(f"    {i}. [{action}] {package}: {reason}")

                if len(result.decision_log) > 10:
                    console.print(f"    ... and {len(result.decision_log) - 10} more steps")

        else:
            all_success = False
            console.print("  [red]Resolution failed[/red]")

            # Display conflicts
            for conflict in result.conflicts:
                console.print(f"\n  [red]Conflict:[/red] {conflict.package}")
                console.print(f"    {conflict.message}")

                if conflict.suggestion:
                    console.print(f"    [yellow]Suggestion:[/yellow] {conflict.suggestion}")

                if verbose:
                    console.print("\n  [dim]Conflicting constraints:[/dim]")
                    for constraint, source in conflict.constraints:
                        console.print(f"    - {constraint.specifier} (from {source})")

    # Save lock file if successful and not dry-run
    if all_success and not dry_run:
        save_lock(lock)
        console.print(f"\n[green]Lock file saved:[/green] {LOCK_FILE}")
    elif dry_run:
        console.print("\n[yellow]Dry run - lock file not saved[/yellow]")
    else:
        console.print("\n[red]Resolution failed - fix conflicts before proceeding[/red]")
        raise SystemExit(1)


# ============================================================================
# INSTALL COMMAND
# ============================================================================

@app.command()
@click.option("--env", "-e", default=None, help="Specific environment to install")
@click.option("--resolve", "-r", "do_resolve", is_flag=True, help="Resolve before installing")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--use-store", is_flag=True, default=True, help="Use central package repository")
def install(env: str | None, do_resolve: bool, verbose: bool, use_store: bool) -> None:
    """
    Install packages from lock file.

    Installs resolved packages into a conda environment. If no lock file
    exists, run 'envknit lock' or use --resolve flag first.

    Packages are installed to a central repository and shared across
    projects by default. Use --no-use-store to install to project-specific environments.

    \b
    Examples:
        envknit install                 # Install all environments
        envknit install --env default   # Install specific environment
        envknit install --resolve       # Resolve and install
    """
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found. Run 'envknit init' first.")
        raise SystemExit(1)

    # Resolve if requested
    if do_resolve:
        console.print("[blue]Resolving dependencies first...[/blue]")
        # Call resolve logic
        ctx = click.Context(resolve)
        ctx.invoke(resolve, env=env, verbose=verbose, dry_run=False)

    # Load lock file
    lock = load_lock()

    if lock is None:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Determine which environments to install
    if env:
        if env not in lock.environments:
            console.print(f"[red]Error:[/red] Environment '{env}' not found in lock file")
            raise SystemExit(1)
        envs_to_install = {env: lock.environments[env]}
    else:
        envs_to_install = lock.environments

    if not envs_to_install:
        console.print("[yellow]No environments to install[/yellow]")
        return

    # Get backend
    backend = get_backend(config)

    if not backend.is_available():
        console.print("[red]Error:[/red] Conda/mamba is not available")
        raise SystemExit(1)

    # Initialize environment store for central repository
    store = EnvironmentStore()

    # Install each environment
    for env_name, packages in envs_to_install.items():
        console.print(f"\n[blue]Installing environment:[/blue] {env_name}")
        console.print(f"  Packages: {len(packages)}")

        # Get environment config for Python version
        env_config = config.get_environment(env_name)
        python_version = env_config.python if env_config else "3.11"

        if use_store:
            # Use central repository for package sharing
            console.print(f"  [dim]Using central repository at {store.ENVKNIT_ROOT}[/dim]")

            # Build package dict for composite environment
            packages_dict = {pkg.name: pkg.version for pkg in packages}

            # Check which packages are already installed
            already_installed = []
            to_install = []

            for pkg in packages:
                if store.is_installed(pkg.name, pkg.version):
                    already_installed.append(pkg)
                else:
                    to_install.append(pkg)

            if already_installed:
                console.print(f"  [green]Already in store ({len(already_installed)} packages):[/green]")
                for pkg in already_installed[:5]:
                    console.print(f"    - {pkg.name}=={pkg.version}")
                if len(already_installed) > 5:
                    console.print(f"    ... and {len(already_installed) - 5} more")

            if to_install:
                console.print(f"  [yellow]To install ({len(to_install)} packages):[/yellow]")

                # Install packages with progress
                success_count = 0
                failed_count = 0

                with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Installing packages", total=len(to_install))

                    for pkg in to_install:
                        progress.update(task, description=f"Installing {pkg.name}")

                        try:
                            store.install_package(
                                name=pkg.name,
                                version=pkg.version,
                                backend=backend,
                                python_version=python_version,
                            )
                            success_count += 1
                            if verbose:
                                console.print(f"    [green]Installed:[/green] {pkg.name}=={pkg.version}")
                        except Exception as e:
                            failed_count += 1
                            console.print(f"    [red]Failed:[/red] {pkg.name} - {e}")

                        progress.advance(task)

                console.print(f"\n  [green]Installed to store:[/green] {success_count} packages")
                if failed_count > 0:
                    console.print(f"  [red]Failed:[/red] {failed_count} packages")

            # Create/get composite environment for this project
            try:
                composite_env_path = store.get_shared_environment(
                    packages=packages_dict,
                    backend=backend,
                    python_version=python_version,
                    project_identifier=f"{config.name}-{env_name}",
                )
                console.print("\n  [green]Composite environment ready:[/green]")
                console.print(f"    Path: {composite_env_path}")
                console.print(f"\n  To activate: conda activate -p {composite_env_path}")
            except Exception as e:
                console.print(f"  [red]Failed to create composite environment:[/red] {e}")

        else:
            # Legacy installation method (project-specific environments)
            env_target = f"envknit-{config.name}-{env_name}"

            # Check if environment exists
            existing_envs = [e.name for e in backend.list_environments()]

            if env_target in existing_envs:
                console.print(f"  Environment '{env_target}' already exists")
                if not Confirm.ask("Reinstall/update packages?", default=True):
                    console.print("  [yellow]Skipping installation[/yellow]")
                    continue

            # Create environment if needed
            if env_target not in existing_envs:
                console.print(f"  Creating environment '{env_target}'...")
                if not backend.create_environment(
                    name=env_target,
                    python_version=python_version
                ):
                    console.print("  [red]Failed to create environment[/red]")
                    continue

            # Install packages with progress
            success_count = 0
            failed_count = 0

            with Progress(
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Installing packages", total=len(packages))

                for pkg in packages:
                    progress.update(task, description=f"Installing {pkg.name}")

                    pkg_info = PackageInfo(
                        name=pkg.name,
                        version=pkg.version,
                    )

                    if backend.install(pkg_info, target=env_target):
                        success_count += 1
                        if verbose:
                            console.print(f"    [green]Installed:[/green] {pkg.name}=={pkg.version}")
                    else:
                        failed_count += 1
                        console.print(f"    [red]Failed:[/red] {pkg.name}")

                    progress.advance(task)

            # Summary
            console.print(f"\n  [green]Installed:[/green] {success_count} packages")
            if failed_count > 0:
                console.print(f"  [red]Failed:[/red] {failed_count} packages")

            console.print(f"\n  To activate: conda activate {env_target}")


# ============================================================================
# LOCK COMMAND
# ============================================================================

@app.command()
@click.option("--env", "-e", default=None, help="Specific environment to lock")
@click.option("--update", "-u", multiple=True, help="Update specific packages")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def lock(env: str | None, update: tuple[str, ...], verbose: bool) -> None:
    """
    Generate a lock file for reproducible installs.

    Resolves all dependencies and creates a lock file with exact versions.
    Use --update to refresh specific packages while keeping others.

    \b
    Examples:
        envknit lock                    # Lock all environments
        envknit lock --env default      # Lock specific environment
        envknit lock --update numpy     # Update specific package
    """
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found. Run 'envknit init' first.")
        raise SystemExit(1)

    # Load existing lock if updating specific packages
    existing_lock = load_lock()

    # If updating specific packages, we need an existing lock
    if update and not existing_lock:
        console.print("[red]Error:[/red] No existing lock file to update")
        console.print("Run 'envknit lock' without --update first")
        raise SystemExit(1)

    # Determine environments to lock
    if env:
        if env not in config.environments:
            console.print(f"[red]Error:[/red] Environment '{env}' not found")
            raise SystemExit(1)
        envs_to_lock = {env: config.environments[env]}
    else:
        envs_to_lock = config.environments

    # Get backend
    backend = get_backend(config)

    if not backend.is_available():
        console.print("[red]Error:[/red] Conda/mamba is not available")
        raise SystemExit(1)

    # Initialize new lock file
    new_lock = LockFile(get_lock_path())

    # If updating, copy non-updated packages from existing lock
    if update and existing_lock:
        update_names = set(update)

        for lock_env, packages in existing_lock.environments.items():
            if lock_env not in envs_to_lock:
                # Keep other environments as-is
                for pkg in packages:
                    new_lock.add_package(lock_env, pkg)
            else:
                # Keep non-updated packages
                for pkg in packages:
                    if pkg.name not in update_names:
                        new_lock.add_package(lock_env, pkg)

    # Lock each environment
    all_success = True
    for env_name, env_config in envs_to_lock.items():
        console.print(f"\n[blue]Locking environment:[/blue] {env_name}")

        # Build requirements
        requirements = list(env_config.packages)

        # If updating, add updated packages
        if update and env_name in envs_to_lock:
            for pkg_name in update:
                # Remove old version from requirements if present
                requirements = [r for r in requirements if not r.startswith(pkg_name)]
                requirements.append(pkg_name)

        if not requirements:
            console.print("  [yellow]No packages to lock[/yellow]")
            continue

        if verbose:
            console.print(f"  Requirements: {', '.join(requirements)}")

        # Resolve
        resolver = PubGrubResolver(backend=backend)
        result = resolver.resolve(requirements)

        if result.success:
            console.print(f"  [green]Locked {len(result.packages)} packages[/green]")

            for pkg_name, pkg_version in sorted(result.packages.items()):
                # Get dependencies from graph
                deps: list[Dependency] = []
                if result.graph:
                    node = result.graph.get_package(pkg_name)
                    if node:
                        deps = [_parse_dep_string(d) for d in node.dependencies]

                new_lock.add_package(
                    env_name,
                    LockedPackage(
                        name=pkg_name,
                        version=pkg_version,
                        source="conda",
                        dependencies=deps,
                    )
                )

                if verbose:
                    console.print(f"    {pkg_name}=={pkg_version}")

        else:
            all_success = False
            console.print("  [red]Locking failed[/red]")

            for conflict in result.conflicts:
                console.print(f"    [red]Conflict:[/red] {conflict.message}")

    # Save lock file
    if all_success:
        save_lock(new_lock)
        console.print(f"\n[green]Lock file saved:[/green] {LOCK_FILE}")
    else:
        console.print("\n[red]Locking failed - fix conflicts and try again[/red]")
        raise SystemExit(1)


# ============================================================================
# TREE COMMAND
# ============================================================================

@app.command()
@click.option("--env", "-e", default=None, help="Specific environment to show")
@click.option("--depth", "-d", default=3, help="Maximum depth to display")
def tree(env: str | None, depth: int) -> None:
    """
    Display dependency tree for environments.

    Shows packages and their dependencies in a tree format.

    \b
    Examples:
        envknit tree                    # Show all environments
        envknit tree --env default      # Show specific environment
        envknit tree --depth 5          # Show deeper tree
    """
    lock = load_lock()

    if lock is None:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Determine which environments to show
    envs_to_show = {}
    if env:
        if env not in lock._env_packages:
            console.print(f"[red]Error:[/red] Environment '{env}' not found in lock file")
            raise SystemExit(1)
        envs_to_show = {env: lock._env_packages[env]}
    else:
        envs_to_show = lock._env_packages

    if not envs_to_show:
        console.print("[yellow]No packages in lock file[/yellow]")
        return

    # Build dependency tree for each environment
    for env_name, packages in envs_to_show.items():
        if len(envs_to_show) > 1:
            console.print(f"\n[bold cyan]Environment: {env_name}[/bold cyan]")

        # Find root packages (direct dependencies)
        config = load_config()
        direct_packages = set()
        if config:
            env_config = config.get_environment(env_name)
            if env_config:
                direct_packages = {parse_package_spec(p)[0].lower() for p in env_config.packages}

        # Build package lookup
        pkg_lookup = {p.name.lower(): p for p in packages}

        # Print tree for each root package
        for pkg in packages:
            if pkg.name.lower() in direct_packages:
                _print_tree_node(pkg.name, pkg.version, pkg_lookup, depth=depth, prefix="", is_last=True, visited=None)

        # If no direct packages found, show all
        if not direct_packages:
            for pkg in packages:
                _print_tree_node(pkg.name, pkg.version, pkg_lookup, depth=depth, prefix="", is_last=True, visited=None)


def _print_tree_node(
    name: str,
    version: str,
    pkg_lookup: dict,
    depth: int,
    prefix: str,
    is_last: bool,
    visited: set | None = None,
) -> None:
    """Recursively print a tree node and its dependencies."""
    if visited is None:
        visited = set()

    # Prevent cycles
    name_lower = name.lower()
    if name_lower in visited:
        console.print(f"{prefix}└── {name} [dim](cycle detected)[/dim]")
        return

    # Print current node
    connector = "└── " if is_last else "├── "
    if prefix == "":
        # Root node
        console.print(f"[green]{name}[/green] [yellow]{version}[/yellow]")
    else:
        console.print(f"{prefix}{connector}[green]{name}[/green] [yellow]{version}[/yellow]")

    # Check depth limit
    if depth <= 0:
        return

    # Get dependencies
    pkg = pkg_lookup.get(name_lower)
    if not pkg or not pkg.dependencies:
        return

    visited_copy = visited | {name_lower}
    deps = list(pkg.dependencies)

    for i, dep in enumerate(deps):
        dep_name = parse_package_spec(dep)[0]
        dep_pkg = pkg_lookup.get(dep_name.lower())

        is_last_dep = (i == len(deps) - 1)
        new_prefix = prefix + ("    " if is_last else "│   ")

        if dep_pkg:
            _print_tree_node(
                dep_pkg.name,
                dep_pkg.version,
                pkg_lookup,
                depth - 1,
                new_prefix,
                is_last_dep,
                visited_copy,
            )
        else:
            # Package not in lock (system package)
            connector = "└── " if is_last_dep else "├── "
            console.print(f"{new_prefix}{connector}[dim]{dep_name}[/dim]")


# ============================================================================
# GRAPH COMMAND
# ============================================================================

@app.command()
@click.option("--env", "-e", default=None, help="Specific environment to show")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def graph(env: str | None, output_json: bool) -> None:
    """
    Display dependency graph for environments.

    Shows packages and their relationships in a graph format.

    \b
    Examples:
        envknit graph                    # Show graph for all environments
        envknit graph --env default      # Show graph for specific environment
        envknit graph --json             # Output as JSON for tools
    """
    lock = load_lock()

    if lock is None:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Determine which environments to show
    envs_to_show = {}
    if env:
        if env not in lock._env_packages:
            console.print(f"[red]Error:[/red] Environment '{env}' not found in lock file")
            raise SystemExit(1)
        envs_to_show = {env: lock._env_packages[env]}
    else:
        envs_to_show = lock._env_packages

    if not envs_to_show:
        console.print("[yellow]No packages in lock file[/yellow]")
        return

    # JSON output
    if output_json:
        _output_graph_json(envs_to_show)
        return

    # Text output
    console.print("\n[bold]Dependency Graph:[/bold]\n")

    for env_name, packages in envs_to_show.items():
        if len(envs_to_show) > 1:
            console.print(f"[bold cyan]Environment: {env_name}[/bold cyan]\n")

        # Find shared dependencies (packages used by multiple packages)
        dep_counts: dict[str, int] = {}
        for pkg in packages:
            for dep in pkg.dependencies:
                dep_name = dep.name.lower()
                dep_counts[dep_name] = dep_counts.get(dep_name, 0) + 1

        shared = {name for name, count in dep_counts.items() if count > 1}

        # Print graph for each package
        for pkg in sorted(packages, key=lambda p: p.name):
            deps = pkg.dependencies
            if not deps:
                console.print(f"[green]{pkg.name}[/green] [dim](no dependencies)[/dim]")
                continue

            # Build the graph line
            dep_strs = []
            for dep in deps:
                dep_name = dep.name
                if dep_name.lower() in shared:
                    dep_strs.append(f"[blue]{dep_name}[/blue] [dim](shared)[/dim]")
                else:
                    dep_strs.append(f"[blue]{dep_name}[/blue]")

            deps_text = "\n    ├── ".join(dep_strs[:3])
            if len(dep_strs) > 3:
                deps_text += f"\n    └── ... and {len(dep_strs) - 3} more"
            elif len(dep_strs) > 1:
                deps_text = deps_text.replace("├──", "└──", 1)

            console.print(f"[green]{pkg.name}[/green] ──┬── {dep_strs[0] if dep_strs else ''}")
            for dep_str in dep_strs[1:]:
                console.print(f"    ├── {dep_str}")
            console.print()


def _output_graph_json(envs_to_show: dict) -> None:
    """Output dependency graph as JSON."""
    import json

    result: dict[str, Any] = {
        "environments": []
    }

    for env_name, packages in envs_to_show.items():
        env_data: dict[str, Any] = {
            "name": env_name,
            "nodes": [],
            "edges": []
        }

        # Build nodes
        for pkg in packages:
            env_data["nodes"].append({
                "id": pkg.name,
                "version": pkg.version,
                "source": pkg.source,
            })

            # Build edges
            for dep in pkg.dependencies:
                dep_name = dep.name
                constraint = dep.constraint

                env_data["edges"].append({
                    "from": pkg.name,
                    "to": dep_name,
                    "constraint": constraint,
                })

        result["environments"].append(env_data)

    console.print_json(json.dumps(result, indent=2))


# ============================================================================
# WHY COMMAND (IMPROVED)
# ============================================================================

@app.command()
@click.argument("package")
@click.option("--env", "-e", default=DEFAULT_ENV, help="Environment to check")
def why(package: str, env: str) -> None:
    """
    Explain why a specific package version was selected.

    Shows the dependency chain that led to the selection of a particular
    package version, helping understand version constraints.

    \b
    Examples:
        envknit why numpy               # Why was numpy selected?
        envknit why pandas --env data   # Check in specific environment
    """
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found.")
        raise SystemExit(1)

    # Load lock file
    lock = load_lock()

    if lock is None:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Check environment exists
    if env not in lock._env_packages:
        console.print(f"[red]Error:[/red] Environment '{env}' not found in lock file")
        raise SystemExit(1)

    packages = lock._env_packages[env]

    # Find the package
    pkg_lookup = {p.name.lower(): p for p in packages}
    locked_pkg = pkg_lookup.get(package.lower())

    if locked_pkg is None:
        console.print(f"[red]Error:[/red] Package '{package}' not found in environment '{env}'")

        # Suggest similar packages
        available = [p.name for p in packages]
        similar = [p for p in available if package.lower() in p.lower()]

        if similar:
            console.print("\n[yellow]Similar packages:[/yellow]")
            for p in similar[:5]:
                console.print(f"  - {p}")

        raise SystemExit(1)

    # Display package info with improved format
    console.print(f"\n[green bold]{locked_pkg.name}@{locked_pkg.version}[/green bold] was selected because:")

    # Check if directly requested
    env_config = config.get_environment(env)
    direct_deps = []
    if env_config:
        direct_deps = [parse_package_spec(p)[0].lower() for p in env_config.packages]

    is_direct = package.lower() in direct_deps

    # Build reasons
    reasons = []

    # Check selection reason from lock file
    if locked_pkg.selection_reason:
        sr = locked_pkg.selection_reason

        if sr.type == "direct":
            reasons.append("  - [cyan]Direct dependency[/cyan] - explicitly requested")
            if sr.rationale:
                reasons.append(f"  - {sr.rationale}")
        elif sr.type == "dependency":
            reasons.append("  - [yellow]Transitive dependency[/yellow] - required by other packages")
            if sr.required_by:
                for req in sr.required_by[:3]:
                    req_pkg = pkg_lookup.get(req.lower())
                    if req_pkg:
                        reasons.append(f"  - Compatible with [blue]{req_pkg.name} {req_pkg.version}[/blue] (requires {locked_pkg.name})")
        else:
            reasons.append("  - [dim]Fallback selection[/dim]")
    else:
        # Fallback to basic detection
        if is_direct:
            reasons.append("  - [cyan]Direct dependency[/cyan] - explicitly requested in envknit.yaml")
            reasons.append("  - Latest available version")
        else:
            reasons.append("  - [yellow]Transitive dependency[/yellow] - required by other packages")

    # Print reasons
    for reason in reasons:
        console.print(reason)

    # Find what depends on this package (with version info)
    dependents: list[tuple[str, str, str]] = []
    for pkg in packages:
        for dep in pkg.dependencies:
            dep_name = dep.name
            if dep_name.lower() == package.lower():
                constraint = dep.constraint
                dependents.append((pkg.name, pkg.version, constraint))

    if dependents:
        console.print("\n[cyan]This version is used by:[/cyan]")
        for name, version, constraint in sorted(dependents):
            if constraint:
                console.print(f"  - [blue]{name} {version}[/blue] (requires [yellow]{constraint}[/yellow])")
            else:
                console.print(f"  - [blue]{name} {version}[/blue]")

    # Show dependencies of this package
    if locked_pkg.dependencies:
        console.print("\n[cyan]Depends on:[/cyan]")
        for dep in sorted(locked_pkg.dependencies, key=lambda d: d.name)[:8]:
            dep_name = dep.name
            dep_pkg = pkg_lookup.get(dep_name.lower())
            if dep_pkg:
                dep_str = f"{dep.name}{dep.constraint}" if dep.constraint else dep.name
                console.print(f"  - {dep_str} [dim](locked: {dep_pkg.version})[/dim]")
            else:
                dep_str = f"{dep.name}{dep.constraint}" if dep.constraint else dep.name
                console.print(f"  - {dep_str} [dim](system package)[/dim]")

        if len(locked_pkg.dependencies) > 8:
            console.print(f"  ... and {len(locked_pkg.dependencies) - 8} more")

    # Show alternatives if available
    if locked_pkg.selection_reason and locked_pkg.selection_reason.alternatives_considered:
        console.print("\n[dim]Alternatives considered:[/dim]")
        for alt in locked_pkg.selection_reason.alternatives_considered[:3]:
            console.print(f"  - {alt.version}: {alt.rejected}")

    # Helpful tips
    console.print(f"\n[dim]Run 'envknit tree --env {env}' to see the full dependency tree.[/dim]")
    console.print(f"[dim]Run 'envknit graph --env {env}' to see the dependency graph.[/dim]")


# ============================================================================
# REMOVE COMMAND
# ============================================================================

@app.command()
@click.argument("packages", nargs=-1, required=True)
@click.option("--env", "-e", default=DEFAULT_ENV, help="Target environment")
def remove(packages: tuple[str, ...], env: str) -> None:
    """
    Remove packages from an environment.

    \b
    Examples:
        envknit remove numpy
        envknit remove pandas tensorflow --env data
    """
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found.")
        raise SystemExit(1)

    env_config = config.get_environment(env)
    if env_config is None:
        console.print(f"[red]Error:[/red] Environment '{env}' not found")
        raise SystemExit(1)

    # Remove packages
    removed_count = 0
    for package in packages:
        package_name = parse_package_spec(package)[0]

        # Find matching packages
        matching = [
            p for p in env_config.packages
            if parse_package_spec(p)[0] == package_name
        ]

        if matching:
            for match in matching:
                env_config.packages.remove(match)
                console.print(f"[green]Removed[/green] {match} from environment '{env}'")
                removed_count += 1
        else:
            console.print(f"[yellow]Not found:[/yellow] {package}")

    if removed_count > 0:
        save_config(config)
        console.print(f"\n[blue]Summary:[/blue] {removed_count} package(s) removed")
        console.print("Run 'envknit lock' to update the lock file")


# ============================================================================
# RUN COMMAND
# ============================================================================

@app.command()
@click.argument("command", nargs=-1, required=True)
@click.option("--env", "-e", default=DEFAULT_ENV, help="Environment to use")
def run(command: tuple[str, ...], env: str) -> None:
    """
    Run a command in an isolated environment.

    \b
    Examples:
        envknit run python script.py
        envknit run --env data jupyter lab
    """
    import subprocess

    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found.")
        raise SystemExit(1)

    # Build environment name
    env_target = f"envknit-{config.name}-{env}"

    # Check if environment exists
    backend = get_backend(config)
    existing_envs = [e.name for e in backend.list_environments()]

    if env_target not in existing_envs:
        console.print(f"[red]Error:[/red] Environment '{env_target}' not found")
        console.print(f"Run 'envknit install --env {env}' first")
        raise SystemExit(1)

    console.print(f"[blue]Running in '{env}':[/blue] {' '.join(command)}")

    # Run command in conda environment
    executable = backend._get_executable()
    full_cmd = [executable, "run", "-n", env_target] + list(command)

    result = subprocess.run(full_cmd)
    raise SystemExit(result.returncode)


# ============================================================================
# ENV GROUP COMMANDS
# ============================================================================

@app.group()
def env_cmd() -> None:
    """Manage environments."""
    pass


@env_cmd.command("list")
def env_list() -> None:
    """List all environments."""
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found.")
        raise SystemExit(1)

    if not config.environments:
        console.print("[yellow]No environments defined[/yellow]")
        return

    table = Table(title="Environments")
    table.add_column("Name", style="cyan")
    table.add_column("Python", style="green")
    table.add_column("Packages", style="yellow")
    table.add_column("Channels", style="magenta")

    for name, env_config in config.environments.items():
        python = env_config.python
        packages = str(len(env_config.packages))
        channels = ", ".join(env_config.channels[:2])
        if len(env_config.channels) > 2:
            channels += f" (+{len(env_config.channels) - 2})"
        table.add_row(name, python, packages, channels or "default")

    console.print(table)


@env_cmd.command("create")
@click.argument("name")
@click.option("--python", "-p", default="3.11", help="Python version")
def env_create(name: str, python: str) -> None:
    """Create a new environment."""
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found.")
        raise SystemExit(1)

    if name in config.environments:
        console.print(f"[red]Error:[/red] Environment '{name}' already exists")
        raise SystemExit(1)

    config.add_environment(
        name,
        EnvironmentConfig(
            python=python,
            packages=[],
            channels=["conda-forge"],
        )
    )

    save_config(config)
    console.print(f"[green]Created[/green] environment '{name}' with Python {python}")


@env_cmd.command("remove")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Force removal without confirmation")
def env_remove(name: str, force: bool) -> None:
    """Remove an environment."""
    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found.")
        raise SystemExit(1)

    if name not in config.environments:
        console.print(f"[red]Error:[/red] Environment '{name}' not found")
        raise SystemExit(1)

    if not force and not Confirm.ask(f"Remove environment '{name}'?"):
        return

    config.remove_environment(name)
    save_config(config)

    console.print(f"[green]Removed[/green] environment '{name}'")


# Register env group
app.add_command(env_cmd, name="env")


# ============================================================================
# STATUS COMMAND
# ============================================================================

@app.command()
def status() -> None:
    """Show project status."""
    config = load_config()

    if config is None:
        console.print(f"[red]Not an envknit project[/red] (no {CONFIG_FILE} found)")
        raise SystemExit(1)

    # Display project info
    console.print(f"\n[cyan]Project:[/cyan] {config.name}")
    console.print(f"[cyan]Version:[/cyan] {config.version}")

    # Environments
    console.print(f"\n[cyan]Environments:[/cyan] {len(config.environments)}")
    for name, env_config in config.environments.items():
        console.print(f"  - {name} (Python {env_config.python}, {len(env_config.packages)} packages)")

    # Lock file status
    lock = load_lock()
    if lock:
        total_packages = sum(len(pkgs) for pkgs in lock.environments.values())
        console.print(f"\n[green]Lock file:[/green] Present ({total_packages} packages locked)")
    else:
        console.print("\n[yellow]Lock file:[/yellow] Not generated")

    # Backend status
    backend = get_backend(config)
    backend_name = backend.name

    if backend.is_available():
        if backend_name == "conda":
            info = backend.detect_conda()
            console.print(f"\n[green]Backend:[/green] {info['type']} {info['version']}")
        elif backend_name == "pip":
            info = backend.detect_pip()
            console.print(f"\n[green]Backend:[/green] pip {info['version']} (python {info['python']})")
        elif backend_name == "poetry":
            info = backend.detect_poetry()
            console.print(f"\n[green]Backend:[/green] poetry {info['version']}")
        else:
            console.print(f"\n[green]Backend:[/green] {backend_name}")
    else:
        console.print(f"\n[red]Backend:[/red] {backend_name} not available")


# ============================================================================
# STORE COMMANDS - Central Package Repository Management
# ============================================================================

@app.group()
def store_cmd() -> None:
    """Manage central package repository."""
    pass


@store_cmd.command("list")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all versions")
@click.option("--package", "-p", default=None, help="Filter by package name")
def store_list(show_all: bool, package: str | None) -> None:
    """
    List packages in the central repository.

    \b
    Examples:
        envknit store list
        envknit store list --all
        envknit store list --package numpy
    """
    store = EnvironmentStore()

    if package:
        # Show versions for specific package
        versions = store.list_installed_versions(package)
        if not versions:
            console.print(f"[yellow]No versions of '{package}' installed[/yellow]")
            return

        console.print(f"\n[cyan]{package}[/cyan] - {len(versions)} version(s) installed:")
        for version in versions:
            metadata = store.get_package_metadata(package, version)
            if metadata:
                ref_count = metadata.reference_count
                created = metadata.installed_at or "unknown"
                console.print(f"  - {version} [dim](refs: {ref_count}, installed: {created[:10] if created != 'unknown' else 'unknown'})[/dim]")
    else:
        # List all packages
        packages = store.list_installed()

        if not packages:
            console.print("[yellow]No packages in central repository[/yellow]")
            console.print(f"Repository location: {store.PACKAGES_DIR}")
            return

        # Group by package name
        by_name: dict[str, list[PackageMetadata]] = {}
        for pkg in packages:
            if pkg.name not in by_name:
                by_name[pkg.name] = []
            by_name[pkg.name].append(pkg)

        console.print(f"\n[cyan]Central Repository[/cyan] ({store.PACKAGES_DIR})")
        console.print(f"[dim]{len(by_name)} packages, {len(packages)} versions total[/dim]\n")

        table = Table()
        table.add_column("Package", style="cyan")
        table.add_column("Versions", style="green")
        table.add_column("Refs", justify="right")

        for name in sorted(by_name.keys()):
            pkg_versions = by_name[name]
            versions_str = ", ".join(p.version for p in pkg_versions[:3])
            if len(pkg_versions) > 3 and not show_all:
                versions_str += f" (+{len(pkg_versions) - 3})"
            elif show_all:
                versions_str = ", ".join(p.version for p in pkg_versions)

            total_refs = sum(p.reference_count for p in pkg_versions)
            table.add_row(name, versions_str, str(total_refs))

        console.print(table)


@store_cmd.command("stats")
def store_stats() -> None:
    """Show central repository statistics."""
    store = EnvironmentStore()
    stats = store.get_storage_stats()

    console.print("\n[cyan]Central Repository Statistics[/cyan]\n")

    console.print(f"Location: {stats['packages_dir']}")
    console.print(f"Unique packages: {stats['total_packages']}")
    console.print(f"Total versions: {stats['total_versions']}")
    console.print(f"Total references: {stats['total_references']}")

    if stats['estimated_size_bytes']:
        size_mb = stats['estimated_size_bytes'] / (1024 * 1024)
        console.print(f"Estimated size: {size_mb:.2f} MB")


@store_cmd.command("cleanup")
@click.option("--dry-run", is_flag=True, default=True, help="Preview without removing")
@click.option("--force", is_flag=True, default=False, help="Actually remove packages")
def store_cleanup(dry_run: bool, force: bool) -> None:
    """
    Remove unused packages from the repository.

    By default, runs in dry-run mode to preview what would be removed.
    Use --force to actually remove packages.

    \b
    Examples:
        envknit store cleanup            # Dry run
        envknit store cleanup --force    # Actually remove
    """
    store = EnvironmentStore()

    if dry_run and not force:
        console.print("[blue]Dry run - no packages will be removed[/blue]\n")

    removed = store.cleanup_unused_packages(dry_run=(dry_run and not force))

    if not removed:
        console.print("[green]No unused packages found[/green]")
    else:
        console.print(f"\n[yellow]{'Would remove' if (dry_run and not force) else 'Removed'} {len(removed)} unused packages:[/yellow]")
        for pkg_id in removed:
            console.print(f"  - {pkg_id}")


@store_cmd.command("remove")
@click.argument("package")
@click.argument("version", required=False)
@click.option("--force", "-f", is_flag=True, help="Force removal even if referenced")
def store_remove(package: str, version: str | None, force: bool) -> None:
    """
    Remove a package from the central repository.

    \b
    Examples:
        envknit store remove numpy 1.26.0
        envknit store remove numpy 1.26.0 --force
    """
    store = EnvironmentStore()

    if version:
        # Remove specific version
        if not store.is_installed(package, version):
            console.print(f"[red]Error:[/red] {package}=={version} not found in repository")
            raise SystemExit(1)

        metadata = store.get_package_metadata(package, version)
        if metadata and metadata.reference_count > 0 and not force:
            console.print(f"[yellow]Warning:[/yellow] {package}=={version} is referenced by {metadata.reference_count} projects")
            if not Confirm.ask("Remove anyway?"):
                return
            force = True

        if store.uninstall_package(package, version, force=force):
            console.print(f"[green]Removed:[/green] {package}=={version}")
        else:
            console.print(f"[red]Failed to remove:[/red] {package}=={version}")
    else:
        # Remove all versions
        versions = store.list_installed_versions(package)
        if not versions:
            console.print(f"[red]Error:[/red] No versions of '{package}' found in repository")
            raise SystemExit(1)

        console.print(f"[yellow]Found {len(versions)} version(s) of {package}:[/yellow]")
        for v in versions:
            console.print(f"  - {v}")

        if not Confirm.ask(f"Remove all versions of {package}?"):
            return

        removed = 0
        for v in versions:
            if store.uninstall_package(package, v, force=True):
                removed += 1

        console.print(f"[green]Removed {removed}/{len(versions)} versions of {package}[/green]")


@store_cmd.command("path")
@click.argument("package")
@click.argument("version", required=False)
def store_path(package: str, version: str | None) -> None:
    """
    Show the path to a package in the repository.

    \b
    Examples:
        envknit store path numpy 1.26.0
        envknit store path numpy  # Shows all versions
    """
    store = EnvironmentStore()

    if version:
        path = store.get_package_path(package, version)
        if path:
            console.print(str(path))
        else:
            console.print(f"[red]Error:[/red] {package}=={version} not found")
            raise SystemExit(1)
    else:
        versions = store.list_installed_versions(package)
        if not versions:
            console.print(f"[red]Error:[/red] No versions of '{package}' found")
            raise SystemExit(1)

        for v in versions:
            path = store.get_package_path(package, v)
            console.print(f"{package}=={v}: {path}")


@store_cmd.command("cache")
@click.option("--clear", is_flag=True, help="Clear all cache")
@click.option("--stats", is_flag=True, help="Show cache statistics")
def store_cache(clear: bool, stats: bool) -> None:
    """
    Manage version cache.

    \b
    Examples:
        envknit store cache --stats
        envknit store cache --clear
    """
    cache = PackageCache()

    if clear:
        cache.invalidate()
        console.print("[green]Cache cleared[/green]")
        return

    if stats:
        cache_stats = cache.get_stats()
        console.print("\n[cyan]Version Cache Statistics[/cyan]\n")
        console.print(f"Cache location: {cache_stats['cache_dir']}")
        console.print(f"Total entries: {cache_stats['total_entries']}")
        console.print(f"Cache TTL: {cache_stats['ttl_seconds']} seconds")
        if cache_stats['cache_size_bytes']:
            size_kb = cache_stats['cache_size_bytes'] / 1024
            console.print(f"Cache size: {size_kb:.2f} KB")
        if cache_stats.get('by_backend'):
            console.print("\nBy backend:")
            for backend, count in cache_stats['by_backend'].items():
                console.print(f"  {backend}: {count} entries")
        return

    # Default: show usage
    console.print("Use --stats to show cache statistics or --clear to clear cache")


# Register store group
app.add_command(store_cmd, name="store")


# ============================================================================
# SHIM COMMANDS - CLI Tool Shim Management
# ============================================================================

@app.group()
def shim_cmd() -> None:
    """Manage CLI tool shims for automatic version switching."""
    pass


@shim_cmd.command("install")
@click.option("--tools", "-t", multiple=True, help="Specific tools to install shims for")
@click.option("--all", "-a", "install_all", is_flag=True, help="Install all default tool shims")
def shim_install(tools: tuple[str, ...], install_all: bool) -> None:
    """
    Install CLI tool shims.

    Shims are wrapper scripts that automatically select the correct version
    of a tool (python, pip, etc.) based on the current project's configuration.

    \b
    Examples:
        envknit shim install --all            # Install all default shims
        envknit shim install -t python -t pip # Install specific shims
    """
    from envknit.isolation.shim import CLIShimGenerator

    generator = CLIShimGenerator()

    # Determine which tools to install
    tools_to_install = generator.DEFAULT_TOOLS if install_all or not tools else list(tools)

    console.print(f"[blue]Installing shims to {generator.shim_dir}[/blue]\n")

    installed = []
    for tool in tools_to_install:
        try:
            shim_path = generator.generate_shim(tool)
            console.print(f"  [green]Created:[/green] {tool} -> {shim_path}")
            installed.append(tool)
        except Exception as e:
            console.print(f"  [red]Failed:[/red] {tool} - {e}")

    console.print(f"\n[green]Installed {len(installed)} shims[/green]")
    console.print("\nTo activate, add to your shell:")
    console.print(f"  export PATH=\"{generator.shim_dir}:$PATH\"")
    console.print("\nOr run: envknit init-shell bash  # or zsh, fish")


@shim_cmd.command("uninstall")
@click.option("--tools", "-t", multiple=True, help="Specific tools to uninstall")
@click.option("--all", "-a", "uninstall_all", is_flag=True, help="Uninstall all shims")
def shim_uninstall(tools: tuple[str, ...], uninstall_all: bool) -> None:
    """
    Uninstall CLI tool shims.

    \b
    Examples:
        envknit shim uninstall --all       # Remove all shims
        envknit shim uninstall -t python   # Remove specific shim
    """
    from envknit.isolation.shim import CLIShimGenerator

    generator = CLIShimGenerator()

    if uninstall_all or (not tools):
        count = generator.remove_all_shims()
        console.print(f"[green]Removed {count} shims from {generator.shim_dir}[/green]")
    else:
        for tool in tools:
            if generator.remove_shim(tool):
                console.print(f"[green]Removed:[/green] {tool}")
            else:
                console.print(f"[yellow]Not found:[/yellow] {tool}")


@shim_cmd.command("list")
def shim_list() -> None:
    """
    List installed CLI tool shims.

    \b
    Examples:
        envknit shim list
    """
    from envknit.isolation.shim import CLIShimGenerator

    generator = CLIShimGenerator()

    shims = generator.list_shims()

    if not shims:
        console.print("[yellow]No shims installed[/yellow]")
        console.print("Run 'envknit shim install --all' to install shims")
        return

    console.print(f"\n[cyan]Installed Shims[/cyan] ({generator.shim_dir})\n")

    table = Table()
    table.add_column("Tool", style="cyan")
    table.add_column("Path", style="dim")

    for shim in sorted(shims):
        table.add_row(shim, str(generator.shim_dir / shim))

    console.print(table)


# Register shim group
app.add_command(shim_cmd, name="shim")


# ============================================================================
# INIT-SHELL COMMAND - Shell Integration
# ============================================================================

@app.command("init-shell")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish", "auto"]))
@click.option("--install", "-i", is_flag=True, help="Install to shell config file")
@click.option("--uninstall", "-u", is_flag=True, help="Remove from shell config file")
def init_shell(shell: str, install: bool, uninstall: bool) -> None:
    """
    Generate or install shell initialization script.

    This command outputs shell code that:
    1. Adds envknit shims directory to PATH
    2. Sets up automatic version detection on directory change

    \b
    Examples:
        envknit init-shell zsh           # Print init script for zsh
        envknit init-shell bash --install # Install to ~/.bashrc
        envknit init-shell auto          # Auto-detect current shell
        eval "$(envknit init-shell zsh)" # Evaluate in shell
    """
    from envknit.isolation.shim import ShellIntegration

    integration = ShellIntegration()

    # Auto-detect shell if requested
    if shell == "auto":
        shell = integration.detect_current_shell()
        if shell == "unknown":
            console.print("[red]Error:[/red] Could not detect current shell")
            console.print("Please specify: bash, zsh, or fish")
            raise SystemExit(1)
        console.print(f"[dim]Detected shell: {shell}[/dim]")

    if uninstall:
        # Remove from shell config
        if shell == "bash":
            success = integration.uninstall_bash()
        elif shell == "zsh":
            success = integration.uninstall_zsh()
        elif shell == "fish":
            success = integration.uninstall_fish()
        else:
            success = False

        if success:
            console.print(f"[green]Removed envknit initialization from {shell} config[/green]")
        else:
            console.print(f"[yellow]No envknit initialization found in {shell} config[/yellow]")
        return

    if install:
        # Install to shell config
        if shell == "bash":
            success = integration.install_bash()
        elif shell == "zsh":
            success = integration.install_zsh()
        elif shell == "fish":
            success = integration.install_fish()
        else:
            success = False

        if success:
            console.print(f"[green]Installed envknit initialization to {shell} config[/green]")
            console.print("\nRestart your shell or run:")
            console.print(f"  source ~/{'.zshrc' if shell == 'zsh' else '.bashrc' if shell == 'bash' else '.config/fish/config.fish'}")
        return

    # Just print the init script
    init_script = integration.get_init_script(shell)
    console.print(init_script, end="")


# ============================================================================
# AUTO COMMAND - Automatic Version Detection
# ============================================================================

@app.command("auto")
@click.option("--verbose", "-v", is_flag=True, help="Show verbose output")
def auto_cmd(verbose: bool) -> None:
    """
    Automatically detect and set environment for current directory.

    This command is typically called automatically when changing directories
    (via shell hooks). It looks for envknit.yaml and sets up the environment.

    \b
    Examples:
        envknit auto              # Auto-detect and configure
        envknit auto --verbose    # Show what's being detected
    """
    from envknit.isolation.shim import ToolDispatcher

    dispatcher = ToolDispatcher()

    # Find project root
    project_root = dispatcher.find_project_root()

    if project_root is None:
        if verbose:
            console.print("[dim]No envknit project found in current directory[/dim]")
        return

    if verbose:
        console.print(f"[cyan]Project root:[/cyan] {project_root}")

    # Find lock file
    lock_file = dispatcher.find_lock_file(project_root)

    if lock_file is None:
        if verbose:
            console.print("[dim]No lock file found. Run 'envknit lock' first.[/dim]")
        return

    if verbose:
        console.print(f"[cyan]Lock file:[/cyan] {lock_file}")

        # Show available tools
        console.print("\n[cyan]Available tools in project environment:[/cyan]")
        for tool in ["python", "pip"]:
            tool_path = dispatcher.get_tool_path(tool, project_root)
            if tool_path:
                console.print(f"  {tool}: {tool_path}")
            else:
                console.print(f"  {tool}: [dim]system default[/dim]")

    # In a real implementation, we might set environment variables here
    # For now, this is mainly informational and used by the shell hooks


# ============================================================================
# EXPORT COMMAND - Export to various formats
# ============================================================================

@app.command()
@click.option("--for-ai", is_flag=True, help="Export AI-friendly context (markdown)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--format", "-f", "export_format",
              type=click.Choice(["context", "requirements", "environment", "pep621"]),
              default="context",
              help="Export format (context, requirements, environment, pep621)")
@click.option("--env", "-e", default=None, help="Specific environment to export")
def export(for_ai: bool, output_json: bool, output: str | None, export_format: str, env: str | None) -> None:
    """
    Export project context and dependencies to various formats.

    \b
    Examples:
        envknit export --for-ai                    # AI-friendly markdown context
        envknit export --for-ai --json             # AI-friendly JSON context
        envknit export --for-ai -o context.md      # Save to file
        envknit export --format requirements       # requirements.txt format
        envknit export --format environment        # environment.yml format
        envknit export --env data                  # Export specific environment
    """
    import json as json_module

    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found. Run 'envknit init' first.")
        raise SystemExit(1)

    # Load lock file
    lock = load_lock()

    if lock is None and export_format in ["requirements", "environment"]:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Import AI context generator
    from envknit.ai.context import AIContextGenerator

    # Create generator
    generator = AIContextGenerator(config, lock)

    # Determine output format
    if for_ai:
        # AI-friendly output
        if output_json:
            content = json_module.dumps(generator.to_json(), indent=2)
        else:
            content = generator.to_markdown()
    else:
        # Other formats
        if export_format == "requirements":
            content = generator.generate().to_requirements_txt(env)
        elif export_format == "environment":
            env_name = env or "default"
            content = generator.generate().to_environment_yml(env_name)
        elif export_format == "pep621":
            content = _generate_pep621(config, lock)
        else:
            # Default: markdown context
            if output_json:
                content = json_module.dumps(generator.to_json(), indent=2)
            else:
                content = generator.to_markdown()

    # Output result
    if output:
        output_path = Path(output)
        output_path.write_text(content)
        console.print(f"[green]Exported to:[/green] {output_path}")
    else:
        # Print to stdout
        console.print(content)


def _generate_pep621(config: Config, lock: LockFile | None) -> str:
    """Generate PEP 621 compliant pyproject.toml section."""
    lines = [
        "# Project metadata (PEP 621)",
        "[project]",
        f'name = "{config.name}"',
        f'version = "{config.version}"',
    ]

    # Add Python version
    if config.environments:
        default_env = config.environments.get("default")
        if default_env:
            lines.append(f'requires-python = ">={default_env.python}"')

    # Add dependencies
    if lock:
        direct_deps = [
            pkg for pkg in lock.packages
            if pkg.selection_reason and pkg.selection_reason.type == "direct"
        ]
        if direct_deps:
            lines.append("dependencies = [")
            for pkg in direct_deps:
                lines.append(f'    "{pkg.name}>={pkg.version}",')
            lines.append("]")

    lines.append("")
    lines.append("[build-system]")
    lines.append('requires = ["hatchling"]')
    lines.append('build-backend = "hatchling.build"')

    return "\n".join(lines)


# ============================================================================
# SECURITY COMMANDS - Vulnerability Scanning
# ============================================================================

@app.group()
def security_cmd() -> None:
    """Security vulnerability scanning and management."""
    pass


@security_cmd.command("scan")
@click.option("--env", "-e", default=None, help="Specific environment to scan")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output")
@click.option("--no-cache", is_flag=True, help="Skip cache, force fresh scan")
@click.option("--backend",
              type=click.Choice(["auto", "pip-audit", "pypi-api"]),
              default="auto",
              help="Scan backend to use")
def security_scan(
    env: str | None,
    output_json: bool,
    verbose: bool,
    no_cache: bool,
    backend: str
) -> None:
    """
    Scan packages for known security vulnerabilities.

    Checks installed packages against known vulnerability databases
    and reports any issues found.

    \b
    Examples:
        envknit security scan              # Scan all packages
        envknit security scan --json       # JSON output
        envknit security scan --verbose    # Detailed output
        envknit security scan --env data   # Scan specific environment
        envknit security scan --no-cache   # Force fresh scan
    """
    from envknit.security import VulnerabilityScanner

    config = load_config()

    if config is None:
        console.print(f"[red]Error:[/red] No {CONFIG_FILE} found. Run 'envknit init' first.")
        raise SystemExit(1)

    # Load lock file
    lock = load_lock()

    if lock is None:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Determine which environments to scan
    if env:
        if env not in lock._env_packages:
            console.print(f"[red]Error:[/red] Environment '{env}' not found in lock file")
            raise SystemExit(1)
        envs_to_scan = {env: lock._env_packages[env]}
    else:
        envs_to_scan = lock._env_packages

    if not envs_to_scan:
        console.print("[yellow]No packages to scan[/yellow]")
        return

    # Collect all packages
    all_packages = []
    seen = set()
    for _, packages in envs_to_scan.items():
        for pkg in packages:
            key = (pkg.name.lower(), pkg.version)
            if key not in seen:
                all_packages.append(pkg)
                seen.add(key)

    # Initialize scanner
    scanner = VulnerabilityScanner(backend=backend)

    console.print(f"[blue]Scanning {len(all_packages)} packages for vulnerabilities...[/blue]")
    console.print(f"[dim]Backend: {scanner.get_backend_name()}[/dim]\n")

    # Clear cache if requested
    if no_cache:
        scanner.clear_cache()

    # Run scan
    result = scanner.scan_all(all_packages, use_cache=not no_cache)

    # JSON output
    if output_json:
        import json as json_module
        console.print_json(json_module.dumps(result.to_dict(), indent=2))
        return

    # Rich output
    _display_scan_result(result, verbose)

    # Exit with error code if critical vulnerabilities found
    if result.has_critical:
        raise SystemExit(1)


def _display_scan_result(result, verbose: bool) -> None:
    """Display scan results in rich format."""
    from envknit.security import VulnerabilitySeverity

    console.print("\n[bold]Security Scan Results[/bold]")
    console.print("━" * 60)

    # Summary
    console.print(f"\nScanned [cyan]{result.total_scanned}[/cyan] packages")

    if result.cache_hit:
        console.print("[dim](Results from cache)[/dim]")

    if result.is_clean:
        console.print("\n[green]✓ No known vulnerabilities found[/green]")
        return

    # Group by severity
    sorted_vulns = result.get_sorted()

    # Count by severity
    severity_counts = {
        VulnerabilitySeverity.CRITICAL: 0,
        VulnerabilitySeverity.HIGH: 0,
        VulnerabilitySeverity.MEDIUM: 0,
        VulnerabilitySeverity.LOW: 0,
    }

    for vuln in sorted_vulns:
        severity_counts[vuln.severity] += 1

    # Display by severity
    for severity in [
        VulnerabilitySeverity.CRITICAL,
        VulnerabilitySeverity.HIGH,
        VulnerabilitySeverity.MEDIUM,
        VulnerabilitySeverity.LOW,
    ]:
        count = severity_counts[severity]
        if count == 0:
            continue

        vulns = result.get_by_severity(severity)
        color = severity.color()

        console.print(f"\n[{color}]{severity.value} ({count})[/{color}]")

        for vuln in vulns:
            if verbose:
                # Detailed output
                console.print(f"┌{'─' * 50}┐")
                console.print(f"│ [bold]{vuln.package} {vuln.installed_version}[/bold]")

                # Wrap description
                desc = vuln.description[:80] + "..." if len(vuln.description) > 80 else vuln.description
                console.print(f"│ [{color}]{vuln.id}[/{color}]: {desc}")

                if vuln.fixed_version:
                    console.print(f"│ Fixed in: {vuln.fixed_version}")
                    console.print(f"│ [yellow]→ Update: {vuln.get_update_command()}[/yellow]")

                if vuln.reference:
                    console.print(f"│ [dim]{vuln.reference}[/dim]")

                console.print(f"└{'─' * 50}┘")
            else:
                # Compact output
                fix_info = f" → fixed in {vuln.fixed_version}" if vuln.fixed_version else ""
                console.print(f"  - [{color}]{vuln.package} {vuln.installed_version}[/{color}]: {vuln.id}{fix_info}")

    # Summary statistics
    clean_count = result.total_scanned - len(result.vulnerable_packages)

    console.print(f"\n[green]No issues in {clean_count} packages.[/green]")

    # Recommendations
    console.print("\n[bold]Recommendations:[/bold]")

    # Critical first
    critical_vulns = result.get_by_severity(VulnerabilitySeverity.CRITICAL)
    if critical_vulns:
        for vuln in critical_vulns[:3]:
            console.print(f"  [red bold]1.[/red bold] Update {vuln.package} to >={vuln.fixed_version} [red](CRITICAL)[/red]")

    high_vulns = result.get_by_severity(VulnerabilitySeverity.HIGH)
    if high_vulns:
        offset = 1 if critical_vulns else 0
        console.print(f"  [yellow]{1 + offset}.[/yellow] Review {len(high_vulns)} HIGH severity vulnerabilities")

    medium_vulns = result.get_by_severity(VulnerabilitySeverity.MEDIUM)
    if medium_vulns:
        offset = 1 if critical_vulns else 0
        offset += 1 if high_vulns else 0
        console.print(f"  [dim]{1 + offset}.[/dim] Review {len(medium_vulns)} MEDIUM severity vulnerabilities")


@security_cmd.command("check")
@click.argument("package", required=False)
@click.option("--version", "-v", default=None, help="Specific version to check")
def security_check(package: str | None, version: str | None) -> None:
    """
    Check a specific package for vulnerabilities.

    \b
    Examples:
        envknit security check numpy          # Check numpy from lock file
        envknit security check numpy -v 1.24.0  # Check specific version
    """
    from envknit.security import VulnerabilityScanner

    scanner = VulnerabilityScanner()

    # If no package specified, show usage
    if not package:
        console.print("[yellow]Usage: envknit security check <package> [--version <version>][/yellow]")
        return

    # Get version from lock file if not specified
    if not version:
        lock = load_lock()
        if lock:
            locked_pkg = lock.get_package(package)
            if locked_pkg:
                version = locked_pkg.version
                console.print(f"[dim]Checking {package}=={version} (from lock file)[/dim]")
            else:
                console.print(f"[red]Error:[/red] Package '{package}' not found in lock file")
                console.print("Use --version to specify a version")
                raise SystemExit(1)
        else:
            console.print("[red]Error:[/red] No lock file found. Use --version to specify a version.")
            raise SystemExit(1)

    # Scan
    console.print(f"[blue]Checking {package}=={version}...[/blue]\n")

    vulnerabilities = scanner.scan_package(package, version)

    if not vulnerabilities:
        console.print(f"[green]✓ No known vulnerabilities in {package}=={version}[/green]")
        return

    # Display results
    for vuln in vulnerabilities:
        color = vuln.severity.color()
        console.print(f"\n[{color}]{vuln.severity.value}: {vuln.id}[/{color}]")
        console.print(f"  Package: {vuln.package} {vuln.installed_version}")
        console.print(f"  Fixed in: {vuln.fixed_version or 'Unknown'}")

        if vuln.description:
            console.print(f"  Description: {vuln.description}")

        if vuln.reference:
            console.print(f"  Reference: [link={vuln.reference}]{vuln.reference}[/link]")

        console.print(f"\n  [yellow]Fix: {vuln.get_update_command()}[/yellow]")


@security_cmd.command("update-check")
@click.option("--env", "-e", default=None, help="Specific environment to check")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--security-only", is_flag=True, help="Only show security-related updates")
def security_update_check(
    env: str | None,
    output_json: bool,
    security_only: bool
) -> None:
    """
    Check for available package updates with security context.

    Shows which packages have updates available and whether they
    fix security vulnerabilities.

    \b
    Examples:
        envknit security update-check           # Check all packages
        envknit security update-check --env default
        envknit security update-check --security-only  # Only security updates
    """
    from envknit.security import VulnerabilityScanner

    lock = load_lock()

    if lock is None:
        console.print("[red]Error:[/red] No lock file found. Run 'envknit lock' first.")
        raise SystemExit(1)

    # Determine which environments to check
    if env:
        if env not in lock._env_packages:
            console.print(f"[red]Error:[/red] Environment '{env}' not found in lock file")
            raise SystemExit(1)
        envs_to_check = {env: lock._env_packages[env]}
    else:
        envs_to_check = lock._env_packages

    # Collect all packages
    all_packages = []
    seen = set()
    for _, packages in envs_to_check.items():
        for pkg in packages:
            key = (pkg.name.lower(), pkg.version)
            if key not in seen:
                all_packages.append(pkg)
                seen.add(key)

    # Initialize scanner
    scanner = VulnerabilityScanner()

    console.print(f"[blue]Checking for updates in {len(all_packages)} packages...[/blue]\n")

    # Check updates
    recommendations = scanner.check_updates(all_packages)

    # Filter if security-only
    if security_only:
        recommendations = [r for r in recommendations if r.is_security_update]

    if not recommendations:
        if security_only:
            console.print("[green]✓ No security updates available[/green]")
        else:
            console.print("[green]✓ All packages are up to date[/green]")
        return

    # JSON output
    if output_json:
        import json as json_module
        data = [r.to_dict() for r in recommendations]
        console.print_json(json_module.dumps(data, indent=2))
        return

    # Rich output
    table = Table(title="Available Updates")
    table.add_column("Package", style="cyan")
    table.add_column("Current", style="yellow")
    table.add_column("Latest", style="green")
    table.add_column("Security", style="red")

    for rec in sorted(recommendations, key=lambda r: (not r.is_security_update, r.package)):
        security_marker = "[red]![/red]" if rec.is_security_update else ""
        table.add_row(
            rec.package,
            rec.current_version,
            rec.latest_version,
            security_marker
        )

    console.print(table)

    # Show security updates
    security_updates = [r for r in recommendations if r.is_security_update]
    if security_updates:
        console.print(f"\n[red bold]Security Updates ({len(security_updates)}):[/red bold]")
        for rec in security_updates:
            console.print(f"  - {rec.package}: {rec.current_version} → {rec.latest_version}")
            if rec.vulnerabilities_fixed:
                console.print(f"    [dim]Fixes: {', '.join(rec.vulnerabilities_fixed[:3])}[/dim]")

    # Summary
    console.print("\n[dim]Run 'envknit add <package>>=<version>' to update specific packages[/dim]")


# ============================================================================
# ACTIVATE / DEACTIVATE - Conda-like activation
# ============================================================================

ENVKNIT_SHIMS_DIR = Path.home() / ".envknit" / "shims"


@app.command()
def activate() -> None:
    """
    Activate envknit for the current shell session.

    This enables:
    - Shims for automatic version switching
    - Auto-detection on directory change
    - Prompt indicator (envknit)

    Usage:
        eval "$(envknit activate)"

    To deactivate:
        eval "$(envknit deactivate)"
    """
    # Output shell code that modifies the current shell
    shims_dir = ENVKNIT_SHIMS_DIR

    script = f'''
# EnvKnit activation
export ENVKNIT_ACTIVE=1
export PATH="{shims_dir}:$PATH"

# Save original prompt
if [ -z "$ENVKNIT_OLD_PS1" ]; then
    export ENVKNIT_OLD_PS1="$PS1"
fi

# Set prompt with (envknit) prefix
export PS1="(envknit) $ENVKNIT_OLD_PS1"

# chpwd hook for auto-detection
_envknit_chpwd() {{
    envknit auto 2>/dev/null || true
}}

# Add to chpwd_functions
if ! (( ${{chpwd_functions[(I)_envknit_chpwd]}} )); then
    chpwd_functions=(_envknit_chpwd $chpwd_functions)
fi

# Run initial auto
envknit auto 2>/dev/null || true
'''
    print(script)


@app.command()
def deactivate() -> None:
    """
    Deactivate envknit for the current shell session.

    Usage:
        eval "$(envknit deactivate)"
    """
    script = '''
# EnvKnit deactivation
export ENVKNIT_ACTIVE=0

# Remove shims from PATH
export PATH=$(echo "$PATH" | sed 's|[^:]*\.envknit/shims:*||g' | sed 's|:$||' | sed 's|::|:|g')

# Restore prompt
if [ -n "$ENVKNIT_OLD_PS1" ]; then
    export PS1="$ENVKNIT_OLD_PS1"
    unset ENVKNIT_OLD_PS1
fi

# Remove chpwd hook
chpwd_functions=(${chpwd_functions:#_envknit_chpwd})

echo "envknit deactivated"
'''
    print(script)


# Register security group
app.add_command(security_cmd, name="security")


if __name__ == "__main__":
    app()
