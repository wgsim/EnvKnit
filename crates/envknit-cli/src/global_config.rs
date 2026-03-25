/// Global user configuration at `~/.envknit/config.yaml`.
///
/// All fields are optional — the file need not exist.  When it does exist,
/// values here act as project-level defaults (project `envknit.yaml` wins).
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct GlobalConfig {
    /// Default backend when not specified in project config. ("pip" | "uv")
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_backend: Option<String>,

    /// Default Python version for new environments when not specified.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_python_version: Option<String>,

    /// Override the package store directory (default: ~/.envknit/packages/).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub store_dir: Option<String>,

    /// Node.js version manager to use for `node` toolchain management. // e.g. "mise", "fnm", "nvm"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_version_manager: Option<String>,

    /// PyPI metadata cache TTL in seconds (default: 300).
    #[serde(default = "default_cache_ttl")]
    pub cache_ttl_secs: u64,

    /// Number of parallel pip workers during `install` (default: 4).
    #[serde(default = "default_parallel_jobs")]
    pub parallel_jobs: usize,

    /// Timeout in seconds for individual subprocess calls (uv pip compile, pip install).
    /// Set to 0 to disable the timeout. Default: 300.
    #[serde(default = "default_subprocess_timeout")]
    pub subprocess_timeout_secs: u64,
}

fn default_cache_ttl() -> u64 {
    300
}

fn default_parallel_jobs() -> usize {
    4
}

fn default_subprocess_timeout() -> u64 {
    300
}

impl Default for GlobalConfig {
    fn default() -> Self {
        Self {
            default_backend: None,
            default_python_version: None,
            store_dir: None,
            node_version_manager: None,
            cache_ttl_secs: default_cache_ttl(),
            parallel_jobs: default_parallel_jobs(),
            subprocess_timeout_secs: default_subprocess_timeout(),
        }
    }
}

impl GlobalConfig {
    /// Path to the global config file.
    pub fn path() -> Option<PathBuf> {
        dirs_next::home_dir().map(|h| h.join(".envknit").join("config.yaml"))
    }

    /// Load from `~/.envknit/config.yaml`.  Returns `Default` if the file
    /// does not exist so callers need not handle the missing-file case.
    pub fn load() -> Result<Self> {
        let path = match Self::path() {
            Some(p) => p,
            None => return Ok(Self::default()),
        };
        if !path.exists() {
            return Ok(Self::default());
        }
        let content = std::fs::read_to_string(&path)
            .with_context(|| format!("Failed to read global config: {}", path.display()))?;
        serde_yaml::from_str(&content)
            .with_context(|| format!("Failed to parse global config: {}", path.display()))
    }

    /// Write the current config to `~/.envknit/config.yaml`.
    pub fn save(&self) -> Result<()> {
        let path = Self::path().context("Cannot determine home directory")?;
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let content = serde_yaml::to_string(self)?;
        std::fs::write(&path, content)?;
        Ok(())
    }

    /// Resolve effective store dir: global config override → ~/.envknit/packages/
    pub fn effective_store_dir(&self) -> PathBuf {
        if let Some(ref dir) = self.store_dir {
            return PathBuf::from(dir);
        }
        dirs_next::home_dir()
            .unwrap_or_else(|| PathBuf::from("/tmp"))
            .join(".envknit")
            .join("packages")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_values() {
        let cfg = GlobalConfig::default();
        assert_eq!(cfg.cache_ttl_secs, 300);
        assert_eq!(cfg.parallel_jobs, 4);
        assert!(cfg.default_backend.is_none());
        assert!(cfg.default_python_version.is_none());
        assert!(cfg.store_dir.is_none());
    }

    #[test]
    fn test_effective_store_dir_default() {
        let cfg = GlobalConfig::default();
        let dir = cfg.effective_store_dir();
        assert!(dir.ends_with("packages"));
        assert!(dir.to_str().unwrap().contains(".envknit"));
    }

    #[test]
    fn test_effective_store_dir_override() {
        let cfg = GlobalConfig {
            store_dir: Some("/custom/store".to_string()),
            ..Default::default()
        };
        assert_eq!(cfg.effective_store_dir(), PathBuf::from("/custom/store"));
    }

    #[test]
    fn test_round_trip_yaml() {
        let cfg = GlobalConfig {
            default_backend: Some("pip".to_string()),
            default_python_version: Some("3.11".to_string()),
            store_dir: None,
            node_version_manager: None,
            cache_ttl_secs: 600,
            parallel_jobs: 8,
        };
        let yaml = serde_yaml::to_string(&cfg).unwrap();
        let loaded: GlobalConfig = serde_yaml::from_str(&yaml).unwrap();
        assert_eq!(loaded.default_backend.as_deref(), Some("pip"));
        assert_eq!(loaded.default_python_version.as_deref(), Some("3.11"));
        assert_eq!(loaded.cache_ttl_secs, 600);
        assert_eq!(loaded.parallel_jobs, 8);
    }

    #[test]
    fn test_load_missing_file_returns_default() {
        // Point to a nonexistent path via a temp dir trick.
        // We test via serde_yaml::from_str directly since load() uses $HOME.
        let yaml = "";
        let cfg: Result<GlobalConfig, _> = serde_yaml::from_str(yaml);
        // Empty YAML parses to default struct.
        assert!(cfg.is_ok());
    }

    #[test]
    fn test_node_version_manager_round_trips() {
        // Load: YAML with node_version_manager deserializes correctly.
        let yaml = "node_version_manager: fnm\n";
        let cfg: GlobalConfig = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(cfg.node_version_manager, Some("fnm".to_string()));

        // Skip-if-none: field must be absent when None.
        let cfg_none = GlobalConfig::default();
        let serialized = serde_yaml::to_string(&cfg_none).unwrap();
        assert!(
            !serialized.contains("node_version_manager"),
            "Expected field to be omitted when None, got: {serialized}"
        );
    }
}
