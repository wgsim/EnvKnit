use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub const LOCK_FILE: &str = "envknit.lock.yaml";
pub const LOCK_SCHEMA_VERSION: &str = "1.0";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LockedPackage {
    pub name: String,
    pub version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub install_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub backend: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub dependencies: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct LockFile {
    pub schema_version: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lock_generated_at: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub resolver_version: Option<String>,
    #[serde(default)]
    pub packages: Vec<LockedPackage>,
    #[serde(default)]
    pub environments: HashMap<String, Vec<LockedPackage>>,
}

impl LockFile {
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)
            .with_context(|| format!("Lock file not found: {}", path.display()))?;
        let lock: LockFile = serde_yaml::from_str(&content)
            .with_context(|| "Failed to parse lock file")?;

        // Schema version gate: reject future major versions
        let file_major: u32 = lock.schema_version.split('.').next()
            .unwrap_or("1").parse().unwrap_or(1);
        let supported_major: u32 = LOCK_SCHEMA_VERSION.split('.').next()
            .unwrap_or("1").parse().unwrap_or(1);
        if file_major > supported_major {
            bail!(
                "Lock file schema_version '{}' is newer than supported '{}'. \
                 Please upgrade envknit.",
                lock.schema_version, LOCK_SCHEMA_VERSION
            );
        }
        Ok(lock)
    }

    pub fn save(&self, path: &Path) -> Result<()> {
        let content = serde_yaml::to_string(self)?;
        std::fs::write(path, content)?;
        Ok(())
    }

    pub fn find(start: &Path) -> Option<PathBuf> {
        let mut dir = start.to_path_buf();
        loop {
            let candidate = dir.join(LOCK_FILE);
            if candidate.exists() {
                return Some(candidate);
            }
            if !dir.pop() {
                return None;
            }
        }
    }

    pub fn packages_for_env<'a>(&'a self, env: &str) -> Vec<&'a LockedPackage> {
        self.environments.get(env)
            .map(|pkgs| pkgs.iter().collect())
            .unwrap_or_else(|| self.packages.iter().collect())
    }
}
