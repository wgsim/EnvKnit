# v0.2.0: uv Required Dependency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the built-in fallback resolver and declare `uv` as a required dependency for `envknit lock`.

**Architecture:** Single Big Bang PR — add `require_uv()` to `uv_resolver.rs`, simplify `lock.rs` to remove the `if use_uv` branch, delete `resolver.rs` + `reqwest`, add uv check to `doctor.rs`, update CI. Tasks are ordered so the build remains green after each commit.

**Tech Stack:** Rust, `semver` crate (already in `Cargo.toml`), `astral-sh/setup-uv` GitHub Action.

**Spec:** `docs/superpowers/specs/2026-03-25-uv-required-dependency-design.md`

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `crates/envknit-cli/src/uv_resolver.rs` | Modify | Add `MIN_UV_VERSION`, `require_uv()`, `version_lt()` + tests |
| `crates/envknit-cli/src/commands/lock.rs` | Modify | Remove `uv_available`/`use_uv`, call `require_uv()`, hoist locals, simplify `resolver_version` |
| `crates/envknit-cli/src/resolver.rs` | Delete | Entire file removed |
| `crates/envknit-cli/src/lib.rs` | Modify | Remove `pub mod resolver;` |
| `crates/envknit-cli/Cargo.toml` | Modify | Remove `reqwest` dependency + TODO comment; bump version to `0.2.0` |
| `crates/envknit-cli/src/commands/doctor.rs` | Modify | Add `use crate::uv_resolver;` + uv check block |
| `.github/workflows/test.yml` | Modify | Add uv install step + `envknit lock` integration test |

---

## Task 1: Add `require_uv()` and `version_lt()` to `uv_resolver.rs`

**Files:**
- Modify: `crates/envknit-cli/src/uv_resolver.rs`

### Context

`uv_resolver.rs` currently has `find_uv()` and `uv_version()`. We add:
- `MIN_UV_VERSION: &str = "0.10.7"` — public constant
- `version_lt(a, b)` — pure function using the `semver` crate
- `require_uv()` — calls `find_uv()`, bails if absent, warns if below minimum

The `semver` crate is already in `Cargo.toml` (line 26). No new dependencies needed.

---

- [ ] **Step 1: Write the failing tests**

Append inside the existing `#[cfg(test)]` block at the bottom of `crates/envknit-cli/src/uv_resolver.rs`:

```rust
    #[test]
    fn version_lt_basic_comparison() {
        assert!(version_lt("0.4.0", "0.10.7"));
        assert!(version_lt("0.10.6", "0.10.7"));
        assert!(!version_lt("0.10.7", "0.10.7"));
        assert!(!version_lt("0.11.0", "0.10.7"));
        assert!(!version_lt("1.0.0", "0.10.7"));
    }

    #[test]
    fn version_lt_unparseable_returns_false() {
        assert!(!version_lt("unknown", "0.10.7"));
        assert!(!version_lt("0.10.7", "unknown"));
    }

    #[test]
    fn require_uv_succeeds_when_uv_present() {
        // This test requires uv to be on PATH (CI installs it; local dev assumed).
        // If uv is missing this test is skipped via the Result check.
        if find_uv().is_none() {
            return; // skip — uv not available in this environment
        }
        assert!(require_uv().is_ok());
    }
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd crates/envknit-cli
cargo test version_lt 2>&1 | tail -20
```

Expected: `error[E0425]: cannot find function 'version_lt'`

- [ ] **Step 3: Implement `MIN_UV_VERSION`, `version_lt()`, `require_uv()`**

Add after the existing `use` imports at the top of `crates/envknit-cli/src/uv_resolver.rs` — insert `use colored::Colorize;` if not already present:

```rust
use colored::Colorize;
```

Then add the following three items anywhere before the `#[cfg(test)]` block (e.g., after `uv_version()`):

```rust
pub const MIN_UV_VERSION: &str = "0.10.7";

/// Returns true if semver string `a` is strictly less than `b`.
/// Uses the `semver` crate for correct comparison. Returns false if either
/// string is unparseable (so we don't warn on unusual version formats).
pub fn version_lt(a: &str, b: &str) -> bool {
    use semver::Version;
    match (Version::parse(a), Version::parse(b)) {
        (Ok(va), Ok(vb)) => va < vb,
        _ => false,
    }
}

/// Checks that uv is present and meets the minimum tested version.
///
/// - uv absent         → bail! (hard error, exits non-zero)
/// - uv < MIN_UV_VERSION → print ⚠ warning, return Ok(()) (continues)
/// - uv ≥ MIN_UV_VERSION → return Ok(()) silently
pub fn require_uv() -> Result<()> {
    match find_uv() {
        None => {
            bail!(
                "uv is required but not found on PATH.\n\
                 Install: https://astral.sh/uv\n\
                 Run `envknit doctor` for system diagnostics."
            );
        }
        Some(_) => {
            let ver = uv_version();
            if version_lt(&ver, MIN_UV_VERSION) {
                eprintln!(
                    "{} uv {} detected (envknit tested with {}+). \
                     Consider upgrading: https://astral.sh/uv",
                    "⚠".yellow(),
                    ver,
                    MIN_UV_VERSION
                );
            }
            Ok(())
        }
    }
}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd crates/envknit-cli
cargo test version_lt require_uv 2>&1 | tail -20
```

Expected: `test result: ok. 3 passed`

- [ ] **Step 5: Confirm the whole crate still compiles**

```bash
cargo build --manifest-path crates/envknit-cli/Cargo.toml 2>&1 | tail -10
```

Expected: `Finished` with no errors. Warnings about unused code in `resolver.rs` are fine at this stage.

- [ ] **Step 6: Commit**

```bash
git add crates/envknit-cli/src/uv_resolver.rs
git commit -m "feat(uv-resolver): add require_uv(), version_lt(), MIN_UV_VERSION"
```

---

## Task 2: Simplify `lock.rs` — remove fallback branch

**Files:**
- Modify: `crates/envknit-cli/src/commands/lock.rs`

### Context

`lock.rs` currently has:
- Lines 4: `use crate::resolver::Resolver;`
- Lines 33–38: `uv_available` / `use_uv` variables + warning eprintln
- Lines 81–107: `if use_uv { ... } else { ... }` branch
- Lines 143–147: `resolver_version` conditional using `use_uv`

All four sections are replaced as described below. After this task `resolver.rs` is still present (so the build stays green), but it is no longer called.

---

- [ ] **Step 1: Remove the `use crate::resolver::Resolver` import (line 4)**

Delete this line from `lock.rs`:
```rust
use crate::resolver::Resolver;
```

- [ ] **Step 2: Replace the uv detection block (lines 33–38) with `require_uv()`**

Current code (lines 33–38 of `lock.rs`):
```rust
    let uv_available = uv_resolver::find_uv().is_some();
    let use_uv = uv_available;

    if !uv_available {
        eprintln!("{} uv not found on PATH — falling back to built-in resolver", "⚠".yellow());
    }
```

Replace with:
```rust
    uv_resolver::require_uv()?;
```

- [ ] **Step 3: Replace the `if use_uv { ... } else { ... }` block (lines 81–107)**

Current code block (inside the `for (env_name, env_config)` loop):
```rust
        let (mut resolved, mut dev_resolved) = if use_uv {
            let prod_strings: Vec<String> = specs.iter().map(|s| s.to_uv_spec()).collect();
            let dev_strings: Vec<String> = dev_specs.iter().map(|s| s.to_uv_spec()).collect();
            let python_version = env_config.python_version.as_deref();
            let (prod, dev) = uv_resolver::resolve(&prod_strings, &dev_strings, python_version, timeout)?;
            (prod, dev)
        } else {
            let resolver = Resolver::new(dry_run);

            let resolved = if !specs.is_empty() {
                resolver.resolve(&specs)?
            } else {
                vec![]
            };

            let dev_resolved = if !dev_specs.is_empty() {
                let mut dr = resolver.resolve(&dev_specs)?;
                for pkg in &mut dr {
                    pkg.dev = true;
                }
                dr
            } else {
                vec![]
            };

            (resolved, dev_resolved)
        };
```

Replace with (locals hoisted out of the former branch):
```rust
        let prod_strings: Vec<String> = specs.iter().map(|s| s.to_uv_spec()).collect();
        let dev_strings: Vec<String> = dev_specs.iter().map(|s| s.to_uv_spec()).collect();
        let python_version = env_config.python_version.as_deref();
        let (mut resolved, mut dev_resolved) =
            uv_resolver::resolve(&prod_strings, &dev_strings, python_version, timeout)?;
```

- [ ] **Step 4: Simplify the `resolver_version` assignment**

Current code (near end of `run()`, after the env loop):
```rust
    lock.resolver_version = Some(if use_uv {
        format!("uv/{}", uv_resolver::uv_version())
    } else {
        format!("envknit-builtin/{}", env!("CARGO_PKG_VERSION"))
    });
```

Replace with:
```rust
    lock.resolver_version = Some(format!("uv/{}", uv_resolver::uv_version()));
```

- [ ] **Step 5: Verify the build**

```bash
cargo build --manifest-path crates/envknit-cli/Cargo.toml 2>&1 | tail -10
```

Expected: `Finished` with no errors. Dead code warnings for `resolver.rs` are expected and will be resolved in the next task.

- [ ] **Step 6: Commit**

```bash
git add crates/envknit-cli/src/commands/lock.rs
git commit -m "refactor(lock): remove built-in resolver fallback, require uv"
```

---

## Task 3: Delete `resolver.rs`, remove `reqwest`, bump version

**Files:**
- Delete: `crates/envknit-cli/src/resolver.rs`
- Modify: `crates/envknit-cli/src/lib.rs` (remove `pub mod resolver;`)
- Modify: `crates/envknit-cli/Cargo.toml` (remove `reqwest`, bump version)

### Context

Now that `lock.rs` no longer calls `Resolver`, `resolver.rs` is dead code. We delete the file, unregister the module from `lib.rs`, and remove the `reqwest` dependency that `resolver.rs` was the sole user of. We also bump the crate version to `0.2.0`.

---

- [ ] **Step 1: Delete `resolver.rs`**

```bash
/opt/homebrew/opt/trash/bin/trash crates/envknit-cli/src/resolver.rs
```

- [ ] **Step 2: Remove `pub mod resolver;` from `lib.rs`**

In `crates/envknit-cli/src/lib.rs`, delete the line:
```rust
pub mod resolver;
```

- [ ] **Step 3: Remove `reqwest` from `Cargo.toml`**

In `crates/envknit-cli/Cargo.toml`, delete these two lines (lines 27–29):
```toml
# TODO: reqwest is only used by the fallback built-in resolver (resolver.rs).
# Remove when/if resolver.rs is deleted in a future cleanup pass.
reqwest = { version = "0.12", features = ["blocking", "json", "rustls-tls"], default-features = false }
```

- [ ] **Step 4: Bump version to `0.2.0`**

In `crates/envknit-cli/Cargo.toml`, change:
```toml
version = "0.1.2"
```
To:
```toml
version = "0.2.0"
```

- [ ] **Step 5: Verify the build with no warnings**

```bash
cargo build --manifest-path crates/envknit-cli/Cargo.toml 2>&1 | tail -10
```

Expected: `Finished` with zero errors and zero `dead_code` warnings related to `resolver`.

- [ ] **Step 6: Run all Rust tests**

```bash
cargo test --manifest-path crates/envknit-cli/Cargo.toml 2>&1 | tail -20
```

Expected: All existing tests pass. The tests in `uv_resolver.rs` added in Task 1 should be included.

- [ ] **Step 7: Commit**

```bash
git add crates/envknit-cli/src/lib.rs crates/envknit-cli/Cargo.toml
git rm crates/envknit-cli/src/resolver.rs
git commit -m "chore: delete resolver.rs, remove reqwest, bump version to 0.2.0"
```

---

## Task 4: Add uv check to `doctor.rs`

**Files:**
- Modify: `crates/envknit-cli/src/commands/doctor.rs`

### Context

`doctor.rs` has a list of `Check` items rendered as `✓ / ! / ✗`. Currently it checks pip, python, pyenv, mise, directories, config, lockfile, PYTHONPATH, python_version, node_version, and global config. We add a uv check right after the `pip` block (line ~80), because uv is now required (unlike pip which is optional).

---

- [ ] **Step 1: Add `use crate::uv_resolver;` to imports**

In `crates/envknit-cli/src/commands/doctor.rs`, the existing imports end at line 9. Add:
```rust
use crate::uv_resolver;
```

- [ ] **Step 2: Insert the uv check block after the `pip` check block**

The `pip` check block ends around line 80 with `},`. Insert immediately after it:

```rust
    // --- uv (required) ---
    match uv_resolver::find_uv() {
        None => {
            checks.push(Check::fail(
                "uv",
                "not found — required for `envknit lock`. Install: https://astral.sh/uv",
            ));
        }
        Some(_) => {
            let ver = uv_resolver::uv_version();
            if uv_resolver::version_lt(&ver, uv_resolver::MIN_UV_VERSION) {
                checks.push(Check::warn(
                    "uv",
                    format!(
                        "{} — below minimum tested version {}. Upgrade: https://astral.sh/uv",
                        ver,
                        uv_resolver::MIN_UV_VERSION
                    ),
                ));
            } else {
                checks.push(Check::ok("uv", ver));
            }
        }
    }
```

- [ ] **Step 3: Verify the build**

```bash
cargo build --manifest-path crates/envknit-cli/Cargo.toml 2>&1 | tail -10
```

Expected: `Finished` with no errors.

- [ ] **Step 4: Manually verify `envknit doctor` output**

```bash
./target/debug/envknit doctor 2>&1 | grep uv
```

Expected output (with uv 0.10.7 installed):
```
  ✓ uv             0.10.7
```

- [ ] **Step 5: Commit**

```bash
git add crates/envknit-cli/src/commands/doctor.rs
git commit -m "feat(doctor): add uv check — Fail if absent, Warn if below 0.10.7"
```

---

## Task 5: Update CI — add uv install + integration test

**Files:**
- Modify: `.github/workflows/test.yml`

### Context

The current `test.yml` (7 steps) runs Python tests only. We add:
1. `astral-sh/setup-uv@v5` before "Install dependencies"
2. A Rust build + `envknit lock` integration test (Python 3.11 only, to avoid quadrupling CI time)

The integration test creates a minimal `envknit.yaml`, runs `envknit lock`, and asserts the lock file contains `resolver_version: uv/...`.

---

- [ ] **Step 1: Add the uv install step**

In `.github/workflows/test.yml`, insert after `- uses: actions/setup-python@v5 ...` and before `- name: Install dependencies`:

```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@v5
```

- [ ] **Step 2: Add Rust build + integration test steps**

Append after `- name: Run tests` (keep the existing `Run tests` step unchanged):

```yaml
      - name: Build envknit CLI
        if: matrix.python-version == '3.11'
        run: cargo build --manifest-path crates/envknit-cli/Cargo.toml

      - name: Integration test — envknit lock with uv
        if: matrix.python-version == '3.11'
        run: |
          mkdir -p /tmp/lock-test && cd /tmp/lock-test
          cat > envknit.yaml <<'EOF'
environments:
  default:
    packages:
      - requests>=2.28
EOF
          $GITHUB_WORKSPACE/target/debug/envknit lock
          grep 'resolver_version:.*uv/' envknit.lock.yaml
```

- [ ] **Step 3: Verify the final YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))" && echo "YAML valid"
```

Expected: `YAML valid`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add uv install step and envknit lock integration test"
```

---

## Final: Verify end-to-end

- [ ] **Run the full Rust test suite one more time**

```bash
cargo test --manifest-path crates/envknit-cli/Cargo.toml 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Run Python tests**

```bash
pytest --tb=short -q
```

Expected: All tests pass (Python library is unaffected by this change).

- [ ] **Smoke test: `envknit lock` with uv present**

```bash
cd /tmp && mkdir -p smoke-test && cd smoke-test
cat > envknit.yaml <<'EOF'
environments:
  default:
    packages:
      - requests>=2.28
EOF
/path/to/target/debug/envknit lock
cat envknit.lock.yaml | grep resolver_version
```

Expected: `resolver_version: uv/0.10.7` (or whatever uv version is installed)

- [ ] **Smoke test: `envknit doctor` shows uv as ✓**

```bash
/path/to/target/debug/envknit doctor | grep uv
```

Expected: `✓ uv             0.10.7`
