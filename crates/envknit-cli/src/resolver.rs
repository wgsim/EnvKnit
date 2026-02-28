use crate::config::PackageSpec;
use crate::lockfile::LockedPackage;
use anyhow::{Context, Result};
use std::collections::HashMap;

pub struct Resolver {
    pub dry_run: bool,
}

impl Resolver {
    pub fn new(dry_run: bool) -> Self {
        Resolver { dry_run }
    }

    pub fn resolve(&self, packages: &[PackageSpec]) -> Result<Vec<LockedPackage>> {
        let mut resolved = Vec::new();

        for spec in packages {
            let versions = self
                .fetch_pypi_versions(&spec.name)
                .with_context(|| format!("Failed to fetch versions for '{}'", spec.name))?;

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

            resolved.push(LockedPackage {
                name: spec.name.clone(),
                version: chosen.clone(),
                install_path: None,
                backend: None,
                dependencies: vec![],
            });
        }

        Ok(resolved)
    }

    fn fetch_pypi_versions(&self, package: &str) -> Result<Vec<String>> {
        let url = format!("https://pypi.org/pypi/{}/json", package);
        let client = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .context("Failed to build HTTP client")?;

        let resp = client
            .get(&url)
            .send()
            .or_else(|_| {
                // retry once
                client.get(&url).send()
            })
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
            .map(|map: &serde_json::Map<String, serde_json::Value>| map.keys().cloned().collect())
            .unwrap_or_default();

        // Sort descending so we pick latest first
        let mut sorted = releases;
        sorted.sort_by(|a, b| Self::compare_version_strings(b, a));
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
                        // Compatible release: >= req, < next major segment
                        let parts: Vec<&str> = req.split('.').collect();
                        if parts.len() < 2 {
                            return ord != std::cmp::Ordering::Less;
                        }
                        let upper: String = parts[..parts.len() - 1]
                            .iter()
                            .enumerate()
                            .map(|(i, p)| {
                                if i == parts.len() - 2 {
                                    // bump second-to-last segment
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
        // No operator: treat as exact
        version == constraint
    }

    /// Numeric tuple comparison of dotted version strings.
    fn compare_version_strings(a: &str, b: &str) -> std::cmp::Ordering {
        // Strip pre/post/dev suffixes at first non-numeric-or-dot char
        let normalize = |s: &str| -> Vec<u64> {
            s.split('.')
                .map(|seg| {
                    // take leading digits only
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

// Silence unused import warning — HashMap used only if we expand transitive deps later.
#[allow(dead_code)]
fn _unused_hashmap_hint() {
    let _: HashMap<String, String> = HashMap::new();
}
