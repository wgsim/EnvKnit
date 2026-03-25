# Lock File Reference (envknit.lock.yaml)

## Purpose

`envknit.lock.yaml` is the single source of truth for resolved dependency versions.
It captures exactly which version of each package was selected by the resolver, where
it is installed, and a SHA-256 checksum for integrity verification.

The file serves two consumers:

- **Rust CLI** (`envknit install`, `envknit run`, `envknit verify`): reads all fields.
- **Python library** (`envknit.configure_from_lock()`): reads the SHARED subset of fields
  to locate installed packages and route imports.

Commit `envknit.lock.yaml` to version control. Never hand-edit it.

---

## Schema Versioning

```yaml
schema_version: "1.0"
```

The `schema_version` field uses `MAJOR.MINOR` format. The CLI enforces a major-version
gate: if the lock file's major version is greater than the CLI's supported major version,
the CLI refuses to load it and prints an upgrade prompt.

Minor version bumps are backwards-compatible. The current supported version is `"1.0"`.

---

## File Structure

```yaml
schema_version: "1.0"
lock_generated_at: "2024-01-15T10:30:00Z"
resolver_version: "uv/0.10.7"           # or "envknit-builtin/0.1.2"
packages: []                          # legacy flat list (usually empty)
environments:
  default:
    - name: requests
      version: "2.31.0"
      install_path: ~/.envknit/packages/requests/2.31.0/
      backend: pip
      dependencies:
        - charset-normalizer>=2,<4
        - idna<4,>=2.5
        - urllib3<3,>=1.21.1
        - certifi>=2017.4.17
      sha256: "a1b2c3d4e5f6..."
    - name: pytest
      version: "7.4.3"
      install_path: ~/.envknit/packages/pytest/7.4.3/
      backend: pip
      dependencies:
        - iniconfig
        - packaging
        - pluggy<2,>=0.12
      dev: true
      sha256: "f6e5d4c3b2a1..."
  ml:
    - name: numpy
      version: "1.26.4"
      install_path: ~/.envknit/packages/numpy/1.26.4/
      backend: pip
      dependencies: []
      sha256: "deadbeef1234..."
```

---

## Top-Level Metadata Fields

| Field | Type | Description |
|---|---|---|
| `schema_version` | `string` | Always `"1.0"`. Used for compatibility gating. |
| `lock_generated_at` | `string \| null` | ISO 8601 timestamp of when `envknit lock` ran. Omitted if not set. |
| `resolver_version` | `string \| null` | Resolver that generated this lock file. Format: `"uv/<version>"` (e.g., `"uv/0.10.7"`) when uv is on PATH, or `"envknit-builtin/<version>"` (e.g., `"envknit-builtin/0.1.2"`) otherwise. Omitted if not set. |
| `packages` | `array` | Legacy flat package list. Present for backwards compatibility; typically empty when `environments` is populated. |
| `environments` | `object` | Map of environment name to list of `LockedPackage` entries. This is the primary data. |

---

## Environment Entries

`environments` is a `HashMap<string, LockedPackage[]>`. Each key is an environment name
(e.g., `"default"`, `"ml"`, `"frontend"`). The value is an ordered list of locked packages
for that environment, including both regular and dev dependencies.

When `envknit install --env ml` runs, only the `ml` environment's entries are processed.
When no `--env` flag is given, the `default` environment is used.

---

## LockedPackage Fields

| Field | Type | Set by | Description |
|---|---|---|---|
| `name` | `string` | `envknit lock` | Canonical package name (PyPI or npm name). |
| `version` | `string` | `envknit lock` | Exact resolved version (e.g., `"2.31.0"`). |
| `install_path` | `string \| null` | `envknit install` | Absolute path to `~/.envknit/packages/<name>/<version>/`. `null` before first install. |
| `backend` | `string \| null` | `envknit lock` | Install backend used (e.g., `"pip"`). Omitted if default. |
| `dependencies` | `string[]` | `envknit lock` | Resolved dependency specs for this package. Empty array if none. |
| `dev` | `bool` | `envknit lock` | `true` if this is a dev dependency. Omitted from YAML when `false`. |
| `sha256` | `string \| null` | `envknit install` | SHA-256 digest of the installed directory tree. `null` before first install. |

### Field serialization notes

- `install_path`, `backend`, and `sha256` are omitted from YAML when `null` (`skip_serializing_if = "Option::is_none"`).
- `dev` is omitted from YAML when `false` (`skip_serializing_if = "std::ops::Not::not"`).
- `dependencies` is omitted from YAML when empty (`skip_serializing_if = "Vec::is_empty"`).

---

## Field Classification: SHARED vs CLI-ONLY

The Python library (`envknit.configure_from_lock()`) reads only a subset of fields:

### SHARED fields (read by both CLI and Python library)

| Field | Purpose |
|---|---|
| `schema_version` | Version compatibility check (`SchemaVersionError` if unsupported) |
| `name` | Identifies the package for import routing |
| `version` | Used to route `envknit.use("requests", "2.31.0")` calls |
| `install_path` | Added to `PYTHONPATH` / `sys.path` for import resolution |
| `sha256` | Optional integrity check before loading |

### CLI-ONLY fields (ignored by Python library)

| Field | Purpose |
|---|---|
| `lock_generated_at` | Audit trail; shown in `envknit status` |
| `resolver_version` | Compatibility diagnostics |
| `backend` | Selects install backend during `envknit install` |
| `dependencies` | Used by resolver for backtracking; displayed by `envknit tree` |
| `dev` | Filtered by `envknit install --no-dev` |

---

## Complete Example

```yaml
schema_version: "1.0"
lock_generated_at: "2024-01-15T10:30:00Z"
resolver_version: "uv/0.10.7"
packages: []
environments:
  default:
    - name: requests
      version: "2.31.0"
      install_path: /home/alice/.envknit/packages/requests/2.31.0/
      backend: pip
      dependencies:
        - charset-normalizer>=2,<4
        - idna<4,>=2.5
        - urllib3<3,>=1.21.1
        - certifi>=2017.4.17
      sha256: "3b553c8f5af1b3d2a0ce7fb0bc8b10dc2bcbf16dd0cecea0f3c5c1bedc2d8e7a"
    - name: charset-normalizer
      version: "3.3.2"
      install_path: /home/alice/.envknit/packages/charset-normalizer/3.3.2/
      backend: pip
      dependencies: []
      sha256: "9a1e2f3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f"
    - name: pytest
      version: "7.4.3"
      install_path: /home/alice/.envknit/packages/pytest/7.4.3/
      backend: pip
      dependencies:
        - iniconfig
        - packaging
        - pluggy<2,>=0.12
      dev: true
      sha256: "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b"
  ml:
    - name: numpy
      version: "1.26.4"
      install_path: /home/alice/.envknit/packages/numpy/1.26.4/
      backend: pip
      dependencies: []
      sha256: "4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f"
```

---

## When to Commit / When to Regenerate

### Always commit `envknit.lock.yaml`

The lock file ensures every developer and CI environment installs identical package
versions. Without it, `envknit install` would re-resolve and may pick different versions.

```
git add envknit.lock.yaml
git commit -m "chore: update lock file"
```

### Regenerate after changing `envknit.yaml`

Any time you add, remove, or change a package spec in `envknit.yaml`, regenerate the
lock file:

```bash
envknit lock
```

Then commit both `envknit.yaml` and `envknit.lock.yaml` together.

### When `install_path` and `sha256` are null

Immediately after `envknit lock`, both `install_path` and `sha256` are `null` for newly
added packages. They are populated by `envknit install`. This is expected — committing a
lock file with null `install_path` values is correct. Each developer runs
`envknit install` locally to populate their own `~/.envknit/packages/` store.

The lock file on disk is not updated by `envknit install`; the store is written
separately. To verify that installed files match the committed checksums, run:

```bash
envknit verify
```

### Detecting divergence

`envknit check` exits with code 1 if `envknit.yaml` and `envknit.lock.yaml` are out of
sync. Run this in CI before installing.
