use crate::config::Config;
use crate::lockfile::{LockFile, LockedPackage, LOCK_FILE, LOCK_SCHEMA_VERSION};
use crate::resolver::Resolver;
use anyhow::{Context, Result};
use chrono::Utc;
use colored::Colorize;
use std::collections::HashMap;
use std::path::Path;

pub fn run(update: Option<String>, dry_run: bool) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found. Run `envknit init` first.")?;
    let config = Config::load(&config_path)?;

    if dry_run {
        println!("{} Dry run — resolving without writing lock file", "→".cyan());
    }
    if let Some(ref pkg) = update {
        println!("{} Updating package: {}", "→".cyan(), pkg.bold());
    }

    println!("{} Resolving dependencies...", "→".cyan());

    let mut env_packages: HashMap<String, Vec<LockedPackage>> = HashMap::new();

    for (env_name, env_config) in &config.environments {
        println!("  Environment: {}", env_name.bold());

        // If --update <pkg> filter to only that package in this env
        let specs: Vec<_> = if let Some(ref pkg) = update {
            env_config
                .packages
                .iter()
                .filter(|p| p.name.eq_ignore_ascii_case(pkg))
                .cloned()
                .collect()
        } else {
            env_config.packages.clone()
        };

        if specs.is_empty() {
            println!("    (no matching packages)");
            continue;
        }

        let resolver = Resolver::new(dry_run);
        let resolved = resolver.resolve(&specs)?;

        for pkg in &resolved {
            println!("    {} {} {}", "✓".green(), pkg.name.bold(), pkg.version);
        }

        env_packages.insert(env_name.clone(), resolved);
    }

    if dry_run {
        println!("{} Dry run complete — no files written.", "→".cyan());
        return Ok(());
    }

    let lock_path = config_path.parent().unwrap().join(LOCK_FILE);

    // If updating, merge with existing lock (keep other packages unchanged)
    let mut lock = if update.is_some() && lock_path.exists() {
        LockFile::load(&lock_path).unwrap_or_else(|_| new_lockfile())
    } else {
        new_lockfile()
    };

    for (env_name, new_pkgs) in env_packages {
        let env_entry = lock.environments.entry(env_name).or_default();
        for new_pkg in new_pkgs {
            if let Some(existing) = env_entry.iter_mut().find(|p| p.name == new_pkg.name) {
                *existing = new_pkg;
            } else {
                env_entry.push(new_pkg);
            }
        }
    }

    lock.lock_generated_at = Some(Utc::now().to_rfc3339());
    lock.save(&lock_path)?;

    println!("{} Lock file written: {}", "✓".green(), lock_path.display());
    println!("  Run `envknit install` to install packages to ~/.envknit/packages/");
    Ok(())
}

fn new_lockfile() -> LockFile {
    LockFile {
        schema_version: LOCK_SCHEMA_VERSION.to_string(),
        lock_generated_at: None,
        resolver_version: Some(env!("CARGO_PKG_VERSION").to_string()),
        packages: vec![],
        environments: HashMap::new(),
    }
}
