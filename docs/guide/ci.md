# CI Integration

## Key Commands for CI

| Command | Purpose | Exit code |
|---|---|---|
| `envknit check` | Verify `envknit.yaml` and `envknit.lock.yaml` are in sync | 1 if diverged |
| `envknit install --no-dev --auto-cleanup` | Install production dependencies, remove stale packages | 1 on failure |
| `envknit verify` | Verify SHA-256 checksums of installed packages match lock file | 1 if mismatch |
| `envknit diff base.lock.yaml head.lock.yaml` | Show changed packages between two lock files (PR review) | 0 always |
| `envknit export --format requirements --output requirements.txt` | Export for pip compatibility | 0 on success |

Run commands in this order: `check` → `install` → `verify` → run tests.

---

## GitHub Actions: Complete Workflow

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install EnvKnit CLI
        run: |
          curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o envknit
          chmod +x envknit
          sudo mv envknit /usr/local/bin/

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Cache package store
        uses: actions/cache@v4
        with:
          path: ~/.envknit/packages
          key: envknit-${{ hashFiles('envknit.lock.yaml') }}
          restore-keys: |
            envknit-

      - name: Verify lock file is in sync
        run: envknit check

      - name: Install dependencies
        run: envknit install --no-dev --auto-cleanup

      - name: Verify package integrity
        run: envknit verify

      - name: Run tests
        run: envknit run -- python -m pytest --tb=short -q
```

---

## Caching `~/.envknit/packages/`

The package store at `~/.envknit/packages/` is safe to cache between CI runs. Cache
invalidation should be keyed on `envknit.lock.yaml`:

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.envknit/packages
    key: envknit-${{ hashFiles('envknit.lock.yaml') }}
    restore-keys: |
      envknit-
```

When the lock file changes (new or updated dependencies), the cache key changes and the
store is rebuilt. The `restore-keys` fallback allows a partial cache hit, and
`envknit install` installs only the missing packages.

Use `--auto-cleanup` on install to remove packages that are in the store but no longer
referenced by the lock file. This keeps the cache from growing unbounded across many
lock file changes.

---

## GitLab CI (Brief)

```yaml
variables:
  ENVKNIT_CACHE_DIR: "$CI_PROJECT_DIR/.envknit-cache"

cache:
  key:
    files:
      - envknit.lock.yaml
  paths:
    - .envknit-cache/

before_script:
  - curl -L https://github.com/wgsim/EnvKnit/releases/latest/download/envknit-linux-amd64 -o /usr/local/bin/envknit
  - chmod +x /usr/local/bin/envknit

test:
  script:
    - envknit check
    - ENVKNIT_STORE_DIR="$ENVKNIT_CACHE_DIR" envknit install --no-dev --auto-cleanup
    - ENVKNIT_STORE_DIR="$ENVKNIT_CACHE_DIR" envknit verify
    - ENVKNIT_STORE_DIR="$ENVKNIT_CACHE_DIR" envknit run -- python -m pytest
```

Note: `ENVKNIT_STORE_DIR` overrides the default `~/.envknit/packages/` to a
project-local directory that GitLab CI can cache. Check the CLI reference for
environment variable support.

---

## Tips

### Always commit `envknit.lock.yaml`

The lock file is what makes CI deterministic. Without it, `envknit install` would
re-resolve from `envknit.yaml` and may select different versions depending on what
is available on PyPI at the time of the run.

Add to your `.gitignore` if needed, but never ignore `envknit.lock.yaml`:

```gitignore
# DO NOT add envknit.lock.yaml here
*.pyc
__pycache__/
.envknit-local/
```

### Use `--no-dev` for production installs

Dev dependencies (marked `dev: true` in the lock file) are for local development and
testing. Skip them in production builds:

```bash
envknit install --no-dev --auto-cleanup
```

For test jobs that need dev dependencies, omit `--no-dev`:

```yaml
- name: Install all dependencies (with dev)
  run: envknit install --auto-cleanup
```

### Cache key strategy

| Strategy | Key | Trade-off |
|---|---|---|
| Exact lock match | `hashFiles('envknit.lock.yaml')` | Perfect isolation, frequent misses |
| Prefix fallback | `envknit-` restore-key | Warm cache on partial lock changes |
| OS-specific | `envknit-linux-${{ hashFiles(...) }}` | Required for C extensions with platform-specific builds |

### Running `envknit diff` on PRs

Add a step to show dependency changes in pull requests:

```yaml
- name: Show dependency changes
  if: github.event_name == 'pull_request'
  run: |
    git fetch origin ${{ github.base_ref }}
    git show origin/${{ github.base_ref }}:envknit.lock.yaml > /tmp/base.lock.yaml || true
    envknit diff /tmp/base.lock.yaml envknit.lock.yaml || true
```

This prints which packages were added, removed, or updated between the base branch and
the PR, making dependency changes visible in CI output.

### Integrity verification

`envknit verify` checks that the SHA-256 digest of each installed package directory
matches the value in `envknit.lock.yaml`. Run it after `envknit install` to detect:

- Corrupted cache entries.
- Packages modified after installation.
- Cache poisoning (in shared CI environments).

If `envknit verify` fails, delete the cache and force a fresh install:

```bash
rm -rf ~/.envknit/packages/
envknit install --no-dev
```
