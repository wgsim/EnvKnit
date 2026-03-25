# v0.2.0 Design: uv as Required Dependency

**Status:** Approved
**Date:** 2026-03-25
**Scope:** `crates/envknit-cli` only — no Python library changes

---

## Goal

Declare `uv` as a required runtime dependency for `envknit lock`. Remove the built-in
fallback resolver (`resolver.rs`) and its `reqwest` HTTP dependency entirely.

---

## Background

`envknit lock` currently delegates to `uv pip compile` when `uv` is on PATH, falling
back to a 611-line built-in resolver (`resolver.rs`) backed by `reqwest` (TLS/HTTP)
when uv is absent. As of v0.1.2, uv is the production path — the fallback is untested
in CI and adds ~reqwest to the binary. v0.2.0 formalises uv as required and removes
the dead code.

---

## Decisions

| # | Decision |
|---|----------|
| Q1 | uv < `0.10.7` → warning only (not error); continue execution |
| Q2 | uv absent → hard error + `envknit doctor` referral |
| Q3 | `resolver.rs` + `reqwest` dependency deleted entirely |
| Q4 | Minimum tested version: `0.10.7` |
| Q5 | CI: add uv install + `envknit lock` integration test |
| Q6 | `doctor.rs`: add uv check item (Fail if absent, Warn if below minimum) |

---

## Implementation Approach

**Big Bang (single PR).** All changes land together:
- Delete `resolver.rs`
- Remove `reqwest` from `Cargo.toml`
- Simplify `lock.rs`
- Add `require_uv()` to `uv_resolver.rs`
- Extend `doctor.rs`
- Update `test.yml`

No deprecation period. v0.2.0 is a minor version bump with an explicit breaking change.

---

## Section 1: Deletions

### `resolver.rs`

Delete `crates/envknit-cli/src/resolver.rs` in full.

Remove from `crates/envknit-cli/src/lib.rs`:
```rust
pub mod resolver;
```

Remove from `crates/envknit-cli/src/commands/lock.rs`:
```rust
use crate::resolver::Resolver;
```

### `reqwest` from `Cargo.toml`

```toml
# crates/envknit-cli/Cargo.toml — remove these lines:
reqwest = { version = "...", features = ["blocking", "rustls-tls"], ... }
```

---

## Section 2: `lock.rs` Simplification

### Before (current)

```rust
let uv_available = uv_resolver::find_uv().is_some();
let use_uv = uv_available;

if !uv_available {
    eprintln!("{} uv not found on PATH — falling back to built-in resolver", "⚠".yellow());
}
// ...
let (mut resolved, mut dev_resolved) = if use_uv {
    uv_resolver::resolve(...)
} else {
    let resolver = Resolver::new(dry_run);
    // ... built-in path
};
```

### After

```rust
uv_resolver::require_uv()?;
// ...
// Replace the entire if use_uv { ... } else { ... } block (lock.rs lines 81–107)
// with the following. The three locals are hoisted out of the former branch:
let prod_strings: Vec<String> = specs.iter().map(|s| s.to_uv_spec()).collect();
let dev_strings: Vec<String> = dev_specs.iter().map(|s| s.to_uv_spec()).collect();
let python_version = env_config.python_version.as_deref();
let (mut resolved, mut dev_resolved) =
    uv_resolver::resolve(&prod_strings, &dev_strings, python_version, timeout)?;
```

Also simplify the `resolver_version` assignment (currently references `use_uv`):

```rust
// Before:
lock.resolver_version = Some(if use_uv {
    format!("uv/{}", uv_resolver::uv_version())
} else {
    format!("envknit-builtin/{}", env!("CARGO_PKG_VERSION"))
});

// After:
lock.resolver_version = Some(format!("uv/{}", uv_resolver::uv_version()));
```

The `if use_uv { ... } else { ... }` branch, `use_uv` variable, `uv_available` variable,
and all `Resolver` references are removed.

---

## Section 3: `uv_resolver.rs` — Version Check

### New public constant and function

```rust
pub const MIN_UV_VERSION: &str = "0.10.7";

/// Checks that uv is present and meets the minimum version.
/// - uv absent  → bail! (hard error)
/// - uv present but < MIN_UV_VERSION → print warning, return Ok(())
/// - uv present and >= MIN_UV_VERSION → return Ok(())
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

/// Returns true if semver string `a` is strictly less than `b`.
/// Uses the `semver` crate (already a dependency) for correct pre-release handling.
pub fn version_lt(a: &str, b: &str) -> bool {
    use semver::Version;
    match (Version::parse(a), Version::parse(b)) {
        (Ok(va), Ok(vb)) => va < vb,
        _ => false, // unparseable versions: don't warn
    }
}
```

### Behaviour table

| Condition | Output | Exit |
|-----------|--------|------|
| uv not found | `error: uv is required...` | non-zero |
| uv < 0.10.7 | `⚠ uv X.Y.Z detected...` | continues |
| uv ≥ 0.10.7 | (silent) | continues |

---

## Section 4: `doctor.rs` — uv Check

Add to `doctor.rs` imports:
```rust
use crate::uv_resolver;
```

Insert after the `pip` check block (uv is required, pip is not — ordering reflects priority):

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

**Display examples:**

```
✓ uv             0.10.7
! uv             0.4.1 — below minimum tested version 0.10.7. Upgrade: https://astral.sh/uv
✗ uv             not found — required for `envknit lock`. Install: https://astral.sh/uv
```

---

## Section 5: CI — `.github/workflows/test.yml`

### Add uv installation step (before "Install dependencies")

```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@v5
```

### Add integration test step (Python 3.11 only)

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

The `grep` assertion verifies that the lock file records a `uv/x.y.z` resolver version,
confirming that uv was actually used.

---

## Files Changed

| File | Action |
|------|--------|
| `crates/envknit-cli/src/resolver.rs` | Delete |
| `crates/envknit-cli/Cargo.toml` | Remove `reqwest` dependency |
| `crates/envknit-cli/src/commands/lock.rs` | Remove fallback branch, call `require_uv()` |
| `crates/envknit-cli/src/uv_resolver.rs` | Add `require_uv()`, `version_lt()`, `MIN_UV_VERSION` |
| `crates/envknit-cli/src/commands/doctor.rs` | Add uv check block |
| `.github/workflows/test.yml` | Add uv install step + integration test |

---

## Out of Scope

- `resolver.rs` unit tests (deleted with the file)
- Windows CI (separate task)
- `doctor` install automation (separate task)
- uv version compatibility matrix below 0.10.7 (future work)
