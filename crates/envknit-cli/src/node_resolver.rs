/// Resolve a Node.js binary path for a given version spec.
///
/// Resolution order (overridable via GlobalConfig.node_version_manager):
///   1. mise  — `mise ls --installed node` + `mise exec node@<ver> -- which node`
///   2. fnm   — checks $FNM_DIR/node-versions/<ver>/installation/bin/node
///   3. nvm   — checks $NVM_DIR/versions/node/v<ver>/bin/node directly
///   4. system — `node --version` if it matches
use crate::global_config::GlobalConfig;
use crate::python_resolver::version_matches;
use anyhow::{bail, Result};
use std::path::PathBuf;
use std::process::Command;

/// Returns the absolute path to a `node` binary satisfying `version_spec`.
/// `version_spec`: "20", "20.11", "20.11.0", ">=18", "==20.11.0".
pub fn resolve_node(version_spec: &str) -> Result<PathBuf> {
    let global_cfg = GlobalConfig::load().unwrap_or_default();

    // If user has pinned a version manager, skip the chain.
    match global_cfg.node_version_manager.as_deref() {
        Some("mise") => {
            return try_mise(version_spec)
                .ok_or_else(|| anyhow::anyhow!(
                    "node {} not found via mise. Run: mise use node@{}",
                    version_spec, version_spec
                ));
        }
        Some("fnm") => {
            return try_fnm(version_spec)
                .ok_or_else(|| anyhow::anyhow!(
                    "node {} not found via fnm. Run: fnm install {}",
                    version_spec, version_spec
                ));
        }
        Some("nvm") => {
            return try_nvm(version_spec)
                .ok_or_else(|| anyhow::anyhow!(
                    "node {} not found via nvm. Run: nvm install {}",
                    version_spec, version_spec
                ));
        }
        _ => {}
    }

    // Auto-detection chain: mise → fnm → nvm → system
    if let Some(p) = try_mise(version_spec) { return Ok(p); }
    if let Some(p) = try_fnm(version_spec) { return Ok(p); }
    if let Some(p) = try_nvm(version_spec) { return Ok(p); }
    if let Some(p) = try_system(version_spec) { return Ok(p); }

    bail!(
        "No Node.js {} found via mise, fnm, nvm, or system PATH.\n  \
         Install it with: fnm install {} OR mise use node@{}",
        version_spec, version_spec, version_spec
    )
}

/// Returns the bin directory containing node/npm/npx for a resolved node binary.
/// E.g. `/home/user/.nvm/versions/node/v20.11.0/bin/node`
///    → `/home/user/.nvm/versions/node/v20.11.0/bin`
pub fn node_bin_dir(node_binary: &PathBuf) -> PathBuf {
    node_binary.parent().unwrap_or(node_binary.as_path()).to_path_buf()
}

fn try_mise(version_spec: &str) -> Option<PathBuf> {
    Command::new("mise").arg("--version").output().ok()?.status.success().then_some(())?;

    let out = Command::new("mise")
        .args(["ls", "--installed", "node"])
        .output()
        .ok()?;
    let stdout = String::from_utf8_lossy(&out.stdout);

    // Lines look like: "node  20.11.0  ..." — pick column index 1, find highest match
    let matched = stdout
        .lines()
        .filter_map(|l| l.split_whitespace().nth(1))
        .filter(|v| version_matches(v, version_spec))
        .max_by(|a, b| compare_version_strings(a, b))?
        .to_string();

    let out = Command::new("mise")
        .args(["exec", &format!("node@{}", matched), "--", "which", "node"])
        .output()
        .ok()?;

    if out.status.success() {
        let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if !path.is_empty() {
            return Some(PathBuf::from(path));
        }
    }
    None
}

fn try_fnm(version_spec: &str) -> Option<PathBuf> {
    // fnm stores versions in $FNM_DIR/node-versions/ (default: ~/.local/share/fnm/node-versions/)
    // or legacy ~/.fnm/node-versions/ on some systems.
    // Check FNM_DIR env var first (XDG_DATA_HOME compliance).
    let home = dirs_next::home_dir()?;
    let fnm_dir_from_env = std::env::var("FNM_DIR").ok().map(PathBuf::from);

    let fnm_base = fnm_dir_from_env.clone().unwrap_or_else(|| {
        std::env::var("XDG_DATA_HOME")
            .map(|xdg| PathBuf::from(xdg).join("fnm"))
            .unwrap_or_else(|_| home.join(".local").join("share").join("fnm"))
    });

    // Only include legacy ~/.fnm path when FNM_DIR is not explicitly set.
    let mut bases = vec![fnm_base.join("node-versions")];
    if fnm_dir_from_env.is_none() {
        bases.push(home.join(".fnm").join("node-versions"));
    }

    for base in &bases {
        if !base.exists() { continue; }

        // FIX: use `else { continue }` not `?` — avoids early return skipping second base.
        let Ok(entries) = std::fs::read_dir(base) else { continue; };

        // Filter non-semver dirs ("aliases", "default") and match version.
        // Use max_by instead of sort + next to avoid unnecessary Vec allocation.
        let best = entries
            .filter_map(Result::ok)
            .filter_map(|e| {
                let name = e.file_name().to_string_lossy().to_string();
                let ver = name.trim_start_matches('v');
                // Reject non-semver entries ("default", "aliases", "lts") by requiring
                // at least one digit segment.
                if ver.split('.').next().map_or(false, |s| s.chars().all(|c| c.is_ascii_digit()))
                    && version_matches(ver, version_spec)
                {
                    Some(name)
                } else {
                    None
                }
            })
            .max_by(|a, b| {
                compare_version_strings(
                    a.trim_start_matches('v'),
                    b.trim_start_matches('v'),
                )
            })?;

        let node = base.join(&best).join("installation").join("bin").join("node");
        if node.exists() { return Some(node); }
    }
    None
}

fn try_nvm(version_spec: &str) -> Option<PathBuf> {
    // nvm is a shell function — cannot be invoked via Command::new("nvm").
    // Check NVM_DIR env var first, then fall back to ~/.nvm.
    let nvm_root = if let Ok(dir) = std::env::var("NVM_DIR") {
        PathBuf::from(dir)
    } else {
        dirs_next::home_dir()?.join(".nvm")
    };
    let nvm_dir = nvm_root.join("versions").join("node");
    if !nvm_dir.exists() { return None; }

    let entries = std::fs::read_dir(&nvm_dir).ok()?;

    // Filter non-semver dirs ("system", "lts", "aliases") and pick highest match.
    let best = entries
        .filter_map(Result::ok)
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().to_string(); // "v20.11.0"
            let ver = name.trim_start_matches('v');
            // Reject non-semver: require first segment to be all-digit.
            if ver.split('.').next().map_or(false, |s| s.chars().all(|c| c.is_ascii_digit()))
                && version_matches(ver, version_spec)
            {
                Some(name)
            } else {
                None
            }
        })
        .max_by(|a, b| {
            compare_version_strings(
                a.trim_start_matches('v'),
                b.trim_start_matches('v'),
            )
        })?;

    let node = nvm_dir.join(&best).join("bin").join("node");
    if node.exists() { Some(node) } else { None }
}

fn try_system(version_spec: &str) -> Option<PathBuf> {
    let out = Command::new("node").arg("--version").output().ok()?;
    if !out.status.success() { return None; }

    // node --version prints "v20.11.0"
    let raw = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let ver = raw.trim_start_matches('v');

    if version_matches(ver, version_spec) {
        which_cmd("node").ok().map(PathBuf::from)
    } else {
        None
    }
}

fn which_cmd(cmd: &str) -> Result<String, ()> {
    Command::new("which")
        .arg(cmd)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .ok_or(())
}

fn compare_version_strings(a: &str, b: &str) -> std::cmp::Ordering {
    let parse = |s: &str| -> Vec<u64> {
        s.split('.')
            .map(|seg| seg.chars().take_while(|c| c.is_ascii_digit()).collect::<String>())
            .filter_map(|s| s.parse().ok())
            .collect()
    };
    let av = parse(a);
    let bv = parse(b);
    let len = av.len().max(bv.len());
    for i in 0..len {
        let x = av.get(i).copied().unwrap_or(0);
        let y = bv.get(i).copied().unwrap_or(0);
        match x.cmp(&y) {
            std::cmp::Ordering::Equal => continue,
            other => return other,
        }
    }
    std::cmp::Ordering::Equal
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_node_prefix_match() {
        assert!(version_matches("20.11.0", "20.11"));
        assert!(version_matches("20.11.0", "20"));
        assert!(!version_matches("18.19.0", "20"));
    }

    #[test]
    fn test_node_exact_match() {
        assert!(version_matches("20.11.0", "==20.11.0"));
        assert!(!version_matches("20.11.1", "==20.11.0"));
    }

    #[test]
    fn test_node_ge_match() {
        assert!(version_matches("20.11.0", ">=20"));
        assert!(!version_matches("18.0.0", ">=20"));
    }

    #[test]
    fn test_node_bin_dir() {
        let node = std::path::PathBuf::from("/home/user/.nvm/versions/node/v20.11.0/bin/node");
        let bin = node_bin_dir(&node);
        assert_eq!(bin, std::path::PathBuf::from("/home/user/.nvm/versions/node/v20.11.0/bin"));
    }

    #[test]
    fn test_resolve_node_fails_gracefully_with_bad_spec() {
        // With no version managers installed in CI, this will fail — that's OK.
        // We just verify it returns an Err, not a panic.
        let result = resolve_node("99.99.99");
        assert!(result.is_err());
    }
}
