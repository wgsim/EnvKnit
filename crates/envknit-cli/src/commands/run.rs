use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use std::path::Path;

pub fn run(env: String, command: Vec<String>) -> Result<()> {
    if command.is_empty() {
        anyhow::bail!("No command specified. Usage: envknit run --env <env> -- <command> [args...]");
    }

    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock && envknit install` first.")?;
    let lock = LockFile::load(&lock_path)?;
    let pkgs = lock.packages_for_env(&env);

    let install_paths: Vec<String> = pkgs
        .iter()
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

    let (prog, args) = command.split_first().unwrap();
    let status = std::process::Command::new(prog)
        .args(args)
        .env("PYTHONPATH", &new_pythonpath)
        .status()
        .with_context(|| format!("Failed to run '{}'", prog))?;

    std::process::exit(status.code().unwrap_or(1));
}
