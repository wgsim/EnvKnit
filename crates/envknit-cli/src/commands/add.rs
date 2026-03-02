use crate::config::{Config, EnvironmentConfig, PackageSpec};
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: String, _backend: Option<String>, dev: bool) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found. Run `envknit init` first.")?;

    let mut config = Config::load(&config_path)?;
    let env_config = config.environments.entry(env.clone())
        .or_insert_with(|| EnvironmentConfig { packages: vec![], dev_packages: vec![], backend: None, python_version: None });

    let spec = PackageSpec::parse(&package);
    let target = if dev { &mut env_config.dev_packages } else { &mut env_config.packages };
    if target.iter().any(|p| p.name == spec.name) {
        bail!("Package '{}' already in environment '{}'", spec.name, env);
    }

    let display = match &spec.version {
        Some(v) => format!("{}{}", spec.name, v),
        None => spec.name.clone(),
    };
    target.push(spec);
    config.save(&config_path)?;

    let kind = if dev { " [dev]" } else { "" };
    println!("{} Added '{}'{} to environment '{}'", "✓".green(), display, kind, env);
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
        let base = std::env::temp_dir().join(format!("envknit_add_{}_{}_{label}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().subsec_nanos()));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn setup(label: &str) -> (std::path::PathBuf, std::path::PathBuf) {
        let dir = tmpdir(label);
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        (dir, orig)
    }

    #[test]
    fn test_add_new_package() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup("n");
        run("numpy>=1.24".to_string(), "default".to_string(), None, false).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert_eq!(cfg.environments["default"].packages[0].name, "numpy");
        assert_eq!(cfg.environments["default"].packages[0].version.as_deref(), Some(">=1.24"));
    }

    #[test]
    fn test_add_without_version() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup("v");
        run("click".to_string(), "default".to_string(), None, false).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert_eq!(cfg.environments["default"].packages[0].name, "click");
        assert!(cfg.environments["default"].packages[0].version.is_none());
    }

    #[test]
    fn test_add_duplicate_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("d");
        run("click".to_string(), "default".to_string(), None, false).unwrap();
        let result = run("click".to_string(), "default".to_string(), None, false);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_add_dev_package() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup("dev");
        run("pytest".to_string(), "default".to_string(), None, true).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(cfg.environments["default"].packages.is_empty());
        assert_eq!(cfg.environments["default"].dev_packages[0].name, "pytest");
    }

    #[test]
    fn test_add_same_name_dev_and_prod_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup("devdup");
        run("click".to_string(), "default".to_string(), None, true).unwrap();
        let result = run("click".to_string(), "default".to_string(), None, true);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
