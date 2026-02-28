use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(env: Option<String>, depth: usize) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let lock = LockFile::load(&lock_path)?;

    let env_names: Vec<String> = if let Some(e) = env {
        vec![e]
    } else if lock.environments.is_empty() {
        vec![]
    } else {
        lock.environments.keys().cloned().collect()
    };

    if env_names.is_empty() {
        println!("No environments found in lock file.");
        return Ok(());
    }

    for env_name in &env_names {
        let pkgs = lock.packages_for_env(env_name);
        println!("{} ({})", env_name.bold(), format!("{} packages", pkgs.len()).dimmed());

        let count = pkgs.len();
        for (i, pkg) in pkgs.iter().enumerate() {
            let is_last = i == count - 1;
            let prefix = if is_last { "└──" } else { "├──" };
            let child_prefix = if is_last { "    " } else { "│   " };
            println!("{} {}@{}", prefix, pkg.name.cyan(), pkg.version);

            if depth > 1 {
                let dep_count = pkg.dependencies.len();
                for (j, dep) in pkg.dependencies.iter().enumerate() {
                    let dep_last = j == dep_count - 1;
                    let dep_prefix = if dep_last { "└──" } else { "├──" };
                    println!("{}  {} {}", child_prefix, dep_prefix, dep.dimmed());
                }
            }
        }
        println!();
    }
    Ok(())
}
