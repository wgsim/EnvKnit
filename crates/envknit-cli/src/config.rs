use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub const CONFIG_FILE: &str = "envknit.yaml";

#[derive(Debug, Serialize, Clone)]
pub struct PackageSpec {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub extras: Vec<String>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum PackageSpecInput {
    String(String),
    Struct {
        name: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        version: Option<String>,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        extras: Vec<String>,
    },
}

impl<'de> serde::Deserialize<'de> for PackageSpec {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let input = PackageSpecInput::deserialize(deserializer)?;
        Ok(match input {
            PackageSpecInput::String(s) => PackageSpec::parse(&s),
            PackageSpecInput::Struct { name, version, extras } => PackageSpec { name, version, extras },
        })
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EnvironmentConfig {
    #[serde(default)]
    pub packages: Vec<PackageSpec>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub dev_packages: Vec<PackageSpec>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backend: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub python_version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_version: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Config {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub envknit_version: Option<String>,
    #[serde(default)]
    pub environments: HashMap<String, EnvironmentConfig>,
}

impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .with_context(|| format!("Failed to read config: {}", path.display()))?;
        serde_yaml::from_str(&content)
            .with_context(|| format!("Failed to parse config: {}", path.display()))
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        let content = serde_yaml::to_string(self)?;
        std::fs::write(path, content)?;
        Ok(())
    }

    pub fn find(start: &Path) -> Option<PathBuf> {
        let mut dir = start.to_path_buf();
        loop {
            let candidate = dir.join(CONFIG_FILE);
            if candidate.exists() {
                return Some(candidate);
            }
            if !dir.pop() {
                return None;
            }
        }
    }
}

impl PackageSpec {
    /// Format as a PEP 508 spec string for uv: `name[extras]version`.
    /// Examples: `"requests"`, `"requests>=2.28"`, `"requests[security]>=2.28"`.
    pub fn to_uv_spec(&self) -> String {
        let extras = if self.extras.is_empty() {
            String::new()
        } else {
            format!("[{}]", self.extras.join(","))
        };
        format!("{}{}{}", self.name, extras, self.version.as_deref().unwrap_or(""))
    }

    /// Parse "name==1.0", "name>=1.0,<2.0", or plain "name".
    ///
    /// Embedded `\n` or `\r` characters are stripped as a defence-in-depth
    /// measure against newline injection.  `resolve_set()` also rejects such
    /// specs, but sanitising here prevents a malformed `PackageSpec` from
    /// propagating further through the pipeline.
    pub fn parse(spec: &str) -> Self {
        let sanitised = spec.replace(['\n', '\r'], "");
        let spec = sanitised.trim();
        for op in ["==", ">=", "<=", "!=", "~=", ">", "<"] {
            if let Some(idx) = spec.find(op) {
                return PackageSpec {
                    name: spec[..idx].trim().to_string(),
                    version: Some(spec[idx..].trim().to_string()),
                    extras: vec![],
                };
            }
        }
        PackageSpec {
            name: spec.trim().to_string(),
            version: None,
            extras: vec![],
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_cfg_{}_{}_{label}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn test_to_uv_spec_name_only() {
        let s = PackageSpec { name: "numpy".to_string(), version: None, extras: vec![] };
        assert_eq!(s.to_uv_spec(), "numpy");
    }

    #[test]
    fn test_to_uv_spec_with_version() {
        let s = PackageSpec { name: "requests".to_string(), version: Some(">=2.28".to_string()), extras: vec![] };
        assert_eq!(s.to_uv_spec(), "requests>=2.28");
    }

    #[test]
    fn test_to_uv_spec_with_extras() {
        let s = PackageSpec {
            name: "requests".to_string(),
            version: Some(">=2.28".to_string()),
            extras: vec!["security".to_string(), "socks".to_string()],
        };
        assert_eq!(s.to_uv_spec(), "requests[security,socks]>=2.28");
    }

    #[test]
    fn test_to_uv_spec_extras_no_version() {
        let s = PackageSpec {
            name: "requests".to_string(),
            version: None,
            extras: vec!["security".to_string()],
        };
        assert_eq!(s.to_uv_spec(), "requests[security]");
    }

    #[test]
    fn test_parse_name_only() {
        let s = PackageSpec::parse("numpy");
        assert_eq!(s.name, "numpy");
        assert!(s.version.is_none());
    }

    #[test]
    fn test_parse_with_eq() {
        let s = PackageSpec::parse("numpy==1.26.4");
        assert_eq!(s.name, "numpy");
        assert_eq!(s.version.as_deref(), Some("==1.26.4"));
    }

    #[test]
    fn test_parse_with_ge_compound() {
        let s = PackageSpec::parse("click>=8.0,<9.0");
        assert_eq!(s.name, "click");
        assert_eq!(s.version.as_deref(), Some(">=8.0,<9.0"));
    }

    #[test]
    fn test_parse_with_tilde() {
        let s = PackageSpec::parse("requests~=2.28");
        assert_eq!(s.name, "requests");
        assert_eq!(s.version.as_deref(), Some("~=2.28"));
    }

    #[test]
    fn test_parse_trims_whitespace() {
        let s = PackageSpec::parse("  numpy  ");
        assert_eq!(s.name, "numpy");
    }

    #[test]
    fn test_parse_strips_newlines() {
        let s = PackageSpec::parse("requests\n--index-url https://evil.com");
        // newline is stripped; only "requests" survives
        assert_eq!(s.name, "requests");
        assert!(s.version.is_none());
    }

    #[test]
    fn test_global_config_subprocess_timeout_default() {
        use crate::global_config::GlobalConfig;
        let cfg = GlobalConfig::default();
        assert_eq!(cfg.subprocess_timeout_secs, 300);
    }

    #[test]
    fn test_global_config_subprocess_timeout_zero_disables() {
        use crate::global_config::GlobalConfig;
        let yaml = "subprocess_timeout_secs: 0\n";
        let cfg: GlobalConfig = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(cfg.subprocess_timeout_secs, 0);
    }

    #[test]
    fn test_config_save_and_load() {
        let dir = tmpdir("round_trip");
        let path = dir.join(CONFIG_FILE);
        let mut envs = HashMap::new();
        envs.insert("default".to_string(), EnvironmentConfig {
            packages: vec![PackageSpec { name: "click".to_string(), version: Some(">=8.0".to_string()), extras: vec![] }],
            dev_packages: vec![],
            backend: None,
            python_version: None,
            node_version: None,
        });
        let cfg = Config { envknit_version: Some("0.1.0".to_string()), environments: envs };
        cfg.save(&path).unwrap();

        let loaded = Config::load(&path).unwrap();
        assert!(loaded.environments.contains_key("default"));
        assert_eq!(loaded.environments["default"].packages[0].name, "click");
    }

    #[test]
    fn test_config_find_walks_up() {
        let dir = tmpdir("walkup");
        let sub = dir.join("sub");
        fs::create_dir_all(&sub).unwrap();
        let cfg_path = dir.join(CONFIG_FILE);
        let cfg = Config { envknit_version: None, environments: HashMap::new() };
        cfg.save(&cfg_path).unwrap();

        let found = Config::find(&sub);
        assert!(found.is_some());
        assert_eq!(found.unwrap(), cfg_path);
    }

    #[test]
    fn test_config_find_returns_none() {
        let dir = tmpdir("notfound");
        let found = Config::find(&dir);
        assert!(found.is_none());
    }

    #[test]
    fn test_parse_string_packages_from_yaml() {
        let dir = tmpdir("str_yaml");
        let yaml = "environments:\n  default:\n    packages:\n      - numpy>=1.24\n      - click\n";
        let path = dir.join(CONFIG_FILE);
        std::fs::write(&path, yaml).unwrap();
        let cfg = Config::load(&path).unwrap();
        let pkgs = &cfg.environments["default"].packages;
        assert_eq!(pkgs[0].name, "numpy");
        assert_eq!(pkgs[0].version.as_deref(), Some(">=1.24"));
        assert_eq!(pkgs[1].name, "click");
        assert!(pkgs[1].version.is_none());
    }

    #[test]
    fn test_parse_struct_packages_from_yaml() {
        let dir = tmpdir("struct_yaml");
        let yaml = "environments:\n  default:\n    packages:\n      - name: numpy\n        version: '>=1.24'\n";
        let path = dir.join(CONFIG_FILE);
        std::fs::write(&path, yaml).unwrap();
        let cfg = Config::load(&path).unwrap();
        let pkgs = &cfg.environments["default"].packages;
        assert_eq!(pkgs[0].name, "numpy");
        assert_eq!(pkgs[0].version.as_deref(), Some(">=1.24"));
    }

    #[test]
    fn test_node_version_round_trips() {
        let dir = tmpdir("node_ver");
        let yaml = "environments:\n  frontend:\n    node_version: '20.11'\n    packages: []\n";
        let path = dir.join(CONFIG_FILE);
        std::fs::write(&path, yaml).unwrap();
        let cfg = Config::load(&path).unwrap();
        assert_eq!(
            cfg.environments["frontend"].node_version.as_deref(),
            Some("20.11")
        );

        // Also test serialization: save a Config with node_version, reload, and assert it survives.
        let mut envs = HashMap::new();
        envs.insert("frontend".to_string(), EnvironmentConfig {
            packages: vec![],
            dev_packages: vec![],
            backend: None,
            python_version: None,
            node_version: Some("20.11".to_string()),
        });
        let cfg2 = Config { envknit_version: None, environments: envs };
        let save_path = dir.join("envknit2.yaml");
        cfg2.save(&save_path).unwrap();
        let reloaded = Config::load(&save_path).unwrap();
        assert_eq!(
            reloaded.environments["frontend"].node_version.as_deref(),
            Some("20.11")
        );
    }
}
