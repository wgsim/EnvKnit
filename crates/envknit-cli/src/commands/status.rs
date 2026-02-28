use crate::config::Config;
use crate::lockfile::LockFile;
use anyhow::Result;
use colored::Colorize;
use std::path::Path;

pub fn run(env: Option<String>) -> Result<()> {
    let config_path = Config::find(Path::new("."));
    let lock_path = LockFile::find(Path::new("."));

    println!("{}", "EnvKnit Status".bold());
    println!("{}", "═".repeat(40));

    match &config_path {
        Some(p) => println!("  Config:    {} {}", "✓".green(), p.display()),
        None    => println!("  Config:    {} not found", "✗".red()),
    }
    match &lock_path {
        Some(p) => println!("  Lock file: {} {}", "✓".green(), p.display()),
        None    => println!("  Lock file: {} not found (run `envknit lock`)", "✗".yellow()),
    }

    if let Some(lock_path) = &lock_path {
        let lock = LockFile::load(lock_path)?;
        let env_names: Vec<String> = if let Some(ref e) = env {
            vec![e.clone()]
        } else if lock.environments.is_empty() {
            vec!["default".to_string()]
        } else {
            lock.environments.keys().cloned().collect()
        };

        println!();
        for env_name in &env_names {
            let pkgs = lock.packages_for_env(env_name);
            println!("  {} {} ({} packages)", "▸".cyan(), env_name.bold(), pkgs.len());
            for pkg in pkgs.iter().take(10) {
                println!("    {} {}@{}", "·".dimmed(), pkg.name, pkg.version.green());
            }
            if pkgs.len() > 10 {
                println!("    {} ... and {} more", "·".dimmed(), pkgs.len() - 10);
            }
        }
    }
    Ok(())
}
