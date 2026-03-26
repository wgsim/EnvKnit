use crate::config::Config;
use crate::global_config::GlobalConfig;
use crate::lockfile::{LockedPackage, LockFile};
use crate::node_resolver;
use crate::process_util::wait_output_timeout;
use crate::python_resolver;
use crate::uv_resolver;
use anyhow::{Context, Result};
use colored::Colorize;
use rayon::prelude::*;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

pub fn run(env: Option<String>, no_dev: bool, auto_cleanup: bool) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let mut lock = LockFile::load(&lock_path)?;

    // uv is required for install (same as lock)
    uv_resolver::require_uv()?;
    let uv_path = uv_resolver::find_uv().expect("uv present after require_uv");

    // Load config to resolve python_version per environment (best-effort)
    let config = Config::find(Path::new(".")).and_then(|p| Config::load(&p).ok());
    let timeout = Duration::from_secs(
        GlobalConfig::load().unwrap_or_default().subprocess_timeout_secs
    );

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
        install_packages_mut(pkgs, "default", &uv_path, None, timeout)?;
    } else {
        for env_name in &envs_to_install {
            println!("  Environment: {}", env_name.bold());

            let python_path = resolve_python_for_env(env_name, &config);

            // Warn if node_version is configured but cannot be resolved (non-blocking)
            if let Some(env_cfg) = config.as_ref().and_then(|c| c.environments.get(env_name)) {
                if let Some(ref ver) = env_cfg.node_version {
                    if let Err(e) = node_resolver::resolve_node(ver) {
                        let system_ver = std::process::Command::new("node")
                            .arg("--version")
                            .output()
                            .ok()
                            .filter(|o| o.status.success())
                            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
                            .unwrap_or_else(|| "not found".to_string());
                        eprintln!(
                            "⚠ node_version '{}' could not be resolved: {}\n  \
                             Falling back to system node: {}\n  \
                             Install fnm or mise to enforce version isolation.",
                            ver, e, system_ver
                        );
                    }
                }
            }

            let pkgs: Vec<_> = lock
                .environments
                .get_mut(env_name)
                .map(|v| v.iter_mut().filter(|p| !no_dev || !p.dev).collect())
                .unwrap_or_default();
            install_packages_mut(pkgs, env_name, &uv_path, python_path, timeout)?;
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

/// Return the resolved Python interpreter path for an environment, if python_version is set.
/// Logs a warning and returns None on resolution failure.
fn resolve_python_for_env(env_name: &str, config: &Option<Config>) -> Option<PathBuf> {
    let ver = config
        .as_ref()
        .and_then(|c| c.environments.get(env_name))
        .and_then(|e| e.python_version.as_deref())?;

    match python_resolver::resolve_python(ver) {
        Ok(path) => {
            println!("  {} Using Python {} for env '{}'", "→".cyan(), ver, env_name);
            Some(path)
        }
        Err(e) => {
            eprintln!(
                "  {} Could not resolve Python {}: {} — falling back to uv default",
                "!".yellow(), ver, e
            );
            None
        }
    }
}

/// Install a batch of packages using `uv pip install --target`.
/// Already-cached packages are identified first, then new packages are installed in parallel.
fn install_packages_mut(
    mut packages: Vec<&mut LockedPackage>,
    _env_name: &str,
    uv_path: &Path,
    python_path: Option<PathBuf>,
    timeout: Duration,
) -> Result<()> {
    let global_cfg = GlobalConfig::load().unwrap_or_default();
    let store_base = global_cfg.effective_store_dir();
    rayon::ThreadPoolBuilder::new()
        .num_threads(global_cfg.parallel_jobs)
        .build_global()
        .unwrap_or(());
    std::fs::create_dir_all(&store_base)?;

    let mut to_install: Vec<(usize, String, String, PathBuf)> = Vec::new();

    for (i, pkg) in packages.iter().enumerate() {
        if pkg.install_path.is_some() {
            println!("    {} {}=={} (cached)", "→".cyan(), pkg.name, pkg.version);
            continue;
        }
        let install_dir = store_base
            .join(pkg.name.to_lowercase())
            .join(&pkg.version);
        to_install.push((i, pkg.name.clone(), pkg.version.clone(), install_dir));
    }

    let uv_path = uv_path.to_path_buf();
    let python_path = python_path.map(|p| p.to_string_lossy().into_owned());

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

            // uv pip install [--python <py>] --target <dir> <spec> --quiet
            let mut cmd = std::process::Command::new(&uv_path);
            cmd.args(["pip", "install"]);
            if let Some(ref py) = python_path {
                cmd.args(["--python", py]);
            }
            cmd.args(["--target", &install_dir.to_string_lossy(), &spec, "--quiet"])
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());

            let child = match cmd.spawn() {
                Err(e) => {
                    let _ = std::fs::remove_dir_all(&install_dir);
                    return (i, install_dir, Err(format!("uv exec failed: {}", e)));
                }
                Ok(c) => c,
            };

            match wait_output_timeout(child, timeout) {
                Err(e) => {
                    let _ = std::fs::remove_dir_all(&install_dir);
                    (i, install_dir, Err(e.to_string()))
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

    let mut first_err: Option<String> = None;
    for (i, install_dir, outcome) in results {
        let pkg = &mut packages[i];
        match outcome {
            Ok(()) => {
                let was_cached = install_dir.exists()
                    && pkg.install_path.is_none();
                pkg.install_path = Some(install_dir.to_string_lossy().to_string());
                pkg.sha256 = Some(hash_dir(&install_dir));
                if was_cached {
                    println!("    {} {}=={} (found at {:?})", "✓".green(), pkg.name, pkg.version, install_dir);
                } else {
                    println!("    {} {}=={} {}", "✓".green(), pkg.name, pkg.version, "installed".green());
                }
            }
            Err(e) => {
                println!("    {} {}=={} {}", "✗".red(), pkg.name, pkg.version, "FAILED".red());
                if first_err.is_none() {
                    first_err = Some(format!("uv pip install failed for {}=={}: {}", pkg.name, pkg.version, e));
                }
            }
        }
    }

    if let Some(err) = first_err {
        anyhow::bail!("{}", err);
    }

    Ok(())
}

/// Compute a deterministic SHA-256 of a directory tree.
pub fn hash_dir(dir: &PathBuf) -> String {
    let mut hasher = Sha256::new();
    let mut paths: Vec<PathBuf> = Vec::new();

    fn collect(dir: &Path, out: &mut Vec<PathBuf>) {
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.is_dir() {
                    collect(&p, out);
                } else {
                    out.push(p);
                }
            }
        }
    }

    collect(dir, &mut paths);
    paths.sort();

    for path in &paths {
        if let Ok(data) = std::fs::read(path) {
            hasher.update(path.to_string_lossy().as_bytes());
            hasher.update(&data);
        }
    }

    hex::encode(hasher.finalize())
}
