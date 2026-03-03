use crate::config::{Config, EnvironmentConfig, CONFIG_FILE};
use anyhow::{bail, Result};
use colored::Colorize;
use std::collections::HashMap;
use std::path::Path;

pub fn run(env: String, backend: Option<String>) -> Result<()> {
    let config_path = Path::new(CONFIG_FILE);
    if config_path.exists() {
        bail!("{} already exists in current directory", CONFIG_FILE);
    }

    let mut environments = HashMap::new();
    environments.insert(env.clone(), EnvironmentConfig {
        packages: vec![],
        dev_packages: vec![],
        backend,
        python_version: None,
        node_version: None,
    });

    let config = Config {
        envknit_version: Some(env!("CARGO_PKG_VERSION").to_string()),
        environments,
    };

    config.save(config_path)?;
    println!("{} Initialized EnvKnit project (environment: '{}')", "✓".green(), env);
    println!("  Edit {} to add packages, then run `envknit lock`", CONFIG_FILE);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::Config;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!("envknit_init_{}_{}_{label}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().subsec_nanos()));
        fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn test_init_creates_yaml() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("c");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        run("default".to_string(), None).unwrap();
        std::env::set_current_dir(orig).unwrap();
        assert!(dir.join(CONFIG_FILE).exists());
        let cfg = Config::load(&dir.join(CONFIG_FILE)).unwrap();
        assert!(cfg.environments.contains_key("default"));
    }

    #[test]
    fn test_init_fails_if_exists() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("e");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        run("default".to_string(), None).unwrap();
        let result = run("default".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_init_custom_env_and_backend() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("k");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        run("ml".to_string(), Some("pip".to_string())).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(CONFIG_FILE)).unwrap();
        assert!(cfg.environments.contains_key("ml"));
        assert_eq!(cfg.environments["ml"].backend.as_deref(), Some("pip"));
    }
}
