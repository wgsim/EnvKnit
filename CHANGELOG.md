# Changelog

All notable changes to EnvKnit are documented here.

---

## [0.1.0] — 2026-02-27

### Added

#### Core architecture
- **Split CLI/library architecture**: `envknit-cli` (standalone binary) and `envknit` (pip library) communicate only through `envknit.lock.yaml` — no shared Python environment
- **PubGrub dependency resolver** with transitive dependency resolution enabled by default, semantic conflict detection (not just syntactic), and cache invalidation on backtrack
- **Lock file contract** (`envknit.lock.yaml`): `schema_version` gate, `install_path` field per package, schema forward-compatibility check (`SchemaVersionError` for future major versions)

#### Runtime import isolation
- **`VersionedFinder`** — `sys.meta_path` hook that routes `import` to versioned install paths
- **`VersionContext`** — context manager implementing per-context module isolation via `ContextVar` (`_active_versions`, `_ctx_modules`); async-safe and thread-safe
- **`_CachedModuleLoader` + `_CtxCachingLoader`** — fast-path cache for repeated imports within the same context; modules are cached on first load
- **`configure_from_lock()`** — loads `envknit.lock.yaml`, registers all versioned install paths, auto-installs import hook; supports `env` filter and deduplication

#### Hybrid C extension detection
- **`_has_c_extensions(path)`** — scans install path for `.so`/`.pyd` files; process-global cache (`_c_ext_detection_cache`)
- **`CExtensionError(ImportError)`** — raised by `use()` when C extensions detected; message includes ready-to-use `worker()` snippet
- Pure-Python packages use `use()` transparently; C extension packages require `worker()`

#### Subprocess worker pool
- **`worker()`** context manager — routes C extension packages through isolated subprocesses
- **`ProcessPool`** — lazy spawn, health checks, graceful SIGTERM → SIGKILL shutdown, `atexit` handler for zombie/SharedMemory cleanup
- **`WorkerContext`** — IPC over `multiprocessing.Pipe`; large arrays via `multiprocessing.shared_memory`

#### CLI (`envknit-cli`)
- Commands: `init`, `add`, `resolve`, `lock`, `install`, `status`, `tree`, `graph`, `why`, `remove`, `run`, `env`, `store`, `shim`, `init-shell`, `auto`, `export`, `security`, `activate`, `deactivate`
- Backends: **conda** (conda/mamba search), **pip** (`pip index versions` + PyPI JSON API fallback), **poetry** (PyPI JSON API)
- `--dry-run` for `resolve`; `--update <pkg>` for `lock`

#### Standalone binary distribution
- **PyInstaller spec** (`envknit-cli.spec`) — single-file binary bundling click, rich, pyyaml, and all EnvKnit internals
- **Build script** (`scripts/build-cli.sh`) — `--clean`, `--strip`, `--upx` flags; ~29 MB output
- **CI workflow** (`.github/workflows/build-cli.yml`) — builds linux/macos/windows artifacts on `v*.*.*` tag push; uploads to GitHub Release

#### Security scanning
- **`VulnerabilityScanner`** — `scan_package()`, `scan_all()`, `check_updates()`
- **`PipAuditBackend`** (preferred) — wraps `pip-audit` CLI, batch scan via stdin
- **`PyPIAPIBackend`** (fallback) — OSV API + PyPI JSON API; CVSS → LOW/MEDIUM/HIGH/CRITICAL mapping
- Result cache: SHA-256 key, 1-hour TTL, disk + memory layers

#### AI context export
- **`AIContextGenerator`** — analyzes `Config` + `LockFile` to produce `AIContext` with dependency summaries, issue detection, and recommendations
- Export formats: Markdown (LLM-ready), `requirements.txt`, conda `environment.yml`, JSON

#### Shim system
- **`ShimGenerator`** — generates Python `__init__.py` shims that redirect imports to versioned install paths
- **`CLIShimGenerator`** — generates executable shim scripts for CLI tools (conda, pip, python, etc.)
- **`ShellIntegration`** — installs `eval "$(envknit init-shell)"` blocks into `.bashrc`/`.zshrc`/`config.fish`; idempotent install/uninstall
- **`ToolDispatcher`** — resolves correct tool path from lock file at runtime, dispatches subprocess

### Infrastructure
- **CI test workflow** (`.github/workflows/test.yml`) — runs `pytest` on Python 3.10–3.13 matrix on push/PR to `main`
- `.gitignore` updated to exclude `.claude/` worktree and session cache

### Tests
- **474 tests** across 17 test files
- Coverage: `ai/context.py` 100%, `config/schema.py` 100%, `security/models.py` 97%, `security/scanner.py` 84%, `storage/cache.py` 90%, `storage/store.py` 66%, `resolver.py` 87%, `lock.py` 82%, `worker.py` 75%, `shim.py` ~55%, overall **51%**

---

## [0.2.0] — 2026-03-26

### Breaking Changes
- **uv is now a required dependency** for `envknit lock` and `envknit install`. The built-in resolver (`resolver.rs`) and `pip install --target` fallback have been removed. If `uv` is not on PATH, `envknit lock` and `envknit install` will fail with a clear error. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### Added
- **`envknit doctor` uv check**: fails with actionable message if uv is absent; warns if below minimum supported version (0.10.7).
- **`SubInterpreterEnv` exported at top-level**: `from envknit import SubInterpreterEnv` now works without importing from `envknit.isolation.subinterpreter`.
- **ContextVar propagation helpers exported at top-level**: `copy_context_to_thread` and related utilities accessible from `envknit` directly.

### Changed
- `envknit install` now uses `uv pip install --target` instead of `pip install --target`. This improves install speed and reliability for packages with complex dependency graphs.

---

## [0.1.2] — 2026-03-24

### Added
- **uv resolver delegation** (`uv_resolver.rs`): `envknit lock` delegates to `uv pip compile` when `uv` is on PATH, falling back to the built-in PubGrub resolver otherwise *(note: uv became required and the built-in resolver was removed in v0.2.0)*. Resolver used is recorded in `lock.resolver_version` (e.g. `uv/0.10.7`).
- **Extras support in lock specs**: `name[extra]>=version` (PEP 508) correctly passed to uv resolver.
- **Security: newline injection guard**: package spec strings are rejected if they contain `\n` or `\r` characters to prevent uv flag injection via crafted package names.
- **`lock_generated_at` timestamp** in lock file for audit trails.
- **Dependency isolation guide** (`docs/guide/dependency-isolation.md`): 9-section document covering version constraints vs installed versions, runtime activation patterns, `sys.modules` conflicts, worker subprocess isolation, and nested dependency conflict resolution strategies.

### Fixed
- `use_uv` flag no longer suppressed during `--dry-run`; dry-run now shows uv-resolved versions (same as real lock).
- `resolver_version` in lock file now correctly reflects `uv/<version>` vs `envknit-builtin/<version>`.

### Changed
- `envknit lock` resolver detection runs once before the environment loop (not per-environment).

## [Unreleased]

### Known limitations
- `isolation/shim.py` 19% → 55% (partial; env management methods require real backend)
- `cli/main.py` 20% → 30% (partial; install/lock commands require real backend)
- C extension in-process multi-version loading permanently impossible; subprocess worker is the only viable path (see `DESIGN_NOTES.md` #5)
- `VersionContext` Category B limitations (global registries, retained references) are fundamental to the Python process model; subprocess isolation required for affected packages (see `DESIGN_NOTES.md` #6)
