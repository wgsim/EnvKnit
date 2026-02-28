use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub const CONFIG_FILE: &str = "envknit.yaml";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PackageSpec {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub extras: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EnvironmentConfig {
    #[serde(default)]
    pub packages: Vec<PackageSpec>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backend: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub python_version: Option<String>,
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
    /// Parse "name==1.0", "name>=1.0,<2.0", or plain "name"
    pub fn parse(spec: &str) -> Self {
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
