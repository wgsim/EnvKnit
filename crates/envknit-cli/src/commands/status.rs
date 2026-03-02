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
            let prod_pkgs: Vec<&crate::lockfile::LockedPackage> = pkgs.iter().copied().filter(|p| !p.dev).collect();
            let dev_pkgs: Vec<&crate::lockfile::LockedPackage> = pkgs.iter().copied().filter(|p| p.dev).collect();
            let installed = pkgs.iter().filter(|p| p.install_path.is_some()).count();

            println!(
                "  {} {} ({} packages, {} installed{})",
                "▸".cyan(),
                env_name.bold(),
                pkgs.len(),
                installed,
                if dev_pkgs.is_empty() { String::new() } else { format!(", {} dev", dev_pkgs.len()) },
            );

            let print_pkg_list = |list: &[&crate::lockfile::LockedPackage], limit: usize| {
                for pkg in list.iter().take(limit) {
                    let status = if pkg.install_path.is_some() { "✓".green() } else { "·".yellow() };
                    println!("    {} {}@{}", status, pkg.name, pkg.version.green());
                }
                if list.len() > limit {
                    println!("    {} ... and {} more", "·".dimmed(), list.len() - limit);
                }
            };

            print_pkg_list(&prod_pkgs, 10);

            if !dev_pkgs.is_empty() {
                println!("    {} dev dependencies:", "·".dimmed());
                print_pkg_list(&dev_pkgs, 5);
            }
        }
    }
    Ok(())
}
