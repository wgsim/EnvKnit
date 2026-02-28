use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found.")?;
    let lock = LockFile::load(&lock_path)?;

    // Collect packages from requested env or all envs
    let all_pkgs: Vec<_> = if let Some(ref e) = env {
        lock.packages_for_env(e)
    } else if lock.environments.is_empty() {
        lock.packages.iter().collect()
    } else {
        lock.environments.values().flatten().collect()
    };

    let pkg_lower = package.to_lowercase();

    // Find the package itself
    let found = all_pkgs.iter().find(|p| p.name.to_lowercase() == pkg_lower);

    match found {
        None => {
            let env_desc = env.as_deref().unwrap_or("all environments");
            println!("{} '{}' not found in {}", "✗".red(), package, env_desc);
        }
        Some(pkg) => {
            let status = if pkg.install_path.is_some() { "installed".green() } else { "not installed".yellow() };
            println!("{} {} {} ({})", "✓".green(), pkg.name.bold(), pkg.version.green(), status);

            // Reverse deps: which packages list this one in their dependencies?
            let name_norm = pkg.name.to_lowercase();
            let dependers: Vec<_> = all_pkgs
                .iter()
                .filter(|p| p.name.to_lowercase() != pkg_lower)
                .filter(|p| p.dependencies.iter().any(|d| {
                    // dep strings may include version like "click>=8.0"; extract name part
                    let dep_name = d.split(|c: char| !c.is_alphanumeric() && c != '-' && c != '_').next().unwrap_or(d);
                    dep_name.to_lowercase() == name_norm
                }))
                .collect();

            if dependers.is_empty() {
                println!("  Required directly (top-level dependency)");
            } else {
                println!("  Required by:");
                for dep in &dependers {
                    println!("    · {}@{}", dep.name, dep.version);
                }
            }

            if !pkg.dependencies.is_empty() {
                println!("  Depends on:");
                for d in &pkg.dependencies {
                    println!("    · {}", d.dimmed());
                }
            }
        }
    }
    Ok(())
}
