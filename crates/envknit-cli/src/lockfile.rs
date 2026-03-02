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
    /// True if this package belongs to the dev_packages list.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub dev: bool,
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_lock_{}_{}_{label}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn pkg(name: &str, version: &str) -> LockedPackage {
        LockedPackage { name: name.to_string(), version: version.to_string(), install_path: None, backend: None, dependencies: vec![], dev: false }
    }

    #[test]
    fn test_lockfile_load_valid() {
        let dir = tmpdir("load");
        let path = dir.join(LOCK_FILE);
        fs::write(&path, "schema_version: '1.0'\npackages: []\n").unwrap();
        let lock = LockFile::load(&path).unwrap();
        assert_eq!(lock.schema_version, "1.0");
        assert!(lock.packages.is_empty());
    }

    #[test]
    fn test_lockfile_future_major_rejected() {
        let dir = tmpdir("future");
        let path = dir.join(LOCK_FILE);
        fs::write(&path, "schema_version: '99.0'\npackages: []\n").unwrap();
        let result = LockFile::load(&path);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("99.0"));
    }

    #[test]
    fn test_lockfile_save_round_trip() {
        let dir = tmpdir("rt");
        let path = dir.join(LOCK_FILE);
        let mut envs: HashMap<String, Vec<LockedPackage>> = HashMap::new();
        envs.insert("default".to_string(), vec![pkg("numpy", "1.24.0"), pkg("click", "8.1.0")]);
        let orig = LockFile { schema_version: LOCK_SCHEMA_VERSION.to_string(), lock_generated_at: None, resolver_version: None, packages: vec![], environments: envs };
        orig.save(&path).unwrap();
        let loaded = LockFile::load(&path).unwrap();
        let pkgs = loaded.environments.get("default").unwrap();
        assert_eq!(pkgs.len(), 2);
        assert_eq!(pkgs[0].name, "numpy");
    }

    #[test]
    fn test_lockfile_find_walks_up() {
        let dir = tmpdir("wu");
        let sub = dir.join("sub");
        fs::create_dir_all(&sub).unwrap();
        let lp = dir.join(LOCK_FILE);
        let lock = LockFile { schema_version: LOCK_SCHEMA_VERSION.to_string(), lock_generated_at: None, resolver_version: None, packages: vec![], environments: Default::default() };
        lock.save(&lp).unwrap();
        assert_eq!(LockFile::find(&sub).unwrap(), lp);
    }

    #[test]
    fn test_packages_for_env_returns_env_packages() {
        let mut envs: HashMap<String, Vec<LockedPackage>> = HashMap::new();
        envs.insert("default".to_string(), vec![pkg("numpy", "1.24.0")]);
        let lock = LockFile { schema_version: LOCK_SCHEMA_VERSION.to_string(), lock_generated_at: None, resolver_version: None, packages: vec![pkg("click", "8.0.0")], environments: envs };
        let pkgs = lock.packages_for_env("default");
        assert_eq!(pkgs.len(), 1);
        assert_eq!(pkgs[0].name, "numpy");
    }

    #[test]
    fn test_packages_for_env_falls_back_to_packages() {
        let lock = LockFile { schema_version: LOCK_SCHEMA_VERSION.to_string(), lock_generated_at: None, resolver_version: None, packages: vec![pkg("click", "8.0.0")], environments: Default::default() };
        let pkgs = lock.packages_for_env("nonexistent");
        assert_eq!(pkgs.len(), 1);
        assert_eq!(pkgs[0].name, "click");
    }
}
