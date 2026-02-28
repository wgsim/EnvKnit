use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(env: Option<String>, depth: usize) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let lock = LockFile::load(&lock_path)?;

    let env_name = env.as_deref().unwrap_or("default");
    let pkgs = lock.packages_for_env(env_name);

    println!("{} ({})", env_name.bold(), format!("{} packages", pkgs.len()).dimmed());
    let limit = if depth == 0 { pkgs.len() } else { depth * 10 };
    for pkg in pkgs.iter().take(limit) {
        println!("├── {}@{}", pkg.name.cyan(), pkg.version);
        for dep in &pkg.dependencies {
            println!("│   └── {}", dep.dimmed());
        }
    }
    Ok(())
}
