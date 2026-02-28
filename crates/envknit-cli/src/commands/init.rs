use crate::config::{Config, EnvironmentConfig, CONFIG_FILE};
use anyhow::{bail, Result};
use colored::Colorize;
use std::collections::HashMap;
use std::path::Path;

pub fn run(env: String, backend: Option<String>) -> Result<()> {
    let config_path = Path::new(CONFIG_FILE);
    if config_path.exists() {
        bail!("{} already exists in current directory", CONFIG_FILE);
    }

    let mut environments = HashMap::new();
    environments.insert(env.clone(), EnvironmentConfig {
        packages: vec![],
        backend,
        python_version: None,
    });

    let config = Config {
        envknit_version: Some(env!("CARGO_PKG_VERSION").to_string()),
        environments,
    };

    config.save(config_path)?;
    println!("{} Initialized EnvKnit project (environment: '{}')", "✓".green(), env);
    println!("  Edit {} to add packages, then run `envknit lock`", CONFIG_FILE);
    Ok(())
}
