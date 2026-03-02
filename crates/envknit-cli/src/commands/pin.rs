use crate::config::Config;
use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

/// Pin packages in config to the exact versions currently resolved in the lock file.
/// Only packages already listed in the config are pinned (no new packages added).
pub fn run(env: String, package: Option<String>) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found.")?;
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;

    let mut config = Config::load(&config_path)?;
    let lock = LockFile::load(&lock_path)?;

    let env_config = config.environments.get_mut(&env)
        .with_context(|| format!("Environment '{}' not found in config", env))?;

    let locked_pkgs = lock.packages_for_env(&env);
    let locked_map: std::collections::HashMap<String, &str> = locked_pkgs
        .iter()
        .map(|p| (p.name.to_lowercase(), p.version.as_str()))
        .collect();

    let mut pinned = 0usize;

    for spec in env_config.packages.iter_mut().chain(env_config.dev_packages.iter_mut()) {
        if let Some(ref filter) = package {
            if !spec.name.eq_ignore_ascii_case(filter) {
                continue;
            }
        }
        if let Some(&ver) = locked_map.get(&spec.name.to_lowercase()) {
            let pin = format!("=={}", ver);
            if spec.version.as_deref() != Some(&pin) {
                spec.version = Some(pin);
                println!("  {} {}=={}", "pinned".green(), spec.name, ver);
                pinned += 1;
            }
        }
    }

    if pinned == 0 {
        println!("{} Nothing to pin (all packages already pinned or not in lock)", "·".yellow());
        return Ok(());
    }

    config.save(&config_path)?;
    println!("{} Pinned {} package(s) in {}", "✓".green(), pinned, env);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::{add, init, lock};
    use crate::config::Config;
    use crate::lockfile::{LockedPackage, LockFile, LOCK_SCHEMA_VERSION};
    use std::collections::HashMap;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_pin_{}_{}_{label}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn write_lock_with_version(dir: &std::path::Path, pkg_name: &str, version: &str) {
        let mut envs = HashMap::new();
        envs.insert("default".to_string(), vec![LockedPackage {
            name: pkg_name.to_string(),
            version: version.to_string(),
            install_path: None,
            backend: None,
            dependencies: vec![],
            dev: false,
        }]);
        let lock = LockFile {
            schema_version: LOCK_SCHEMA_VERSION.to_string(),
            lock_generated_at: None,
            resolver_version: None,
            packages: vec![],
            environments: envs,
        };
        lock.save(&dir.join(crate::lockfile::LOCK_FILE)).unwrap();
    }

    #[test]
    fn test_pin_sets_exact_version() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("p");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        add::run("numpy".to_string(), "default".to_string(), None, false).unwrap();
        write_lock_with_version(&dir, "numpy", "1.26.4");
        run("default".to_string(), None).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        let ver = cfg.environments["default"].packages[0].version.as_deref();
        assert_eq!(ver, Some("==1.26.4"));
    }

    #[test]
    fn test_pin_specific_package() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("sp");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        add::run("numpy".to_string(), "default".to_string(), None, false).unwrap();
        add::run("click".to_string(), "default".to_string(), None, false).unwrap();
        // Write lock with both packages
        let mut envs = HashMap::new();
        envs.insert("default".to_string(), vec![
            LockedPackage { name: "numpy".to_string(), version: "1.26.4".to_string(), install_path: None, backend: None, dependencies: vec![], dev: false },
            LockedPackage { name: "click".to_string(), version: "8.1.7".to_string(), install_path: None, backend: None, dependencies: vec![], dev: false },
        ]);
        let lock = LockFile { schema_version: LOCK_SCHEMA_VERSION.to_string(), lock_generated_at: None, resolver_version: None, packages: vec![], environments: envs };
        lock.save(&dir.join(crate::lockfile::LOCK_FILE)).unwrap();
        run("default".to_string(), Some("numpy".to_string())).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        let numpy_ver = cfg.environments["default"].packages.iter().find(|p| p.name == "numpy").and_then(|p| p.version.as_deref());
        let click_ver = cfg.environments["default"].packages.iter().find(|p| p.name == "click").and_then(|p| p.version.as_deref());
        assert_eq!(numpy_ver, Some("==1.26.4"));
        assert!(click_ver.is_none()); // click was not pinned
    }

    #[test]
    fn test_pin_no_lock_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("nl");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        let result = run("default".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_pin_wrong_env_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("we");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        write_lock_with_version(&dir, "numpy", "1.26.4");
        let result = run("ml".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
