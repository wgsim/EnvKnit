use super::{run_command, Backend};
use anyhow::Result;

pub struct PoetryBackend;

impl PoetryBackend {
    pub fn new() -> Self { PoetryBackend }
}

impl Backend for PoetryBackend {
    fn name(&self) -> &str { "poetry" }

    fn install(&self, package: &str, version: &str, _env: &str) -> Result<()> {
        let spec = format!("{}@{}", package, version);
        run_command("poetry", &["add", &spec])?;
        Ok(())
    }

    fn uninstall(&self, package: &str, _env: &str) -> Result<()> {
        run_command("poetry", &["remove", package])?;
        Ok(())
    }

    fn list_versions(&self, package: &str) -> Result<Vec<String>> {
        let out = run_command("poetry", &["search", package, "--json"])?;
        let json: serde_json::Value = serde_json::from_str(&out)?;
        Ok(json.as_array()
            .map(|arr| arr.iter()
                .filter_map(|v| v["version"].as_str().map(String::from))
                .collect())
            .unwrap_or_default())
    }
}
