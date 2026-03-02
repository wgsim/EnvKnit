use crate::config::Config;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

/// Upgrade one or all packages in an environment.
///
/// Strategy:
///   - `==X.Y.Z`  pin → removed (unconstrained, pip will resolve latest)
///   - `>=X`, `~=X`, compound → kept as-is (already flexible)
///   - no version → no-op (already unconstrained)
///
/// After updating config, remind user to run `envknit lock && envknit install`.
pub fn run(package: Option<String>, env: String, version: Option<String>) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found. Run `envknit init` first.")?;
    let mut config = Config::load(&config_path)?;

    let env_config = config
        .environments
        .get_mut(&env)
        .with_context(|| format!("Environment '{}' not found", env))?;

    if env_config.packages.is_empty() {
        println!("{} No packages in environment '{}'", "!".yellow(), env);
        return Ok(());
    }

    let mut upgraded: Vec<String> = Vec::new();
    let mut skipped: Vec<String> = Vec::new();

    match package {
        Some(ref pkg_name) => {
            // Upgrade a single package
            let spec = env_config
                .packages
                .iter_mut()
                .find(|p| p.name == *pkg_name)
                .with_context(|| {
                    format!("Package '{}' not found in environment '{}'", pkg_name, env)
                })?;

            if let Some(ref new_ver) = version {
                // Pin to explicit version
                let old = spec.version.clone().unwrap_or_default();
                spec.version = Some(format!("=={}", new_ver));
                upgraded.push(format!("{}: {} → =={}", spec.name, old, new_ver));
            } else {
                match &spec.version {
                    None => {
                        skipped.push(format!("{} (already unconstrained)", spec.name));
                    }
                    Some(v) if v.starts_with("==") => {
                        let old = v.clone();
                        spec.version = None;
                        upgraded.push(format!("{}: {} → (latest)", spec.name, old));
                    }
                    Some(v) => {
                        skipped.push(format!("{} ({} — flexible constraint kept)", spec.name, v));
                    }
                }
            }
        }
        None => {
            // Upgrade all packages
            if version.is_some() {
                bail!("--version requires a specific package name");
            }
            for spec in env_config.packages.iter_mut() {
                match &spec.version {
                    None => {
                        skipped.push(format!("{} (already unconstrained)", spec.name));
                    }
                    Some(v) if v.starts_with("==") => {
                        let old = v.clone();
                        spec.version = None;
                        upgraded.push(format!("{}: {} → (latest)", spec.name, old));
                    }
                    Some(v) => {
                        skipped.push(format!("{} ({} — flexible constraint kept)", spec.name, v));
                    }
                }
            }
        }
    }

    if upgraded.is_empty() && skipped.is_empty() {
        println!("{} Nothing to upgrade", "!".yellow());
        return Ok(());
    }

    config.save(&config_path)?;

    for msg in &upgraded {
        println!("{} {}", "↑".green(), msg);
    }
    for msg in &skipped {
        println!("{} {}", "–".dimmed(), msg);
    }

    if !upgraded.is_empty() {
        println!();
        println!("  Run `envknit lock && envknit install` to apply upgrades");
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::{add, init};
    use crate::config::Config;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_upg_{}_{}_{label}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn setup_with_pkg(label: &str, pkg_spec: &str) -> (std::path::PathBuf, std::path::PathBuf) {
        let dir = tmpdir(label);
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        add::run(pkg_spec.to_string(), "default".to_string(), None, false).unwrap();
        (dir, orig)
    }

    #[test]
    fn test_upgrade_removes_exact_pin() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup_with_pkg("pin", "numpy==1.26.4");
        run(Some("numpy".to_string()), "default".to_string(), None).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert!(cfg.environments["default"].packages[0].version.is_none());
    }

    #[test]
    fn test_upgrade_keeps_flexible_constraint() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup_with_pkg("flex", "click>=8.0");
        run(Some("click".to_string()), "default".to_string(), None).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        // flexible constraint should be preserved
        assert_eq!(
            cfg.environments["default"].packages[0].version.as_deref(),
            Some(">=8.0")
        );
    }

    #[test]
    fn test_upgrade_to_explicit_version() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (dir, orig) = setup_with_pkg("explicit", "numpy==1.24.0");
        run(
            Some("numpy".to_string()),
            "default".to_string(),
            Some("2.0.0".to_string()),
        )
        .unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        assert_eq!(
            cfg.environments["default"].packages[0].version.as_deref(),
            Some("==2.0.0")
        );
    }

    #[test]
    fn test_upgrade_all_packages() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("all");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        add::run("numpy==1.24.0".to_string(), "default".to_string(), None, false).unwrap();
        add::run("click>=8.0".to_string(), "default".to_string(), None, false).unwrap();
        run(None, "default".to_string(), None).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let cfg = Config::load(&dir.join(crate::config::CONFIG_FILE)).unwrap();
        let pkgs = &cfg.environments["default"].packages;
        // numpy==1.24.0 pin removed
        let numpy = pkgs.iter().find(|p| p.name == "numpy").unwrap();
        assert!(numpy.version.is_none());
        // click>=8.0 kept
        let click = pkgs.iter().find(|p| p.name == "click").unwrap();
        assert_eq!(click.version.as_deref(), Some(">=8.0"));
    }

    #[test]
    fn test_upgrade_nonexistent_pkg_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup_with_pkg("nope", "numpy");
        let result = run(Some("pandas".to_string()), "default".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_upgrade_version_without_package_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let (_dir, orig) = setup_with_pkg("nopkg", "numpy==1.0.0");
        let result = run(None, "default".to_string(), Some("2.0.0".to_string()));
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }
}
