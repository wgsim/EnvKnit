use crate::config::Config;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: String) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found.")?;
    let mut config = Config::load(&config_path)?;

    let env_config = config.environments.get_mut(&env)
        .with_context(|| format!("Environment '{}' not found", env))?;

    let before = env_config.packages.len();
    env_config.packages.retain(|p| p.name != package);

    if env_config.packages.len() == before {
        bail!("Package '{}' not found in environment '{}'", package, env);
    }

    config.save(&config_path)?;
    println!("{} Removed '{}' from environment '{}'", "✓".green(), package, env);
    println!("  Run `envknit lock` to update the lock file");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::{add, init};
    use crate::config::Config;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!("envknit_rm_{}_{}_{label}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().subsec_nanos()));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn setup(label: &str) -> (std::path::PathBuf, std::path::PathBuf) {
        let dir = tmpdir(label);
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        add::run("numpy".to_string(), "default".to_string(), None, false).unwrap();
        (dir, orig)
    }

    #[test]
    fn test_remove_existing() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup("e");
        run("numpy".to_string(), "default".to_string()).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(cfg.environments["default"].packages.is_empty());
    }

    #[test]
    fn test_remove_nonexistent_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("nx");
        let result = run("pandas".to_string(), "default".to_string());
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_remove_wrong_env_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("we");
        let result = run("numpy".to_string(), "ml".to_string());
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
