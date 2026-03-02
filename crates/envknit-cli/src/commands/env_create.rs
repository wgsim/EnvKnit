use crate::config::{Config, EnvironmentConfig};
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(name: String, backend: Option<String>) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found. Run `envknit init` first.")?;
    let mut config = Config::load(&config_path)?;

    if config.environments.contains_key(&name) {
        bail!("Environment '{}' already exists", name);
    }

    config.environments.insert(name.clone(), EnvironmentConfig {
        packages: vec![],
        dev_packages: vec![],
        backend,
        python_version: None,
    });

    config.save(&config_path)?;
    println!("{} Created environment '{}'", "✓".green(), name);
    println!("  Run `envknit lock` to update the lock file");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::init;
    use crate::config::Config;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_envcreate_{}_{}_{label}",
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
    fn test_env_create_new() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("n");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        run("ml".to_string(), None).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(cfg.environments.contains_key("ml"));
    }

    #[test]
    fn test_env_create_duplicate_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("d");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        let result = run("default".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_env_create_with_backend() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("b");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        run("gpu".to_string(), Some("pip".to_string())).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert_eq!(cfg.environments["gpu"].backend.as_deref(), Some("pip"));
    }

    #[test]
    fn test_env_create_no_config_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("nc");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let result = run("ml".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
