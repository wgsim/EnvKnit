use crate::config::{Config, EnvironmentConfig, PackageSpec};
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: String, _backend: Option<String>) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found. Run `envknit init` first.")?;

    let mut config = Config::load(&config_path)?;
    let env_config = config.environments.entry(env.clone())
        .or_insert_with(|| EnvironmentConfig { packages: vec![], backend: None, python_version: None });

    let spec = PackageSpec::parse(&package);
    if env_config.packages.iter().any(|p| p.name == spec.name) {
        bail!("Package '{}' already in environment '{}'", spec.name, env);
    }

    let display = match &spec.version {
        Some(v) => format!("{}{}", spec.name, v),
        None => spec.name.clone(),
    };
    env_config.packages.push(spec);
    config.save(&config_path)?;

    println!("{} Added '{}' to environment '{}'", "✓".green(), display, env);
    println!("  Run `envknit lock` to update the lock file");
    Ok(())
}
