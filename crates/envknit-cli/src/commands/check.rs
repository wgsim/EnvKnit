use crate::config::Config;
use crate::lockfile::LockFile;
use crate::node_resolver;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

/// Exit code conventions:
///   0 = clean
///   1 = drift detected (anyhow::bail!)
pub fn run() -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found.")?;
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;

    let config = Config::load(&config_path)?;
    let lock = LockFile::load(&lock_path)?;

    println!("{}", "EnvKnit Check".bold());
    println!("{}", "═".repeat(40));

    let mut issues: Vec<String> = Vec::new();

    // 1. Environments in config but missing from lock
    for env_name in config.environments.keys() {
        if !lock.environments.contains_key(env_name) {
            issues.push(format!(
                "Environment '{}' is in config but missing from lock file",
                env_name
            ));
        }
    }

    // 2. Environments in lock but not in config (stale)
    for env_name in lock.environments.keys() {
        if !config.environments.contains_key(env_name) {
            issues.push(format!(
                "Environment '{}' is in lock file but not in config (stale)",
                env_name
            ));
        }
    }

    // 3. Per-environment: packages in config not present in lock
    for (env_name, env_config) in &config.environments {
        let locked_pkgs = lock.packages_for_env(env_name);
        let locked_names: std::collections::HashSet<String> = locked_pkgs
            .iter()
            .map(|p| p.name.to_lowercase())
            .collect();

        for spec in env_config.packages.iter().chain(env_config.dev_packages.iter()) {
            if !locked_names.contains(&spec.name.to_lowercase()) {
                issues.push(format!(
                    "[{}] '{}' is in config but not in lock file (run `envknit lock`)",
                    env_name, spec.name
                ));
            }
        }
    }

    let mut warnings: Vec<String> = Vec::new();

    // node_version resolution check (Warn, not Fail)
    for (env_name, env_cfg) in &config.environments {
        if let Some(ref ver) = env_cfg.node_version {
            if node_resolver::resolve_node(ver).is_err() {
                warnings.push(format!(
                    "[{}] node_version '{}' could not be resolved (install fnm/mise)",
                    env_name, ver
                ));
            }
        }
    }

    if issues.is_empty() {
        println!("  {} Config and lock file are in sync.", "✓".green());
        for w in &warnings {
            println!("  {} {}", "!".yellow(), w);
        }
        Ok(())
    } else {
        for issue in &issues {
            println!("  {} {}", "✗".red(), issue);
        }
        for w in &warnings {
            println!("  {} {}", "!".yellow(), w);
        }
        println!();
        anyhow::bail!(
            "{} issue(s) found — run `envknit lock` to fix",
            issues.len()
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::{add, init, lock};
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_check_{}_{}_{label}",
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
    fn test_check_passes_when_no_packages() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("ok");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        lock::run(None, false, None).unwrap();
        let result = run();
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_ok());
    }

    #[test]
    fn test_check_fails_when_lock_missing_env() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("me");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        // Write an empty lock (no environments)
        let lock = crate::lockfile::LockFile {
            schema_version: crate::lockfile::LOCK_SCHEMA_VERSION.to_string(),
            lock_generated_at: None,
            resolver_version: None,
            packages: vec![],
            environments: std::collections::HashMap::new(),
        };
        lock.save(&dir.join(crate::lockfile::LOCK_FILE)).unwrap();
        let result = run();
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_check_fails_when_package_not_in_lock() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("pkg");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        lock::run(None, false, None).unwrap();
        // Add package to config AFTER locking — creates drift
        add::run("requests".to_string(), "default".to_string(), None, false).unwrap();
        let result = run();
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_check_fails_when_no_lock_file() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("nl");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        init::run("default".to_string(), None).unwrap();
        let result = run();
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_check_warns_on_unresolvable_node_version() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = std::env::temp_dir().join(format!(
            "envknit_check_node_test_{}", std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let yaml = "environments:\n  default:\n    node_version: '99.99.99'\n    packages: []\n";
        std::fs::write(dir.join("envknit.yaml"), yaml).unwrap();
        let lock_yaml = "schema_version: '1.0'\nlock_generated_at: '2026-01-01T00:00:00+00:00'\nresolver_version: '0.1.0'\nenvironments:\n  default: []\n";
        std::fs::write(dir.join("envknit.lock.yaml"), lock_yaml).unwrap();
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let result = run();
        std::env::set_current_dir(orig).unwrap();
        // check should pass (exit 0) — node_version failure is a Warn, not Fail
        assert!(result.is_ok(), "unresolvable node_version should be Warn not Fail in check: {:?}", result);
    }
}
