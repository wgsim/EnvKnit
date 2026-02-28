use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found.")?;
    let lock = LockFile::load(&lock_path)?;

    let env_name = env.as_deref().unwrap_or("default");
    let pkgs = lock.packages_for_env(env_name);

    match pkgs.iter().find(|p| p.name.to_lowercase() == package.to_lowercase()) {
        Some(pkg) => {
            println!("{} {} {} is installed", "✓".green(), pkg.name.bold(), pkg.version.green());
            if pkg.dependencies.is_empty() {
                println!("  No recorded dependencies");
            } else {
                println!("  Depends on:");
                for dep in &pkg.dependencies {
                    println!("    · {}", dep);
                }
            }
        }
        None => println!("{} '{}' not found in environment '{}'", "✗".red(), package, env_name),
    }
    Ok(())
}
