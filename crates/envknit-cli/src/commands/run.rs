use crate::config::Config;
use crate::lockfile::LockFile;
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

    let (prog, args) = command.split_first().unwrap();
    let mut cmd = std::process::Command::new(prog);
    cmd.args(args)
        .env("PYTHONPATH", &new_pythonpath)
        .env("ENVKNIT_ENV", &env);

    // Inject PYTHON and PYTHON3 so scripts can find the right interpreter
    if let Some(ref py) = python_path {
        cmd.env("PYTHON", py).env("PYTHON3", py);
    }

    let status = cmd
        .status()
        .with_context(|| format!("Failed to run '{}'", prog))?;

    std::process::exit(status.code().unwrap_or(1));
}
