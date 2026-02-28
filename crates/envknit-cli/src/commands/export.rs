use crate::lockfile::LockFile;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(format: String, output: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found.")?;
    let lock = LockFile::load(&lock_path)?;

    let content = match format.as_str() {
        "requirements" => lock.packages.iter()
            .map(|p| format!("{}=={}", p.name, p.version))
            .collect::<Vec<_>>()
            .join("\n"),
        "json" => serde_json::to_string_pretty(&lock.packages)?,
        _ => bail!("Unknown format '{}'. Supported: requirements, json", format),
    };

    match output {
        Some(ref path) => {
            std::fs::write(path, &content)?;
            println!("{} Written to {}", "✓".green(), path);
        }
        None => println!("{}", content),
    }
    Ok(())
}
