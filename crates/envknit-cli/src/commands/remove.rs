use crate::config::Config;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(package: String, env: String) -> Result<()> {
    let config_path = Config::find(Path::new("."))
        .context("No envknit.yaml found.")?;
    let mut config = Config::load(&config_path)?;

    let env_config = config.environments.get_mut(&env)
        .with_context(|| format!("Environment '{}' not found", env))?;

    let before = env_config.packages.len();
    env_config.packages.retain(|p| p.name != package);

    if env_config.packages.len() == before {
        bail!("Package '{}' not found in environment '{}'", package, env);
    }

    config.save(&config_path)?;
    println!("{} Removed '{}' from environment '{}'", "✓".green(), package, env);
    println!("  Run `envknit lock` to update the lock file");
    Ok(())
}
