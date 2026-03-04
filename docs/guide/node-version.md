# Node.js Version Management

## Setting `node_version`

Set `node_version` in `envknit.yaml` per environment:

```yaml
environments:
  frontend:
    node_version: "20.11"
    packages: []
  legacy-fe:
    node_version: "18"
    packages: []
```

When `node_version` is set, `envknit run` resolves the matching Node.js binary and
prepends its `bin/` directory to `PATH`. This makes `node`, `npm`, and `npx` resolve
to the pinned version for the duration of the command.

If `node_version` is omitted, the system `node` (whatever is on `PATH`) is used.

---

## Resolution Chain

EnvKnit resolves Node.js in this order:

1. **mise** (if installed)
2. **fnm** (filesystem check)
3. **nvm** (filesystem check)
4. **System Node** (fallback — prints a warning)

The chain is short-circuited if `node_version_manager` is set in global config (see
[Overriding the Chain](#overriding-the-chain)).

### 1. mise

EnvKnit checks whether `mise` is available, then lists installed Node.js versions:

```
mise ls --installed node
```

It finds the highest installed version that matches the spec, then resolves the binary
path via:

```
mise exec node@<matched_version> -- which node
```

### 2. fnm

EnvKnit does not shell out to `fnm` (it is a shell function). Instead, it scans the
filesystem directly.

It checks these directories in order:

1. `$FNM_DIR/node-versions/` (if `FNM_DIR` is set)
2. `$XDG_DATA_HOME/fnm/node-versions/` (if `XDG_DATA_HOME` is set)
3. `~/.local/share/fnm/node-versions/` (default)
4. `~/.fnm/node-versions/` (legacy path, only when `FNM_DIR` is not set)

Within each directory, it finds all installed version entries (e.g., `v20.11.0`),
strips the leading `v`, matches against the spec, and picks the highest match.

The node binary path is:

```
<fnm_base>/node-versions/<version>/installation/bin/node
```

### 3. nvm

EnvKnit does not shell out to `nvm` (it is a shell function). Instead, it scans:

1. `$NVM_DIR/versions/node/` (if `NVM_DIR` is set)
2. `~/.nvm/versions/node/` (default)

Version entries are named `v20.11.0`. EnvKnit strips the `v` prefix, matches against
the spec, and picks the highest match.

The node binary path is:

```
<nvm_root>/versions/node/<version>/bin/node
```

### 4. System Node (Fallback)

If none of the above methods find a match, EnvKnit calls `node --version` and checks
if the system version satisfies the spec. If it does, it uses it and prints a warning:

```
⚠ node_version '20.11' could not be resolved: No Node.js 20.11 found via mise, fnm, nvm, or system PATH.
  Falling back to system node: v18.19.0
  Install fnm or mise to enforce version isolation.
```

If no node binary is found at all, `envknit run` and `envknit install` exit with an error.

---

## Overriding the Chain

Set `node_version_manager` in `~/.config/envknit/config.yaml` to pin a specific
version manager and skip auto-detection:

```yaml
node_version_manager: "fnm"   # one of: mise, fnm, nvm
```

With this set, EnvKnit only tries the specified manager. If the requested version is
not found there, it exits with an error (no fallback chain):

```
node 20.11 not found via fnm. Run: fnm install 20.11
```

This is useful in environments where multiple version managers are installed and you
want deterministic behavior.

---

## Version Spec Formats

| Spec | Match behavior | Example match |
|---|---|---|
| `"20"` | Prefix match: matches any 20.x.y | 20.0.0, 20.11.0 |
| `"20.11"` | Prefix match: matches any 20.11.x | 20.11.0, 20.11.1 |
| `"20.11.0"` | Exact prefix match | 20.11.0 |
| `">=18"` | Operator: matches 18 and above | 18.19.0, 20.11.0 |
| `"==20.11.0"` | Operator: exact match | 20.11.0 |
| `">18"` | Operator: strictly greater than 18 | 18.1.0, 20.0.0 |
| `"<21"` | Operator: strictly less than 21 | 20.11.0, 18.0.0 |

When multiple installed versions match, EnvKnit selects the **highest** matching version.

---

## How It Works at Runtime

When `envknit run` launches a command, it resolves the node binary, finds its parent
directory (the `bin/` dir), and prepends it to `PATH`:

```
PATH = /home/user/.local/share/fnm/node-versions/v20.11.0/installation/bin:$PATH
```

Because `node`, `npm`, and `npx` all live in the same `bin/` directory, they all
resolve to the pinned version:

```bash
envknit run -- node --version    # prints v20.11.0
envknit run -- npm --version     # prints npm version bundled with 20.11.0
envknit run -- npx vite build    # uses vite from local node_modules
```

Unlike Python packages, Node.js tools installed in `node_modules/` via `npm install`
are accessed through `npx` or `node_modules/.bin/`, not via EnvKnit's package store.
EnvKnit only manages the Node.js runtime version; npm and your project's
`node_modules/` manage Node.js packages.

---

## Version Manager Directory Structures

### fnm

```
~/.local/share/fnm/
  node-versions/
    v18.19.0/
      installation/
        bin/
          node
          npm
          npx
    v20.11.0/
      installation/
        bin/
          node
          npm
          npx
```

### nvm

```
~/.nvm/
  versions/
    node/
      v18.19.0/
        bin/
          node
          npm
          npx
      v20.11.0/
        bin/
          node
          npm
          npx
```

### mise

mise manages installations in its own data directory and exposes them via the
`mise exec` shim mechanism. The directory structure is internal to mise and should
not be relied upon directly.

---

## Diagnosing with `envknit doctor`

```bash
envknit doctor
```

Example output when fnm is the active manager:

```
Checking Node.js version management...
  ✓ fnm is available (filesystem check)
  ✓ Node 20.11.0 found at ~/.local/share/fnm/node-versions/v20.11.0/installation/bin/node
  ✓ Node 18.19.0 found at ~/.local/share/fnm/node-versions/v18.19.0/installation/bin/node

Checking project config...
  node_version: "20.11" (environment: frontend)
  Resolved to: ~/.local/share/fnm/node-versions/v20.11.0/installation/bin/node
```

If no version manager is found:

```
Checking Node.js version management...
  - mise not found
  - fnm: no versions directory found
  - nvm: ~/.nvm not found
  ! System node: v18.19.0 (version isolation not enforced)
    To enforce version isolation, install fnm or mise.
```

---

## Installing Node.js Versions

### fnm

```bash
fnm install 20.11
fnm install 18
fnm use 20.11
```

### mise

```bash
mise install node@20.11
mise install node@18
mise use node@20.11    # set as local default
```

### nvm

```bash
nvm install 20.11
nvm install 18
nvm use 20.11
```

After installing a new Node.js version, verify EnvKnit finds it:

```bash
envknit doctor
```
