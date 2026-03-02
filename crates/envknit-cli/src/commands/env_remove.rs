use crate::config::Config;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(name: String) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found. Run `envknit init` first.")?;
    let mut config = Config::load(&config_path)?;

    if !config.environments.contains_key(&name) {
        bail!("Environment '{}' not found", name);
    }

    config.environments.remove(&name);
    config.save(&config_path)?;
    println!("{} Removed environment '{}'", "✓".green(), name);
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
            "envknit_envremove_{}_{}_{label}",
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
    fn test_env_remove_existing() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("e");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        super::super::env_create::run("ml".to_string(), None).unwrap();
        run("ml".to_string()).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(!cfg.environments.contains_key("ml"));
    }

    #[test]
    fn test_env_remove_nonexistent_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("nx");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        let result = run("staging".to_string());
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_env_remove_no_config_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("nc");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let result = run("default".to_string());
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
