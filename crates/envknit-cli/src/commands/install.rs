use crate::lockfile::{LockedPackage, LockFile};
use anyhow::{Context, Result};
use colored::Colorize;
use rayon::prelude::*;
use std::path::{Path, PathBuf};

pub fn run(env: Option<String>, no_dev: bool, auto_cleanup: bool) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let mut lock = LockFile::load(&lock_path)?;

    let env_display = env.as_deref().unwrap_or("all");
    println!(
        "{} Installing packages for environment: {}{}",
        "→".cyan(),
        env_display.bold(),
        if no_dev { " (no dev)" } else { "" }
    );

    let envs_to_install: Vec<String> = if let Some(ref e) = env {
        vec![e.clone()]
    } else {
        lock.environments.keys().cloned().collect()
    };

    if envs_to_install.is_empty() {
        let pkgs: Vec<_> = lock.packages.iter_mut()
            .filter(|p| !no_dev || !p.dev)
            .collect();
        install_packages_mut(pkgs, "default")?;
    } else {
        for env_name in &envs_to_install {
            println!("  Environment: {}", env_name.bold());
            let pkgs: Vec<_> = lock
                .environments
                .get_mut(env_name)
                .map(|v| v.iter_mut().filter(|p| !no_dev || !p.dev).collect())
                .unwrap_or_default();
            install_packages_mut(pkgs, env_name)?;
        }
    }

    lock.save(&lock_path)?;
    println!("{} Installation complete.", "✓".green());

    if auto_cleanup {
        println!("{} Running store cleanup...", "→".cyan());
        super::store::cleanup(false)?;
    }

    Ok(())
}

/// Install a batch of packages, running new installs in parallel via rayon.
/// Already-cached packages are identified first (sequential), then new packages
/// are installed concurrently.
fn install_packages_mut(mut packages: Vec<&mut LockedPackage>, _env_name: &str) -> Result<()> {
    let store_base = dirs_next::home_dir()
        .context("Cannot determine home directory")?
        .join(".envknit")
        .join("packages");
    std::fs::create_dir_all(&store_base)?;

    // Split into already-handled and needs-install
    let mut to_install: Vec<(usize, String, String, PathBuf)> = Vec::new();

    for (i, pkg) in packages.iter().enumerate() {
        if pkg.install_path.is_some() {
            println!("    {} {}=={} (cached)", "→".cyan(), pkg.name, pkg.version);
            continue;
        }
        let install_dir = store_base
            .join(pkg.name.to_lowercase())
            .join(&pkg.version);
        if install_dir.exists() {
            // Already on disk — just update path (done below after parallel phase)
        }
        to_install.push((i, pkg.name.clone(), pkg.version.clone(), install_dir));
    }

    // Parallel install: each entry is (index, name, version, dir)
    let results: Vec<(usize, PathBuf, Result<(), String>)> = to_install
        .into_par_iter()
        .map(|(i, name, version, install_dir)| {
            if install_dir.exists() {
                return (i, install_dir, Ok(()));
            }
            if let Err(e) = std::fs::create_dir_all(&install_dir) {
                return (i, install_dir, Err(e.to_string()));
            }

            let spec = format!("{}=={}", name, version);
            let output = std::process::Command::new("pip")
                .args(["install", "--target", &install_dir.to_string_lossy(), &spec, "--quiet"])
                .output();

            match output {
                Err(e) => {
                    let _ = std::fs::remove_dir_all(&install_dir);
                    (i, install_dir, Err(format!("pip exec failed: {}", e)))
                }
                Ok(out) if out.status.success() => (i, install_dir, Ok(())),
                Ok(out) => {
                    let _ = std::fs::remove_dir_all(&install_dir);
                    let stderr = String::from_utf8_lossy(&out.stderr).to_string();
                    (i, install_dir, Err(stderr))
                }
            }
        })
        .collect();

    // Apply results back to packages and report
    let mut first_err: Option<String> = None;
    for (i, install_dir, outcome) in results {
        let pkg = &mut packages[i];
        match outcome {
            Ok(()) => {
                pkg.install_path = Some(install_dir.to_string_lossy().to_string());
                let was_cached = install_dir.exists();
                if was_cached {
                    println!("    {} {}=={} (found at {:?})", "✓".green(), pkg.name, pkg.version, install_dir);
                } else {
                    println!("    {} {}=={} {}", "✓".green(), pkg.name, pkg.version, "installed".green());
                }
            }
            Err(e) => {
                println!("    {} {}=={} {}", "✗".red(), pkg.name, pkg.version, "FAILED".red());
                if first_err.is_none() {
                    first_err = Some(format!("pip install failed for {}=={}: {}", pkg.name, pkg.version, e));
                }
            }
        }
    }

    if let Some(err) = first_err {
        anyhow::bail!("{}", err);
    }

    Ok(())
}
