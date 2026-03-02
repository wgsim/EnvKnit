use crate::lockfile::LockFile;
use anyhow::{Context, Result};
use colored::Colorize;
use std::collections::HashMap;
use std::path::PathBuf;

pub fn run(base: String, head: String, env: Option<String>) -> Result<()> {
    let base_lock = LockFile::load(&PathBuf::from(&base))
        .with_context(|| format!("Failed to load base lock file: {}", base))?;
    let head_lock = LockFile::load(&PathBuf::from(&head))
        .with_context(|| format!("Failed to load head lock file: {}", head))?;

    println!("{}", "EnvKnit Diff".bold());
    println!("{}", "═".repeat(40));
    println!("  base: {}", base.dimmed());
    println!("  head: {}", head.dimmed());
    println!();

    // Determine which envs to compare
    let mut env_names: Vec<String> = if let Some(ref e) = env {
        vec![e.clone()]
    } else {
        let mut names: std::collections::HashSet<String> = std::collections::HashSet::new();
        names.extend(base_lock.environments.keys().cloned());
        names.extend(head_lock.environments.keys().cloned());
        let mut v: Vec<_> = names.into_iter().collect();
        v.sort();
        v
    };

    // Also compare top-level packages if no named envs
    if env_names.is_empty() {
        env_names.push("(packages)".to_string());
    }

    let mut any_diff = false;

    for env_name in &env_names {
        let base_pkgs: HashMap<String, String> = if env_name == "(packages)" {
            base_lock.packages.iter().map(|p| (p.name.to_lowercase(), p.version.clone())).collect()
        } else {
            base_lock.environments.get(env_name)
                .map(|pkgs| pkgs.iter().map(|p| (p.name.to_lowercase(), p.version.clone())).collect())
                .unwrap_or_default()
        };

        let head_pkgs: HashMap<String, String> = if env_name == "(packages)" {
            head_lock.packages.iter().map(|p| (p.name.to_lowercase(), p.version.clone())).collect()
        } else {
            head_lock.environments.get(env_name)
                .map(|pkgs| pkgs.iter().map(|p| (p.name.to_lowercase(), p.version.clone())).collect())
                .unwrap_or_default()
        };

        let mut added: Vec<(&str, &str)> = Vec::new();
        let mut removed: Vec<(&str, &str)> = Vec::new();
        let mut changed: Vec<(&str, &str, &str)> = Vec::new();

        for (name, head_ver) in &head_pkgs {
            match base_pkgs.get(name) {
                None => added.push((name, head_ver)),
                Some(base_ver) if base_ver != head_ver => changed.push((name, base_ver, head_ver)),
                _ => {}
            }
        }
        for (name, base_ver) in &base_pkgs {
            if !head_pkgs.contains_key(name) {
                removed.push((name, base_ver));
            }
        }

        added.sort_by_key(|(n, _)| *n);
        removed.sort_by_key(|(n, _)| *n);
        changed.sort_by_key(|(n, _, _)| *n);

        let env_has_diff = !added.is_empty() || !removed.is_empty() || !changed.is_empty();
        any_diff |= env_has_diff;

        println!("  {} {}", "▸".cyan(), env_name.bold());

        if !env_has_diff {
            println!("    {} no changes", "·".dimmed());
        }

        for (name, ver) in &added {
            println!("    {} {}=={}", "+".green().bold(), name, ver.green());
        }
        for (name, ver) in &removed {
            println!("    {} {}=={}", "-".red().bold(), name, ver.red());
        }
        for (name, base_ver, head_ver) in &changed {
            println!(
                "    {} {}  {} → {}",
                "~".yellow().bold(),
                name,
                base_ver.red(),
                head_ver.green()
            );
        }
        println!();
    }

    if !any_diff {
        println!("{} Lock files are identical.", "✓".green());
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lockfile::{LockedPackage, LOCK_SCHEMA_VERSION};
    use std::collections::HashMap;
    use std::fs;

    fn tmpdir(label: &str) -> PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_diff_{}_{}_{label}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&base).unwrap();
        base
    }

    fn mkpkg(name: &str, version: &str) -> LockedPackage {
        LockedPackage { name: name.to_string(), version: version.to_string(), install_path: None, backend: None, dependencies: vec![], dev: false }
    }

    fn write_lock(path: &PathBuf, envs: HashMap<String, Vec<LockedPackage>>) {
        let lock = LockFile {
            schema_version: LOCK_SCHEMA_VERSION.to_string(),
            lock_generated_at: None,
            resolver_version: None,
            packages: vec![],
            environments: envs,
        };
        lock.save(path).unwrap();
    }

    #[test]
    fn test_diff_identical_locks() {
        let dir = tmpdir("id");
        let mut envs = HashMap::new();
        envs.insert("default".to_string(), vec![mkpkg("numpy", "1.26.4")]);
        let p1 = dir.join("a.lock.yaml");
        let p2 = dir.join("b.lock.yaml");
        write_lock(&p1, envs.clone());
        write_lock(&p2, envs);
        let result = run(p1.to_string_lossy().into(), p2.to_string_lossy().into(), None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_diff_added_package() {
        let dir = tmpdir("add");
        let mut base_envs = HashMap::new();
        base_envs.insert("default".to_string(), vec![mkpkg("numpy", "1.26.4")]);
        let mut head_envs = HashMap::new();
        head_envs.insert("default".to_string(), vec![mkpkg("numpy", "1.26.4"), mkpkg("pandas", "2.0.0")]);
        let p1 = dir.join("base.lock.yaml");
        let p2 = dir.join("head.lock.yaml");
        write_lock(&p1, base_envs);
        write_lock(&p2, head_envs);
        let result = run(p1.to_string_lossy().into(), p2.to_string_lossy().into(), None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_diff_version_changed() {
        let dir = tmpdir("ver");
        let mut base_envs = HashMap::new();
        base_envs.insert("default".to_string(), vec![mkpkg("numpy", "1.24.0")]);
        let mut head_envs = HashMap::new();
        head_envs.insert("default".to_string(), vec![mkpkg("numpy", "1.26.4")]);
        let p1 = dir.join("base.lock.yaml");
        let p2 = dir.join("head.lock.yaml");
        write_lock(&p1, base_envs);
        write_lock(&p2, head_envs);
        let result = run(p1.to_string_lossy().into(), p2.to_string_lossy().into(), None);
        assert!(result.is_ok());
    }

    #[test]
    fn test_diff_missing_file_fails() {
        let result = run("/nonexistent/a.yaml".into(), "/nonexistent/b.yaml".into(), None);
        assert!(result.is_err());
    }
}
