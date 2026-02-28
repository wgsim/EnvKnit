use crate::lockfile::LockFile;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::collections::HashSet;
use std::path::Path;

pub fn run(format: String, output: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found.")?;
    let lock = LockFile::load(&lock_path)?;

    // Collect unique packages across all environments (union, dedup by name+version)
    let mut seen: HashSet<String> = HashSet::new();
    let mut all_pkgs: Vec<_> = Vec::new();
    for pkg in lock.packages.iter() {
        let key = format!("{}=={}", pkg.name, pkg.version);
        if seen.insert(key) {
            all_pkgs.push(pkg);
        }
    }
    for env_pkgs in lock.environments.values() {
        for pkg in env_pkgs {
            let key = format!("{}=={}", pkg.name, pkg.version);
            if seen.insert(key) {
                all_pkgs.push(pkg);
            }
        }
    }

    if all_pkgs.is_empty() {
        eprintln!("{} No packages found in lock file.", "!".yellow());
    }

    let content = match format.as_str() {
        "requirements" => all_pkgs
            .iter()
            .map(|p| format!("{}=={}", p.name, p.version))
            .collect::<Vec<_>>()
            .join("\n"),
        "json" => serde_json::to_string_pretty(&all_pkgs)?,
        _ => bail!("Unknown format '{}'. Supported: requirements, json", format),
    };

    match output {
        Some(ref path) => {
            std::fs::write(path, &content)?;
            println!("{} Written to {}", "✓".green(), path);
        }
        None => println!("{}", content),
    }
    Ok(())
}
