use super::{run_command, Backend};
use anyhow::Result;

pub struct CondaBackend;

impl CondaBackend {
    pub fn new() -> Self { CondaBackend }
}

impl Backend for CondaBackend {
    fn name(&self) -> &str { "conda" }

    fn install(&self, package: &str, version: &str, env: &str) -> Result<()> {
        let spec = format!("{}={}", package, version);
        run_command("conda", &["install", "-n", env, &spec, "-y"])?;
        Ok(())
    }

    fn uninstall(&self, package: &str, env: &str) -> Result<()> {
        run_command("conda", &["remove", "-n", env, package, "-y"])?;
        Ok(())
    }

    fn list_versions(&self, package: &str) -> Result<Vec<String>> {
        let out = run_command("conda", &["search", package, "--json"])?;
        let json: serde_json::Value = serde_json::from_str(&out)?;
        Ok(json[package].as_array()
            .map(|arr| arr.iter()
                .filter_map(|v| v["version"].as_str().map(String::from))
                .collect())
            .unwrap_or_default())
    }
}
