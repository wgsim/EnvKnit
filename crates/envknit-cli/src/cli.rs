use clap::{Parser, Subcommand};
use clap_complete::Shell;

#[derive(Subcommand)]
pub enum EnvAction {
    /// List all environments
    List,
    /// Create a new environment
    Create {
        /// Environment name
        name: String,
        #[arg(long)]
        backend: Option<String>,
    },
    /// Remove an environment
    Remove {
        /// Environment name
        name: String,
    },
}

#[derive(Subcommand)]
pub enum StoreAction {
    /// List installed packages
    List {
        #[arg(long)]
        package: Option<String>,
    },
    /// Show store disk usage statistics
    Stats,
    /// Remove packages not referenced by current lock file
    Cleanup {
        #[arg(long)]
        dry_run: bool,
    },
}

#[derive(Parser)]
#[command(
    name = "envknit",
    version,
    about = "Multi-version Python package manager",
    long_about = None,
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Initialize a new EnvKnit project
    Init {
        #[arg(long, default_value = "default")]
        env: String,
        #[arg(long)]
        backend: Option<String>,
    },
    /// Add a package to the configuration
    Add {
        /// Package spec (e.g. numpy, numpy==1.26.4, numpy>=1.24)
        package: String,
        #[arg(long, default_value = "default")]
        env: String,
        #[arg(long)]
        backend: Option<String>,
        /// Add as a development dependency
        #[arg(long)]
        dev: bool,
    },
    /// Remove a package from the configuration
    Remove {
        package: String,
        #[arg(long, default_value = "default")]
        env: String,
        /// Remove from dev dependencies
        #[arg(long)]
        dev: bool,
    },
    /// Resolve dependencies and write lock file
    Lock {
        #[arg(long)]
        update: Option<String>,
        #[arg(long)]
        dry_run: bool,
        /// Only re-lock a specific environment
        #[arg(long)]
        env: Option<String>,
    },
    /// Install packages from lock file
    Install {
        #[arg(long)]
        env: Option<String>,
        /// Skip dev dependencies
        #[arg(long)]
        no_dev: bool,
        /// Remove unreferenced store entries after installation
        #[arg(long)]
        auto_cleanup: bool,
    },
    /// Diagnose environment (pip, python, pyenv, mise, config, lock file)
    Doctor,
    /// Generate shell completion script
    Completions {
        /// Shell to generate completions for
        shell: Shell,
    },
    /// Verify config and lock file are in sync (useful in CI)
    Check,
    /// Verify integrity of installed packages using recorded SHA-256 hashes
    Verify {
        #[arg(long)]
        env: Option<String>,
    },
    /// Compare two lock files and show added/removed/changed packages
    Diff {
        /// Base lock file path
        base: String,
        /// Head lock file path
        head: String,
        /// Scope diff to a specific environment
        #[arg(long)]
        env: Option<String>,
    },
    /// Show status of installed environments
    Status {
        #[arg(long)]
        env: Option<String>,
    },
    /// Show dependency tree
    Tree {
        #[arg(long)]
        env: Option<String>,
        #[arg(long, default_value = "3")]
        depth: usize,
    },
    /// Show dependency graph from lock file
    Graph {
        #[arg(long)]
        env: Option<String>,
        #[arg(long)]
        json: bool,
        #[arg(long, default_value = "0")]
        depth: usize,
    },
    /// Show why a package is installed
    Why {
        package: String,
        #[arg(long)]
        env: Option<String>,
    },
    /// Export configuration in various formats
    Export {
        #[arg(long, default_value = "requirements")]
        format: String,
        #[arg(long)]
        output: Option<String>,
        /// Exclude dev dependencies from output
        #[arg(long)]
        no_dev: bool,
    },
    /// Manage environments
    Env {
        #[command(subcommand)]
        action: EnvAction,
    },
    /// Run a command in an environment's package context
    Run {
        #[arg(long, default_value = "default")]
        env: String,
        /// Exclude dev packages from PYTHONPATH
        #[arg(long)]
        no_dev: bool,
        /// Command and arguments (everything after --)
        #[arg(last = true)]
        command: Vec<String>,
    },
    /// Manage the package store
    Store {
        #[command(subcommand)]
        action: StoreAction,
    },
    /// Print shell integration snippet (use: eval "$(envknit init-shell)")
    InitShell {
        /// Shell name (bash/zsh/fish); defaults to $SHELL
        #[arg(long)]
        shell: Option<String>,
    },
    /// Build and publish to PyPI (wraps `build` + `twine`)
    Publish {
        /// PyPI repository name (default: pypi)
        #[arg(long, default_value = "pypi")]
        repository: String,
        /// Show what would be run without executing
        #[arg(long)]
        dry_run: bool,
    },
    /// Pin config packages to exact versions from the lock file
    Pin {
        #[arg(long, default_value = "default")]
        env: String,
        /// Pin a specific package only (pins all if omitted)
        package: Option<String>,
    },
    /// Upgrade package(s) to latest (removes == pins; keeps flexible constraints)
    Upgrade {
        /// Package name (upgrades all if omitted)
        package: Option<String>,
        #[arg(long, default_value = "default")]
        env: String,
        /// Pin to an explicit version instead of unpinning
        #[arg(long)]
        version: Option<String>,
    },
}
