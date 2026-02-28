use super::{run_command, Backend};
use anyhow::Result;

pub struct PipBackend;

impl PipBackend {
    pub fn new() -> Self { PipBackend }
}

impl Backend for PipBackend {
    fn name(&self) -> &str { "pip" }

    fn install(&self, package: &str, version: &str, _env: &str) -> Result<()> {
        let spec = format!("{}=={}", package, version);
        run_command("pip", &["install", &spec])?;
        Ok(())
    }

    fn uninstall(&self, package: &str, _env: &str) -> Result<()> {
        run_command("pip", &["uninstall", package, "-y"])?;
        Ok(())
    }

    fn list_versions(&self, package: &str) -> Result<Vec<String>> {
        let out = run_command("pip", &["index", "versions", package])?;
        for line in out.lines() {
            if line.starts_with("Available versions:") {
                return Ok(line["Available versions:".len()..]
                    .split(',')
                    .map(|s| s.trim().to_string())
                    .collect());
            }
        }
        Ok(vec![])
    }
}
