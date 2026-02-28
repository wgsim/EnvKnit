use crate::backends;
use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(env: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let lock = LockFile::load(&lock_path)?;

    let env_display = env.as_deref().unwrap_or("all");
    println!(
        "{} Installing packages for environment: {}",
        "→".cyan(),
        env_display.bold()
    );

    let envs_to_install: Vec<String> = if let Some(ref e) = env {
        vec![e.clone()]
    } else {
        lock.environments.keys().cloned().collect()
    };

    if envs_to_install.is_empty() {
        // Fall back to top-level packages list
        install_packages(&lock.packages, "default", None)?;
    } else {
        for env_name in &envs_to_install {
            let pkgs = lock.packages_for_env(env_name);
            println!("  Environment: {}", env_name.bold());
            install_packages(
                &pkgs.iter().map(|p| (*p).clone()).collect::<Vec<_>>(),
                env_name,
                None,
            )?;
        }
    }

    println!("{} Installation complete.", "✓".green());
    Ok(())
}

fn install_packages(
    packages: &[crate::lockfile::LockedPackage],
    env_name: &str,
    default_backend: Option<&str>,
) -> Result<()> {
    for pkg in packages {
        if pkg.install_path.is_some() {
            println!(
                "    {} {} {} (already installed at {})",
                "→".cyan(),
                pkg.name.bold(),
                pkg.version,
                pkg.install_path.as_deref().unwrap_or("")
            );
            continue;
        }

        let backend_name = pkg
            .backend
            .as_deref()
            .or(default_backend)
            .unwrap_or("pip");

        print!(
            "    {} {} {}=={} via {}...",
            "→".cyan(),
            "installing".dimmed(),
            pkg.name.bold(),
            pkg.version,
            backend_name
        );

        let backend = backends::get_backend(backend_name)
            .with_context(|| format!("Unknown backend '{}'", backend_name))?;

        match backend.install(&pkg.name, &pkg.version, env_name) {
            Ok(_) => println!(" {}", "done".green()),
            Err(e) => {
                println!(" {}", "FAILED".red());
                return Err(e).with_context(|| {
                    format!("Failed to install {}=={}", pkg.name, pkg.version)
                });
            }
        }
    }
    Ok(())
}
