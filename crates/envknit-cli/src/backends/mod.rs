pub mod conda;
pub mod pip;
pub mod poetry;

use anyhow::Result;

pub trait Backend {
    fn name(&self) -> &str;
    fn install(&self, package: &str, version: &str, env: &str) -> Result<()>;
    fn uninstall(&self, package: &str, env: &str) -> Result<()>;
    fn list_versions(&self, package: &str) -> Result<Vec<String>>;
}

pub fn get_backend(name: &str) -> Option<Box<dyn Backend>> {
    match name {
        "conda" => Some(Box::new(conda::CondaBackend::new())),
        "pip" => Some(Box::new(pip::PipBackend::new())),
        "poetry" => Some(Box::new(poetry::PoetryBackend::new())),
        _ => None,
    }
}

/// Run a subprocess command and return stdout
pub fn run_command(program: &str, args: &[&str]) -> Result<String> {
    let output = std::process::Command::new(program)
        .args(args)
        .output()?;
    if output.status.success() {
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    } else {
        anyhow::bail!(
            "{} failed: {}",
            program,
            String::from_utf8_lossy(&output.stderr)
        )
    }
}
