# Configuration Reference

## Project Configuration (`envknit.yaml`)

### File Location and Discovery

EnvKnit searches for `envknit.yaml` starting from the current working directory
and walking up toward the filesystem root (`Config::find()`). The first file
found wins. This means you can run EnvKnit commands from any subdirectory of
your project and it will locate the correct config.

### Top-Level Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `envknit_version` | `string` | No | Declares the config format version (e.g. `"0.1.0"`). Not validated at runtime; reserved for future compatibility checks. |
| `environments` | `map<string, EnvironmentConfig>` | No | Map of named environments. Keys are environment names (e.g. `default`, `ml`, `frontend`). Defaults to an empty map. |

### Environment Fields

Each key under `environments:` is an environment name. The value is an
`EnvironmentConfig` object with the following fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `python_version` | `string` | None | Python version spec for this environment (e.g. `"3.11"`, `">=3.10"`). |
| `node_version` | `string` | None | Node.js version spec for this environment (e.g. `"20.11"`, `">=20"`). |
| `backend` | `string` | None | Package install backend. Currently only `"pip"` is supported by the CLI. |
| `packages` | `list<PackageSpec>` | `[]` | Production dependencies. |
| `dev_packages` | `list<PackageSpec>` | `[]` | Development-only dependencies. |

### Package Specification Formats

Each entry in `packages` or `dev_packages` can be written in one of two formats.

#### String format

A plain requirement string, identical to a pip requirement specifier:

```yaml
packages:
  - numpy>=1.24
  - requests==2.31.0
  - click>=8.0,<9.0
  - requests~=2.28
  - flask          # no version constraint
```

#### Struct format

An explicit map with `name`, an optional `version`, and an optional `extras` list:

```yaml
packages:
  - name: numpy
    version: ">=1.24"
  - name: torch
    version: ">=2.0"
    extras: [cuda]
  - name: flask    # version omitted — any version accepted
```

#### Supported version operators

| Operator | Meaning |
|---|---|
| `==` | Exact version |
| `>=` | Greater than or equal |
| `<=` | Less than or equal |
| `!=` | Exclude version |
| `~=` | Compatible release (e.g. `~=2.28` means `>=2.28, ==2.*`) |
| `>` | Strictly greater than |
| `<` | Strictly less than |

Compound constraints are supported by separating clauses with a comma:
`>=1.24,<2.0`.

### Complete `envknit.yaml` Example

```yaml
envknit_version: "0.1.0"

environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28.0
      - click>=8.0,<9.0
    dev_packages:
      - pytest>=7.0
      - black>=23.0

  ml:
    python_version: "3.11"
    packages:
      - name: torch
        version: ">=2.0"
      - numpy>=1.24,<2.0

  frontend:
    node_version: "20.11"
    packages: []
```

---

## Global Configuration (`~/.envknit/config.yaml`)

### File Location

The global config is always read from `~/.envknit/config.yaml`. The file and
its parent directory are created automatically when EnvKnit writes global
settings. If the file does not exist, all fields revert to their built-in
defaults.

### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `default_backend` | `string` | None | Default install backend for environments that do not specify one. Accepted values: `"pip"`, `"uv"`. |
| `default_python_version` | `string` | None | Default Python version for new environments when not specified in `envknit.yaml`. |
| `store_dir` | `string` | `~/.envknit/packages/` | Override the directory where EnvKnit stores managed packages. Supports absolute paths. |
| `node_version_manager` | `string` | None (auto-detect) | Force a specific Node.js version manager. Accepted values: `"mise"`, `"fnm"`, `"nvm"`. When omitted, EnvKnit auto-detects the available manager. |
| `cache_ttl_secs` | `integer (u64)` | `300` | PyPI metadata cache TTL in seconds. Set to `0` to disable caching. |
| `parallel_jobs` | `integer (usize)` | `4` | Number of parallel pip workers used during `install`. |
| `subprocess_timeout_secs` | `integer (u64)` | `300` | Timeout in seconds for subprocess calls (`uv pip compile`, `pip install`). Set to `0` to disable the timeout. |

### Complete `~/.envknit/config.yaml` Example

```yaml
default_backend: pip
default_python_version: "3.11"
store_dir: /data/envknit/packages
node_version_manager: fnm
cache_ttl_secs: 600
parallel_jobs: 8
subprocess_timeout_secs: 300
```

---

## Precedence Rules

When the same setting can come from both files, project config wins over global
config:

1. **Project `envknit.yaml`** — highest precedence. Values set here are used as-is.
2. **Global `~/.envknit/config.yaml`** — provides user-level defaults. A field
   only takes effect when the corresponding project field is absent or not set.

Fields that exist only in the global config (`store_dir`, `cache_ttl_secs`,
`parallel_jobs`, `node_version_manager`, `subprocess_timeout_secs`) are not
overridable per-project and always come from the global config.
