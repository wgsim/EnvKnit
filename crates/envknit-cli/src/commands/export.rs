use crate::lockfile::LockFile;
use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::collections::HashSet;
use std::path::Path;

pub fn run(format: String, output: Option<String>) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found.")?;
    let lock = LockFile::load(&lock_path)?;

    // Collect unique packages across all environments (union, dedup by name+version)
    let mut seen: HashSet<String> = HashSet::new();
    let mut all_pkgs: Vec<_> = Vec::new();
    for pkg in lock.packages.iter() {
        let key = format!("{}=={}", pkg.name, pkg.version);
        if seen.insert(key) {
            all_pkgs.push(pkg);
        }
    }
    for env_pkgs in lock.environments.values() {
        for pkg in env_pkgs {
            let key = format!("{}=={}", pkg.name, pkg.version);
            if seen.insert(key) {
                all_pkgs.push(pkg);
            }
        }
    }

    if all_pkgs.is_empty() {
        eprintln!("{} No packages found in lock file.", "!".yellow());
    }

    let content = match format.as_str() {
        "requirements" => all_pkgs
            .iter()
            .map(|p| format!("{}=={}", p.name, p.version))
            .collect::<Vec<_>>()
            .join("\n"),
        "json" => serde_json::to_string_pretty(&all_pkgs)?,
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lockfile::{LockedPackage, LOCK_SCHEMA_VERSION};
    use std::collections::HashMap;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!("envknit_exp_{}_{}_{label}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().subsec_nanos()));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn mkpkg(name: &str, version: &str) -> LockedPackage {
        LockedPackage { name: name.to_string(), version: version.to_string(), install_path: None, backend: None, dependencies: vec![] }
    }

    fn write_lock(dir: &std::path::Path, envs: HashMap<String, Vec<LockedPackage>>) {
        let lock = LockFile { schema_version: LOCK_SCHEMA_VERSION.to_string(), lock_generated_at: None, resolver_version: None, packages: vec![], environments: envs };
        lock.save(&dir.join(crate::lockfile::LOCK_FILE)).unwrap();
    }

    #[test]
    fn test_export_requirements_format() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("r");
        let mut envs = HashMap::new();
        envs.insert("default".to_string(), vec![mkpkg("click", "8.3.1")]);
        write_lock(&dir, envs);
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let out = dir.join("out.txt");
        run("requirements".to_string(), Some(out.to_string_lossy().to_string())).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let content = fs::read_to_string(&out).unwrap();
        assert!(content.contains("click==8.3.1"));
    }

    #[test]
    fn test_export_json_format() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("j");
        let mut envs = HashMap::new();
        envs.insert("default".to_string(), vec![mkpkg("numpy", "1.26.4")]);
        write_lock(&dir, envs);
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let out = dir.join("out.json");
        run("json".to_string(), Some(out.to_string_lossy().to_string())).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let content = fs::read_to_string(&out).unwrap();
        assert!(content.contains("numpy") && content.contains("1.26.4"));
    }

    #[test]
    fn test_export_unknown_format_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("u");
        write_lock(&dir, HashMap::new());
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let result = run("pip".to_string(), None);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_export_dedup_across_envs() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("d");
        let pkg = mkpkg("shared", "1.0.0");
        let mut envs = HashMap::new();
        envs.insert("a".to_string(), vec![pkg.clone()]);
        envs.insert("b".to_string(), vec![pkg]);
        write_lock(&dir, envs);
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let out = dir.join("out.txt");
        run("requirements".to_string(), Some(out.to_string_lossy().to_string())).unwrap();
        std::env::set_current_dir(orig).unwrap();
        let content = fs::read_to_string(&out).unwrap();
        assert_eq!(content.matches("shared==1.0.0").count(), 1);
    }
}
