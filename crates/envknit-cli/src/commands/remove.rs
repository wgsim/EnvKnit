use crate::config::Config;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: String, dev: bool) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found.")?;
    let mut config = Config::load(&config_path)?;

    let env_config = config.environments.get_mut(&env)
        .with_context(|| format!("Environment '{}' not found", env))?;

    let target = if dev { &mut env_config.dev_packages } else { &mut env_config.packages };
    let before = target.len();
    target.retain(|p| p.name != package);

    if target.len() == before {
        let kind = if dev { "dev " } else { "" };
        bail!("{}package '{}' not found in environment '{}'", kind, package, env);
    }

    config.save(&config_path)?;
    let kind = if dev { " [dev]" } else { "" };
    println!("{} Removed '{}'{} from environment '{}'", "✓".green(), package, kind, env);
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
        run("numpy".to_string(), "default".to_string(), false).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(cfg.environments["default"].packages.is_empty());
    }

    #[test]
    fn test_remove_nonexistent_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("nx");
        let result = run("pandas".to_string(), "default".to_string(), false);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_remove_wrong_env_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("we");
        let result = run("numpy".to_string(), "ml".to_string(), false);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_remove_dev_package() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup("dev");
        add::run("pytest".to_string(), "default".to_string(), None, true).unwrap();
        run("pytest".to_string(), "default".to_string(), true).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(cfg.environments["default"].dev_packages.is_empty());
    }

    #[test]
    fn test_remove_dev_flag_wrong_list_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("devwrong");
        // numpy is in packages, not dev_packages — removing with --dev should fail
        let result = run("numpy".to_string(), "default".to_string(), true);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
