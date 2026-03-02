/// Resolve a Python interpreter path for a given version spec.
///
/// Resolution order:
///   1. mise: `mise which python` after `mise use python@<ver>`
///   2. pyenv: `pyenv root`/versions/<ver>/bin/python3
///   3. System: `python3.X` or `python3` if version matches
use anyhow::{bail, Result};
use std::path::PathBuf;
use std::process::Command;

/// Returns the absolute path to a Python interpreter satisfying `version_spec`.
/// `version_spec` is a string like "3.11", "3.11.6", ">=3.10".
pub fn resolve_python(version_spec: &str) -> Result<PathBuf> {
    // Try mise first
    if let Some(p) = try_mise(version_spec) {
        return Ok(p);
    }

    // Try pyenv
    if let Some(p) = try_pyenv(version_spec) {
        return Ok(p);
    }

    // Try system python
    if let Some(p) = try_system(version_spec) {
        return Ok(p);
    }

    bail!(
        "No Python {} found via mise, pyenv, or system PATH.\n  \
         Install it with: pyenv install {} OR mise use python@{}",
        version_spec, version_spec, version_spec
    )
}

fn try_mise(version_spec: &str) -> Option<PathBuf> {
    // Check mise is available
    Command::new("mise").arg("--version").output().ok()?.status.success().then_some(())?;

    // Ask mise for an installed python matching the spec
    let out = Command::new("mise")
        .args(["ls", "--installed", "python"])
        .output()
        .ok()?;

    let stdout = String::from_utf8_lossy(&out.stdout);
    let matched = stdout
        .lines()
        .filter_map(|l| l.split_whitespace().nth(1)) // "python  3.11.6  ..."
        .find(|v| version_matches(v, version_spec))?;

    // Get the interpreter path via `mise exec`
    let out = Command::new("mise")
        .args(["exec", &format!("python@{}", matched), "--", "which", "python3"])
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

fn try_pyenv(version_spec: &str) -> Option<PathBuf> {
    let out = Command::new("pyenv").arg("root").output().ok()?;
    if !out.status.success() {
        return None;
    }
    let root = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let versions_dir = PathBuf::from(&root).join("versions");

    let entries = std::fs::read_dir(&versions_dir).ok()?;
    let mut candidates: Vec<String> = entries
        .flatten()
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().to_string();
            if version_matches(&name, version_spec) {
                Some(name)
            } else {
                None
            }
        })
        .collect();

    // Pick the highest matching version
    candidates.sort_by(|a, b| compare_version_strings(b, a));
    let best = candidates.into_iter().next()?;

    let interpreter = PathBuf::from(&root)
        .join("versions")
        .join(&best)
        .join("bin")
        .join("python3");

    if interpreter.exists() { Some(interpreter) } else { None }
}

fn try_system(version_spec: &str) -> Option<PathBuf> {
    // Try python3.X first (exact minor version)
    let minor = version_spec.split('.').take(2).collect::<Vec<_>>().join(".");
    let versioned = format!("python{}", minor);

    for cmd in &[versioned.as_str(), "python3", "python"] {
        let Ok(out) = Command::new(cmd).arg("--version").output() else { continue };
        if !out.status.success() { continue }
        let ver_str = String::from_utf8_lossy(&out.stdout)
            .trim()
            .trim_start_matches("Python ")
            .to_string();
        if version_matches(&ver_str, version_spec) {
            if let Ok(path) = which_cmd(cmd) {
                return Some(PathBuf::from(path));
            }
        }
    }
    None
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

/// Returns the pip executable associated with a given Python interpreter.
/// E.g. `/home/user/.pyenv/versions/3.11.6/bin/python3` →
///      `/home/user/.pyenv/versions/3.11.6/bin/pip3`
pub fn pip_for_python(python: &PathBuf) -> PathBuf {
    let parent = python.parent().unwrap_or(python.as_path());
    // Try pip3 first, then pip in the same bin/ dir
    for name in &["pip3", "pip"] {
        let candidate = parent.join(name);
        if candidate.exists() {
            return candidate;
        }
    }
    // Fallback: invoke python -m pip
    python.clone()
}

/// Returns args to use pip: either `[pip_path]` or `[python_path, "-m", "pip"]`.
pub fn pip_args(python: &PathBuf) -> Vec<String> {
    let pip = pip_for_python(python);
    if pip == *python {
        vec![
            python.to_string_lossy().to_string(),
            "-m".to_string(),
            "pip".to_string(),
        ]
    } else {
        vec![pip.to_string_lossy().to_string()]
    }
}

/// Simple version matching: checks if `version` satisfies `spec`.
/// Supports: "3.11", "3.11.6" (prefix match), ">=3.10", ">3.9", "==3.11.6".
pub fn version_matches(version: &str, spec: &str) -> bool {
    let spec = spec.trim();
    if spec.is_empty() {
        return true;
    }

    let ops = [">=", "<=", "==", "!=", ">", "<"];
    for op in ops {
        if let Some(req) = spec.strip_prefix(op) {
            let ord = compare_version_strings(version, req.trim());
            return match op {
                "==" => ord == std::cmp::Ordering::Equal,
                "!=" => ord != std::cmp::Ordering::Equal,
                ">=" => ord != std::cmp::Ordering::Less,
                "<=" => ord != std::cmp::Ordering::Greater,
                ">" => ord == std::cmp::Ordering::Greater,
                "<" => ord == std::cmp::Ordering::Less,
                _ => false,
            };
        }
    }

    // No operator — treat as prefix match: "3.11" matches "3.11.6"
    version == spec || version.starts_with(&format!("{}.", spec))
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
    fn test_prefix_match() {
        assert!(version_matches("3.11.6", "3.11"));
        assert!(version_matches("3.11.0", "3.11"));
        assert!(!version_matches("3.10.9", "3.11"));
    }

    #[test]
    fn test_exact_match() {
        assert!(version_matches("3.11.6", "==3.11.6"));
        assert!(!version_matches("3.11.5", "==3.11.6"));
    }

    #[test]
    fn test_ge_match() {
        assert!(version_matches("3.11.0", ">=3.10"));
        assert!(version_matches("3.10.0", ">=3.10"));
        assert!(!version_matches("3.9.9", ">=3.10"));
    }

    #[test]
    fn test_lt_match() {
        assert!(version_matches("3.9.0", "<3.10"));
        assert!(!version_matches("3.10.0", "<3.10"));
    }

    #[test]
    fn test_empty_spec() {
        assert!(version_matches("3.11.6", ""));
    }
}
