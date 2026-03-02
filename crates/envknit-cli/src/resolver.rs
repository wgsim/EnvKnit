use crate::config::PackageSpec;
use crate::lockfile::LockedPackage;
use anyhow::{Context, Result};
use indexmap::IndexMap;
use std::collections::HashSet;
use std::path::PathBuf;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const VERSIONS_TTL_SECS: u64 = 3600; // 1 hour

fn cache_dir() -> PathBuf {
    dirs_next::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".envknit")
        .join("cache")
}

fn versions_cache_path(name: &str) -> PathBuf {
    cache_dir().join("versions").join(format!("{}.json", normalize_name(name)))
}

fn info_cache_path(name: &str, version: &str) -> PathBuf {
    cache_dir().join("info").join(normalize_name(name)).join(format!("{}.json", version))
}

fn now_secs() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or(Duration::ZERO).as_secs()
}

pub struct Resolver {
    pub dry_run: bool,
}

impl Resolver {
    pub fn new(dry_run: bool) -> Self {
        Resolver { dry_run }
    }

    pub fn resolve(&self, packages: &[PackageSpec]) -> Result<Vec<LockedPackage>> {
        let mut resolved: IndexMap<String, LockedPackage> = IndexMap::new();
        let mut queue: Vec<(PackageSpec, usize)> = packages.iter().map(|p| (p.clone(), 0)).collect();
        let mut visited: HashSet<String> = HashSet::new();

        while let Some((spec, depth)) = queue.pop() {
            let name_key = normalize_name(&spec.name);
            if visited.contains(&name_key) {
                continue;
            }
            visited.insert(name_key.clone());

            let versions = match self.fetch_pypi_versions(&spec.name) {
                Ok(v) => v,
                Err(e) => {
                    if depth > 0 {
                        eprintln!("warning: skipping transitive dep '{}': {}", spec.name, e);
                        continue;
                    }
                    return Err(e).with_context(|| format!("Failed to fetch versions for '{}'", spec.name));
                }
            };

            let constraint = spec.version.as_deref().unwrap_or("");
            let chosen = versions
                .iter()
                .find(|v| Self::version_matches(v, constraint))
                .with_context(|| {
                    format!(
                        "No version of '{}' satisfies constraint '{}'",
                        spec.name, constraint
                    )
                })?;
            let chosen_version = chosen.clone();

            // Fetch transitive deps (skip if depth limit reached or fetch fails)
            let dep_names: Vec<String> = if depth < 5 {
                match self.fetch_pypi_info(&spec.name, &chosen_version) {
                    Ok(requires_dist) => {
                        let mut names = Vec::new();
                        for dep_str in &requires_dist {
                            if let Some(dep_spec) = parse_requires_dist(dep_str) {
                                let dep_key = normalize_name(&dep_spec.name);
                                names.push(format!(
                                    "{}{}",
                                    dep_spec.name,
                                    dep_spec.version.as_deref().unwrap_or("")
                                ));
                                if !visited.contains(&dep_key) {
                                    queue.push((dep_spec, depth + 1));
                                }
                            }
                        }
                        names
                    }
                    Err(e) => {
                        eprintln!(
                            "warning: could not fetch deps for '{}=={}: {}",
                            spec.name, chosen_version, e
                        );
                        vec![]
                    }
                }
            } else {
                vec![]
            };

            resolved.insert(
                name_key,
                LockedPackage {
                    name: spec.name.clone(),
                    version: chosen_version,
                    install_path: None,
                    backend: None,
                    dependencies: dep_names,
                    dev: false,
                    sha256: None,
                },
            );
        }

        Ok(resolved.into_values().collect())
    }

    /// Fetch `requires_dist` list for a specific package version from PyPI.
    /// Results are cached permanently (release metadata is immutable).
    fn fetch_pypi_info(&self, package: &str, version: &str) -> Result<Vec<String>> {
        let cache_path = info_cache_path(package, version);
        if let Ok(raw) = std::fs::read_to_string(&cache_path) {
            if let Ok(deps) = serde_json::from_str::<Vec<String>>(&raw) {
                return Ok(deps);
            }
        }

        let url = format!("https://pypi.org/pypi/{}/{}/json", package, version);
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .context("Failed to build HTTP client")?;

        let resp = client
            .get(&url)
            .send()
            .or_else(|_| client.get(&url).send())
            .with_context(|| format!("PyPI request failed for '{}=={}'", package, version))?;

        if !resp.status().is_success() {
            anyhow::bail!(
                "PyPI returned HTTP {} for '{}=={}'",
                resp.status(),
                package,
                version
            );
        }

        let body: serde_json::Value = resp.json().context("Failed to parse PyPI JSON")?;

        let requires_dist: Vec<String> = body["info"]["requires_dist"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect()
            })
            .unwrap_or_default();

        if let Some(parent) = cache_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&cache_path, serde_json::to_string(&requires_dist).unwrap_or_default());

        Ok(requires_dist)
    }

    fn fetch_pypi_versions(&self, package: &str) -> Result<Vec<String>> {
        let cache_path = versions_cache_path(package);

        // Cache hit: check TTL
        if let Ok(raw) = std::fs::read_to_string(&cache_path) {
            if let Ok(obj) = serde_json::from_str::<serde_json::Value>(&raw) {
                let ts = obj["ts"].as_u64().unwrap_or(0);
                if now_secs().saturating_sub(ts) < VERSIONS_TTL_SECS {
                    if let Some(arr) = obj["versions"].as_array() {
                        let versions: Vec<String> = arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect();
                        if !versions.is_empty() {
                            return Ok(versions);
                        }
                    }
                }
            }
        }

        let url = format!("https://pypi.org/pypi/{}/json", package);
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .context("Failed to build HTTP client")?;

        let resp = client
            .get(&url)
            .send()
            .or_else(|_| client.get(&url).send())
            .with_context(|| format!("PyPI request failed for '{}' after retry", package))?;

        if !resp.status().is_success() {
            anyhow::bail!(
                "PyPI returned HTTP {} for package '{}'",
                resp.status(),
                package
            );
        }

        let body: serde_json::Value = resp.json().context("Failed to parse PyPI JSON")?;

        let releases: Vec<String> = body["releases"]
            .as_object()
            .map(|map| map.keys().cloned().collect())
            .unwrap_or_default();

        let mut sorted = releases;
        sorted.sort_by(|a, b| Self::compare_version_strings(b, a));

        if let Some(parent) = cache_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let entry = serde_json::json!({ "ts": now_secs(), "versions": sorted });
        let _ = std::fs::write(&cache_path, entry.to_string());

        Ok(sorted)
    }

    /// Greedy PEP 440-style constraint matching.
    /// Supports: "" (any), "==1.0", ">=1.0", "<=1.0", ">1.0", "<1.0", "!=1.0"
    /// and comma-separated combinations like ">=1.0,<2.0".
    fn version_matches(version: &str, constraint: &str) -> bool {
        let constraint = constraint.trim();
        if constraint.is_empty() {
            return true;
        }
        for part in constraint.split(',') {
            let part = part.trim();
            if !Self::single_constraint_matches(version, part) {
                return false;
            }
        }
        true
    }

    fn single_constraint_matches(version: &str, constraint: &str) -> bool {
        let ops = ["==", "!=", ">=", "<=", "~=", ">", "<"];
        for op in ops {
            if let Some(rest) = constraint.strip_prefix(op) {
                let req = rest.trim();
                let ord = Self::compare_version_strings(version, req);
                return match op {
                    "==" => ord == std::cmp::Ordering::Equal,
                    "!=" => ord != std::cmp::Ordering::Equal,
                    ">=" => ord != std::cmp::Ordering::Less,
                    "<=" => ord != std::cmp::Ordering::Greater,
                    ">" => ord == std::cmp::Ordering::Greater,
                    "<" => ord == std::cmp::Ordering::Less,
                    "~=" => {
                        let parts: Vec<&str> = req.split('.').collect();
                        if parts.len() < 2 {
                            return ord != std::cmp::Ordering::Less;
                        }
                        let upper: String = parts[..parts.len() - 1]
                            .iter()
                            .enumerate()
                            .map(|(i, p)| {
                                if i == parts.len() - 2 {
                                    p.parse::<u64>()
                                        .map(|n| (n + 1).to_string())
                                        .unwrap_or_else(|_| p.to_string())
                                } else {
                                    p.to_string()
                                }
                            })
                            .collect::<Vec<_>>()
                            .join(".");
                        ord != std::cmp::Ordering::Less
                            && Self::compare_version_strings(version, &upper)
                                == std::cmp::Ordering::Less
                    }
                    _ => false,
                };
            }
        }
        version == constraint
    }

    /// Numeric tuple comparison of dotted version strings.
    fn compare_version_strings(a: &str, b: &str) -> std::cmp::Ordering {
        let normalize = |s: &str| -> Vec<u64> {
            s.split('.')
                .map(|seg| {
                    let digits: String = seg.chars().take_while(|c| c.is_ascii_digit()).collect();
                    digits.parse::<u64>().unwrap_or(0)
                })
                .collect()
        };
        let av = normalize(a);
        let bv = normalize(b);
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
}

/// Normalize package name: lowercase, replace `-` and `.` with `_`.
fn normalize_name(name: &str) -> String {
    name.to_lowercase()
        .replace('-', "_")
        .replace('.', "_")
}

/// Parse a PEP 508 dependency string into a `PackageSpec`.
///
/// - Strips environment markers (anything after ` ; `).
/// - Returns `None` for `extra ==` markers (optional deps).
/// - Handles both `"requests (>=2.28)"` and `"requests>=2.28"` forms.
pub fn parse_requires_dist(dep: &str) -> Option<PackageSpec> {
    // Split off environment markers
    let (base, marker) = match dep.split_once(';') {
        Some((b, m)) => (b.trim(), m.trim()),
        None => (dep.trim(), ""),
    };

    // Skip extras (optional dependency groups)
    if marker.contains("extra ==") || marker.contains("extra==") {
        return None;
    }

    // Parse `Name (constraint)` or `Name constraint`
    let (name, version) = if let Some(paren_start) = base.find('(') {
        // e.g. "requests (>=2.28.0)"
        let name = base[..paren_start].trim().to_string();
        let paren_end = base.find(')')?;
        let constraint = base[paren_start + 1..paren_end].trim().to_string();
        (name, if constraint.is_empty() { None } else { Some(constraint) })
    } else {
        // e.g. "requests>=2.28.0" or "requests"
        // Find the earliest-occurring version operator (not first in list order).
        // e.g. "urllib3<3,>=1.21.1": '<' at pos 7 wins over '>=' at pos 10.
        let ops = ["==", "!=", ">=", "<=", "~=", ">", "<"];
        let mut split_pos: Option<(usize, usize)> = None;
        for op in ops {
            if let Some(pos) = base.find(op) {
                if split_pos.map_or(true, |(cur, _)| pos < cur) {
                    split_pos = Some((pos, op.len()));
                }
            }
        }
        if let Some((pos, op_len)) = split_pos {
            let name = base[..pos].trim().to_string();
            // Include the operator in the constraint string
            let constraint = base[pos..].trim().to_string();
            (name, if constraint.is_empty() { None } else { Some(constraint) })
        } else {
            (base.trim().to_string(), None)
        }
    };

    if name.is_empty() {
        return None;
    }

    Some(PackageSpec {
        name,
        version,
        extras: vec![],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_requires_dist_paren() {
        let s = parse_requires_dist("requests (>=2.28.0)").unwrap();
        assert_eq!(s.name, "requests");
        assert_eq!(s.version.as_deref(), Some(">=2.28.0"));
    }

    #[test]
    fn test_parse_requires_dist_inline() {
        let s = parse_requires_dist("click>=7.0").unwrap();
        assert_eq!(s.name, "click");
        assert_eq!(s.version.as_deref(), Some(">=7.0"));
    }

    #[test]
    fn test_parse_requires_dist_no_version() {
        let s = parse_requires_dist("typing-extensions").unwrap();
        assert_eq!(s.name, "typing-extensions");
        assert!(s.version.is_none());
    }

    #[test]
    fn test_parse_requires_dist_skip_extra() {
        let result = parse_requires_dist("numpy ; extra == 'dev'");
        assert!(result.is_none());
    }

    #[test]
    fn test_parse_requires_dist_marker_no_extra() {
        // Non-extra marker: should NOT be skipped
        let s = parse_requires_dist("click>=7.0 ; python_version >= '3.8'").unwrap();
        assert_eq!(s.name, "click");
        assert_eq!(s.version.as_deref(), Some(">=7.0"));
    }

    #[test]
    fn test_normalize_name() {
        assert_eq!(normalize_name("Typing-Extensions"), "typing_extensions");
        assert_eq!(normalize_name("my.package"), "my_package");
    }

    #[test]
    fn test_version_matches_empty_constraint() {
        assert!(Resolver::version_matches("1.0", ""));
    }

    #[test]
    fn test_version_matches_eq() {
        assert!(Resolver::version_matches("1.0.0", "==1.0.0"));
        assert!(!Resolver::version_matches("1.0.1", "==1.0.0"));
    }

    #[test]
    fn test_version_matches_ne() {
        assert!(Resolver::version_matches("1.0.0", "!=2.0.0"));
        assert!(!Resolver::version_matches("2.0.0", "!=2.0.0"));
    }

    #[test]
    fn test_version_matches_ge_le() {
        assert!(Resolver::version_matches("2.0", ">=1.0"));
        assert!(Resolver::version_matches("1.0", ">=1.0"));
        assert!(!Resolver::version_matches("0.9", ">=1.0"));
        assert!(Resolver::version_matches("1.0", "<=2.0"));
        assert!(!Resolver::version_matches("2.1", "<=2.0"));
    }

    #[test]
    fn test_version_matches_gt_lt() {
        assert!(Resolver::version_matches("2.0", ">1.9"));
        assert!(!Resolver::version_matches("1.9", ">1.9"));
        assert!(Resolver::version_matches("1.0", "<2.0"));
        assert!(!Resolver::version_matches("2.0", "<2.0"));
    }

    #[test]
    fn test_version_matches_tilde() {
        assert!(Resolver::version_matches("1.5", "~=1.4"));
        assert!(!Resolver::version_matches("2.0", "~=1.4"));
        assert!(!Resolver::version_matches("1.3", "~=1.4"));
    }

    #[test]
    fn test_version_matches_compound() {
        assert!(Resolver::version_matches("1.5", ">=1.0,<2.0"));
        assert!(!Resolver::version_matches("2.0", ">=1.0,<2.0"));
        assert!(!Resolver::version_matches("0.9", ">=1.0,<2.0"));
    }

    #[test]
    fn test_compare_version_strings() {
        use std::cmp::Ordering;
        assert_eq!(Resolver::compare_version_strings("2.0", "1.9.9"), Ordering::Greater);
        assert_eq!(Resolver::compare_version_strings("1.0", "1.0"), Ordering::Equal);
        assert_eq!(Resolver::compare_version_strings("1.0", "1.0.1"), Ordering::Less);
    }

    #[test]
    fn test_parse_requires_dist_earliest_op() {
        let s = parse_requires_dist("urllib3<3,>=1.21.1").unwrap();
        assert_eq!(s.name, "urllib3");
        assert_eq!(s.version.as_deref(), Some("<3,>=1.21.1"));
    }
}
