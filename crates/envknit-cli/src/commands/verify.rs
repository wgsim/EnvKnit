use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

use super::install::hash_dir;

pub fn run(env: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found.")?;
    let lock = LockFile::load(&lock_path)?;

    println!("{}", "EnvKnit Verify".bold());
    println!("{}", "═".repeat(40));

    let env_names: Vec<String> = if let Some(ref e) = env {
        vec![e.clone()]
    } else if lock.environments.is_empty() {
        vec!["default".to_string()]
    } else {
        lock.environments.keys().cloned().collect()
    };

    let mut ok_count = 0usize;
    let mut fail_count = 0usize;
    let mut skip_count = 0usize;

    for env_name in &env_names {
        let pkgs = lock.packages_for_env(env_name);
        println!("  {} {}", "▸".cyan(), env_name.bold());

        for pkg in pkgs {
            let Some(ref install_path) = pkg.install_path else {
                println!("    {} {}=={} not installed", "·".dimmed(), pkg.name, pkg.version);
                skip_count += 1;
                continue;
            };

            let Some(ref recorded_hash) = pkg.sha256 else {
                println!(
                    "    {} {}=={} {} (no hash recorded — re-run `envknit install`)",
                    "!".yellow(), pkg.name, pkg.version, "skipped".yellow()
                );
                skip_count += 1;
                continue;
            };

            let dir = std::path::PathBuf::from(install_path);
            if !dir.exists() {
                println!(
                    "    {} {}=={} install directory missing: {}",
                    "✗".red(), pkg.name, pkg.version, install_path
                );
                fail_count += 1;
                continue;
            }

            let current_hash = hash_dir(&dir);
            if &current_hash == recorded_hash {
                println!("    {} {}=={}", "✓".green(), pkg.name, pkg.version);
                ok_count += 1;
            } else {
                println!(
                    "    {} {}=={} {} (expected {}, got {})",
                    "✗".red(),
                    pkg.name,
                    pkg.version,
                    "TAMPERED".red().bold(),
                    &recorded_hash[..12],
                    &current_hash[..12],
                );
                fail_count += 1;
            }
        }
    }

    println!();
    println!(
        "  {} ok, {} failed, {} skipped",
        ok_count.to_string().green(),
        fail_count.to_string().red(),
        skip_count.to_string().yellow(),
    );

    if fail_count > 0 {
        anyhow::bail!("{} package(s) failed integrity check", fail_count);
    }

    Ok(())
}
