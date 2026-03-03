# Node.js v3.0 Design — Node.js Version Management

**Date:** 2026-03-03
**Status:** Approved
**Scope:** Node.js runtime version resolution (not npm package management)

---

## Problem Statement

EnvKnit v2.0 supports Python version management via `python_version:` in `envknit.yaml`,
resolving through mise → pyenv → system. Projects using both Python and Node.js have no
equivalent mechanism for Node.js version pinning.

## Decision: Version Management Only (not npm shim)

npm/yarn/pnpm already provide excellent lock files (`package-lock.json`, `yarn.lock`,
`pnpm-lock.yaml`). Reimplementing npm resolution would require handling nested
`dependencies`/`peerDependencies`, a fundamentally different model from PyPI's flat JSON API.

**Goal:** Mirror the `python_version` pattern for Node.js — declare a required version in
`envknit.yaml`, and EnvKnit resolves and injects the correct Node.js binary at runtime.

---

## Architecture

### New File: `node_resolver.rs`

Mirrors `python_resolver.rs`. Resolution chain (configurable):

```
mise → fnm → nvm → system
```

Key functions:
- `resolve_node(version_spec: &str) -> Result<PathBuf>` — returns path to matching `node` binary
- `node_bin_dir(node_binary: &PathBuf) -> PathBuf` — returns the bin directory containing node/npm/npx
- `version_matches(installed: &str, spec: &str) -> bool` — reused from python_resolver pattern

User override via `~/.envknit/config.yaml`:
```yaml
node_version_manager: fnm   # forces a specific tool; skips chain
```

### Config Schema Change: `config.rs`

Add `node_version: Option<String>` to `EnvironmentConfig`:

```yaml
environments:
  frontend:
    node_version: "20.11"
    packages: []
```

### Global Config Change: `global_config.rs`

Add `node_version_manager: Option<String>` field.

---

## Command Integration

### `envknit run`
On success: prepend `node_bin_dir` to `PATH` so that `node`, `npm`, `npx` all use the
pinned version.

On failure: print explicit stderr warning, fall back to system:
```
⚠ node_version "20.11" could not be resolved (fnm/nvm/mise not found)
  Falling back to system node: v18.19.0
  Install fnm or mise to enforce version isolation.
```

### `envknit install`
Same warning pattern on resolve failure. Does not block installation.

### `envknit doctor`
Per-environment node_version check:
- Success: `✓ node_version [frontend] 20.11 → /home/user/.local/share/mise/installs/node/20.11.0/bin`
- Failure: `! node_version [frontend] 20.11 not found — install fnm or mise` (Warn, exit 0)

### `envknit check`
- node_version unresolvable: `! node_version [frontend] unresolvable` (Warn, exit 0, not Fail)

---

## Resolver Chain Detail

```
mise version node@<spec>    → ~/.local/share/mise/installs/node/<version>/bin/node
fnm exec --using=<version>  → ~/.local/share/fnm/node-versions/<version>/installation/bin/node
nvm which <version>         → ~/.nvm/versions/node/v<version>/bin/node
system                      → which node (warn if version mismatch)
```

`version_matches` uses prefix matching: spec `"20"` matches installed `"20.11.0"`,
spec `"20.11"` matches `"20.11.0"`, spec `"20.11.1"` requires exact match.

---

## Fallback & Warning Policy

| Layer | resolve success | resolve failure |
|-------|----------------|-----------------|
| `doctor` | `✓` green | `!` yellow Warn, exit 0 |
| `check` | pass | `!` Warn, exit 0 |
| `envknit run` | PATH prepend | stderr warning + system fallback |
| `envknit install` | node version noted | stderr warning + continue |

**Python resolver alignment:** `python_resolver.rs` fallback paths will be updated with the
same explicit stderr warning pattern for consistency.

---

## Files to Create / Modify

| File | Change |
|------|--------|
| `src/node_resolver.rs` | New — resolution chain + version matching |
| `src/config.rs` | Add `node_version: Option<String>` to `EnvironmentConfig` |
| `src/global_config.rs` | Add `node_version_manager: Option<String>` |
| `src/lib.rs` | Add `pub mod node_resolver` |
| `src/commands/run.rs` | Inject `node_bin_dir` into PATH |
| `src/commands/install.rs` | Warn on node_version resolve failure |
| `src/commands/doctor.rs` | Per-env node_version check |
| `src/commands/check.rs` | node_version Warn item |
| `src/python_resolver.rs` | Add explicit stderr warning on fallback |

---

## Out of Scope

- npm/yarn/pnpm package resolution (managed by those tools' own lock files)
- Deno or Bun support (separate milestone if needed)
- Auto-installing Node.js versions (requires `mise install node@<ver>` — user responsibility)
