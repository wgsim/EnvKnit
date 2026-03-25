use crate::lockfile::LockedPackage;
use crate::process_util::wait_output_timeout;
use anyhow::{bail, Result};
use std::collections::HashSet;
use std::io::Write as IoWrite;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::Duration;

pub fn find_uv() -> Option<PathBuf> {
    // Check uv is runnable
    let status = Command::new("uv").arg("--version").output().ok()?;
    if !status.status.success() {
        return None;
    }
    // Resolve full path
    #[cfg(windows)]
    let which_cmd = "where";
    #[cfg(not(windows))]
    let which_cmd = "which";

    let out = Command::new(which_cmd).arg("uv").output().ok()?;
    if !out.status.success() {
        return None;
    }
    let path_str = String::from_utf8_lossy(&out.stdout);
    let path_str = path_str.lines().next()?.trim();
    if path_str.is_empty() {
        return None;
    }
    Some(PathBuf::from(path_str))
}

pub fn uv_version() -> String {
    let out = Command::new("uv").arg("--version").output();
    match out {
        Ok(o) if o.status.success() => {
            let s = String::from_utf8_lossy(&o.stdout);
            let s = s.trim();
            // Strip "uv " prefix
            s.strip_prefix("uv ").unwrap_or(s).to_string()
        }
        _ => "unknown".to_string(),
    }
}

pub fn parse_uv_output(output: &str) -> Vec<LockedPackage> {
    let mut pkgs = Vec::new();
    for line in output.lines() {
        // --no-annotate is passed to uv, so inline comments won't appear in normal output;
        // just trim whitespace and skip comment/blank lines.
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        // Parse name==version
        if let Some((name, version)) = line.split_once("==") {
            pkgs.push(LockedPackage {
                name: name.trim().to_string(),
                version: version.trim().to_string(),
                install_path: None,
                backend: None,
                dependencies: Vec::new(),
                dev: false,
                sha256: None,
            });
        }
    }
    pkgs
}

fn resolve_set(specs: &[String], python_version: Option<&str>, context: &str, timeout: Duration) -> Result<Vec<LockedPackage>> {
    if specs.is_empty() {
        return Ok(vec![]);
    }

    // Reject specs containing newlines — they would be interpreted as separate
    // lines by uv pip compile and could inject flags like --index-url.
    for spec in specs {
        if spec.contains('\n') || spec.contains('\r') {
            anyhow::bail!(
                "Invalid package spec in {}: {:?} contains a newline character",
                context,
                spec
            );
        }
    }

    let mut cmd = Command::new("uv");
    cmd.args(["pip", "compile", "--no-annotate", "--quiet", "-"]);
    if let Some(py) = python_version {
        cmd.args(["--python-version", py]);
    }
    cmd.stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd.spawn()?;
    if let Some(stdin) = child.stdin.take() {
        let mut stdin = stdin;
        stdin.write_all(specs.join("\n").as_bytes())?;
    }
    let output = wait_output_timeout(child, timeout)?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("uv pip compile failed ({}): {}", context, stderr);
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(parse_uv_output(&stdout))
}

/// Resolve prod and dev dependency sets via uv pip compile.
///
/// Two separate `uv pip compile` invocations are used intentionally:
///
/// 1. **Prod-only** (`specs`): resolves the production closure. This is the canonical
///    set — the packages that will be installed in non-dev environments.
///
/// 2. **Prod+dev combined** (`specs + dev_specs`): uv resolves the full closure
///    including dev packages. Packages not already in the prod set are tagged as
///    `dev = true` and returned separately. This approach ensures dev deps are resolved
///    against the same prod versions (no silent downgrades), while still allowing the
///    caller to strip dev packages from production installs.
///
/// The two invocations may select different versions for a package that appears in both
/// closures when dev deps introduce additional constraints. The prod-set versions are
/// canonical: any package present in both the prod and combined closures uses the version
/// from the prod invocation. Dev-only packages are identified by set-subtraction on prod
/// package names — anything in the combined closure that is not in prod by name.
pub fn resolve(
    specs: &[String],
    dev_specs: &[String],
    python_version: Option<&str>,
    timeout: Duration,
) -> Result<(Vec<LockedPackage>, Vec<LockedPackage>)> {
    let prod = resolve_set(specs, python_version, "prod", timeout)?;
    if dev_specs.is_empty() {
        return Ok((prod, Vec::new()));
    }

    // Build a name→version map from the prod closure for divergence detection.
    let prod_versions: std::collections::HashMap<String, &str> = prod
        .iter()
        .map(|p| (p.name.to_lowercase(), p.version.as_str()))
        .collect();
    let prod_names: HashSet<String> = prod_versions.keys().cloned().collect();

    let mut combined = specs.to_vec();
    combined.extend_from_slice(dev_specs);
    let all = resolve_set(&combined, python_version, "prod+dev", timeout)?;

    // Warn when a shared package resolves to a different version in the combined
    // closure.  The prod version always takes precedence in the lock file, so this
    // is informational only — but it signals a potential constraint conflict.
    for pkg in &all {
        let key = pkg.name.to_lowercase();
        if let Some(&prod_ver) = prod_versions.get(&key) {
            if pkg.version != prod_ver {
                eprintln!(
                    "⚠ version divergence for '{}': prod={}, prod+dev={} — prod version used",
                    pkg.name, prod_ver, pkg.version
                );
            }
        }
    }

    let dev_only: Vec<LockedPackage> = all
        .into_iter()
        .filter(|p| !prod_names.contains(&p.name.to_lowercase()))
        .map(|mut p| {
            p.dev = true;
            p
        })
        .collect();

    Ok((prod, dev_only))
}

#[cfg(test)]
mod tests {
    use super::*;

    // Serialises PATH mutations across all tests in this module.
    // Callers must also pass `-- --test-threads=1` to prevent races with tests in other modules.
    static PATH_MUTEX: std::sync::Mutex<()> = std::sync::Mutex::new(());

    #[test]
    fn parse_uv_output_basic() {
        let output = "requests==2.31.0\nurllib3==2.0.7\n";
        let pkgs = parse_uv_output(output);
        assert_eq!(pkgs.len(), 2);
        assert_eq!(pkgs[0].name, "requests");
        assert_eq!(pkgs[0].version, "2.31.0");
        assert_eq!(pkgs[1].name, "urllib3");
        assert_eq!(pkgs[1].version, "2.0.7");
    }

    #[test]
    fn parse_uv_output_skips_comments_and_blanks() {
        let output = "# This is a comment\n\nrequests==2.31.0\n\n# another comment\nurllib3==2.0.7\n";
        let pkgs = parse_uv_output(output);
        assert_eq!(pkgs.len(), 2);
        assert_eq!(pkgs[0].name, "requests");
        assert_eq!(pkgs[1].name, "urllib3");
    }

    #[test]
    fn parse_uv_output_empty() {
        let pkgs = parse_uv_output("");
        assert!(pkgs.is_empty());
    }

    #[test]
    fn find_uv_returns_none_with_empty_path() {
        let _guard = PATH_MUTEX.lock().unwrap();
        let orig = std::env::var("PATH").unwrap_or_default();
        std::env::set_var("PATH", "");
        let result = find_uv();
        std::env::set_var("PATH", orig);
        assert!(result.is_none());
    }

    #[test]
    fn find_uv_returns_some_when_available() {
        if find_uv().is_none() {
            return;
        } // skip if uv not installed
        assert!(find_uv().unwrap().exists());
    }

    #[test]
    fn resolve_set_rejects_newline_injection() {
        // A spec with an embedded newline must be rejected before reaching uv.
        let bad_specs = vec!["requests\n--index-url https://evil.com".to_string()];
        // resolve_set is private; test via the public resolve() instead.
        let result = resolve(&bad_specs, &[], None);
        assert!(result.is_err());
        let msg = format!("{}", result.unwrap_err());
        assert!(msg.contains("newline"), "error should mention newline, got: {}", msg);
    }

    #[test]
    fn uv_version_returns_non_empty_string() {
        let v = uv_version();
        assert!(!v.is_empty());
        if v != "unknown" {
            assert!(!v.starts_with("uv "), "got: {}", v);
        }
    }
}
