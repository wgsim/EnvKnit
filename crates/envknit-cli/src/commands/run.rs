use crate::config::Config;
use crate::lockfile::LockFile;
use crate::node_resolver;
use crate::python_resolver;
use anyhow::{Context, Result};
use std::path::Path;

pub fn run(env: String, command: Vec<String>, no_dev: bool) -> Result<()> {
    if command.is_empty() {
        anyhow::bail!("No command specified. Usage: envknit run --env <env> -- <command> [args...]");
    }

    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock && envknit install` first.")?;
    let lock = LockFile::load(&lock_path)?;
    let pkgs = lock.packages_for_env(&env);

    let install_paths: Vec<String> = pkgs
        .iter()
        .filter(|p| !no_dev || !p.dev)
        .filter_map(|p| p.install_path.clone())
        .collect();

    if install_paths.is_empty() {
        eprintln!(
            "warning: no packages installed for env '{}'. Run `envknit install` first.",
            env
        );
    }

    let existing_pythonpath = std::env::var("PYTHONPATH").unwrap_or_default();
    let new_pythonpath = if existing_pythonpath.is_empty() {
        install_paths.join(":")
    } else {
        format!("{}:{}", install_paths.join(":"), existing_pythonpath)
    };

    // Resolve python interpreter from python_version if set in config
    let python_path: Option<String> = Config::find(Path::new("."))
        .and_then(|p| Config::load(&p).ok())
        .and_then(|c| c.environments.get(&env).and_then(|e| e.python_version.clone()))
        .and_then(|ver| python_resolver::resolve_python(&ver).ok())
        .map(|p| p.to_string_lossy().to_string());

    // Resolve Node.js bin directory from node_version if set in config.
    // On failure: warn to stderr and continue (system node used as fallback).
    let node_bin: Option<std::path::PathBuf> = Config::find(std::path::Path::new("."))
        .and_then(|p| Config::load(&p).ok())
        .and_then(|c| c.environments.get(&env).and_then(|e| e.node_version.clone()))
        .and_then(|ver| match node_resolver::resolve_node(&ver) {
            Ok(node_path) => Some(node_resolver::node_bin_dir(&node_path)),
            Err(e) => {
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
                None
            }
        });

    let (prog, args) = command.split_first().unwrap();
    let mut cmd = std::process::Command::new(prog);
    cmd.args(args)
        .env("PYTHONPATH", &new_pythonpath)
        .env("ENVKNIT_ENV", &env);

    // Inject PYTHON and PYTHON3 so scripts can find the right interpreter
    if let Some(ref py) = python_path {
        cmd.env("PYTHON", py).env("PYTHON3", py);
    }

    // Prepend node bin dir to PATH so node/npm/npx resolve to the right version
    if let Some(ref bin_dir) = node_bin {
        let existing_path = std::env::var("PATH").unwrap_or_default();
        let sep = if cfg!(windows) { ";" } else { ":" };
        let new_path = format!("{}{}{}", bin_dir.to_string_lossy(), sep, existing_path);
        cmd.env("PATH", new_path);
    }

    let status = cmd
        .status()
        .with_context(|| format!("Failed to run '{}'", prog))?;

    std::process::exit(status.code().unwrap_or(1));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_run_missing_lock_errors() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = std::env::temp_dir().join(format!(
            "envknit_run_test_{}", std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let prev = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let result = run("default".to_string(), vec!["true".to_string()], false);
        std::env::set_current_dir(prev).unwrap();
        assert!(result.is_err(), "run without lock file should error");
    }
}
