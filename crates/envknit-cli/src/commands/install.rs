use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(env: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let mut lock = LockFile::load(&lock_path)?;

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
        install_packages(&mut lock.packages, "default")?;
    } else {
        for env_name in &envs_to_install {
            println!("  Environment: {}", env_name.bold());
            let pkgs = lock
                .environments
                .get_mut(env_name)
                .map(|v| v.as_mut_slice())
                .unwrap_or(&mut []);
            install_packages(pkgs, env_name)?;
        }
    }

    lock.save(&lock_path)?;
    println!("{} Installation complete.", "✓".green());
    Ok(())
}

fn install_packages(packages: &mut [crate::lockfile::LockedPackage], env_name: &str) -> Result<()> {
    let store_base = dirs_next::home_dir()
        .context("Cannot determine home directory")?
        .join(".envknit")
        .join("packages");
    std::fs::create_dir_all(&store_base)?;

    for pkg in packages.iter_mut() {
        if pkg.install_path.is_some() {
            println!(
                "    {} {}=={} (cached)",
                "→".cyan(),
                pkg.name,
                pkg.version
            );
            continue;
        }

        let install_dir = store_base
            .join(pkg.name.to_lowercase())
            .join(&pkg.version);

        if install_dir.exists() {
            pkg.install_path = Some(install_dir.to_string_lossy().to_string());
            println!(
                "    {} {}=={} (found at {:?})",
                "✓".green(),
                pkg.name,
                pkg.version,
                install_dir
            );
            continue;
        }

        std::fs::create_dir_all(&install_dir)?;

        let spec = format!("{}=={}", pkg.name, pkg.version);
        print!(
            "    {} {} {}...",
            "→".cyan(),
            "installing".dimmed(),
            spec.bold()
        );
        std::io::Write::flush(&mut std::io::stdout())?;

        let output = std::process::Command::new("pip")
            .args([
                "install",
                "--target",
                &install_dir.to_string_lossy(),
                &spec,
                "--quiet",
            ])
            .output()
            .context("Failed to run pip")?;

        if output.status.success() {
            pkg.install_path = Some(install_dir.to_string_lossy().to_string());
            println!(" {}", "done".green());
        } else {
            println!(" {}", "FAILED".red());
            // Clean up partial directory
            let _ = std::fs::remove_dir_all(&install_dir);
            let stderr = String::from_utf8_lossy(&output.stderr);
            anyhow::bail!("pip install failed for {}: {}", spec, stderr);
        }
    }

    let _ = env_name; // used in outer context for display only
    Ok(())
}
