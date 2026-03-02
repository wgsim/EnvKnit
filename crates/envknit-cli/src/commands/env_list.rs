use crate::lockfile::LockFile;
use anyhow::Result;
use colored::Colorize;
use std::path::Path;

pub fn run() -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .ok_or_else(|| anyhow::anyhow!("No envknit.lock.yaml found. Run `envknit lock` first."))?;
    let lock = LockFile::load(&lock_path)?;

    println!("{}", "Environments".bold());
    println!("{}", "═".repeat(40));

    if lock.environments.is_empty() {
        println!("  (no environments defined)");
        return Ok(());
    }

    let mut names: Vec<_> = lock.environments.keys().collect();
    names.sort();

    for name in names {
        let pkgs = &lock.environments[name];
        let installed = pkgs.iter().filter(|p| p.install_path.is_some()).count();
        println!(
            "  {} {}  ({} packages, {} installed)",
            "▸".cyan(),
            name.bold(),
            pkgs.len(),
            installed
        );
    }
    Ok(())
}
