use crate::lockfile::{LockFile, LockedPackage};
use anyhow::{Context, Result};
use colored::Colorize;
use std::collections::HashMap;
use std::path::Path;

pub fn run(env: Option<String>, json: bool, depth: usize) -> Result<()> {
    let lock_path = LockFile::find(Path::new("."))
        .context("No envknit.lock.yaml found. Run `envknit lock` first.")?;
    let lock = LockFile::load(&lock_path)?;

    let env_names: Vec<String> = if let Some(e) = env {
        vec![e]
    } else if lock.environments.is_empty() {
        vec![]
    } else {
        lock.environments.keys().cloned().collect()
    };

    if env_names.is_empty() {
        println!("No environments found in lock file.");
        return Ok(());
    }

    if json {
        render_json(&lock, &env_names)?;
    } else {
        render_ascii(&lock, &env_names, depth);
    }
    Ok(())
}

fn render_ascii(lock: &LockFile, env_names: &[String], max_depth: usize) {
    for env_name in env_names {
        let pkgs = lock.packages_for_env(env_name);
        let pkg_map: HashMap<String, &LockedPackage> = pkgs
            .iter()
            .map(|p| (p.name.to_lowercase(), *p))
            .collect();

        println!("{}", env_name.bold());
        let count = pkgs.len();
        for (i, pkg) in pkgs.iter().enumerate() {
            let is_last = i == count - 1;
            render_pkg(pkg, &pkg_map, is_last, "", 0, max_depth);
        }
        println!();
    }
}

fn render_pkg(
    pkg: &LockedPackage,
    pkg_map: &HashMap<String, &LockedPackage>,
    is_last: bool,
    prefix: &str,
    depth: usize,
    max_depth: usize,
) {
    let connector = if is_last { "└──" } else { "├──" };
    let status = if pkg.install_path.is_some() {
        "✓".green()
    } else {
        "·".yellow()
    };
    println!(
        "{}{} {}@{} {}",
        prefix,
        connector,
        pkg.name.cyan(),
        pkg.version,
        status
    );

    if max_depth == 0 || depth < max_depth {
        let child_prefix = format!("{}{}", prefix, if is_last { "    " } else { "│   " });
        let dep_count = pkg.dependencies.len();
        for (j, dep_name) in pkg.dependencies.iter().enumerate() {
            let dep_name_norm = dep_name
                .to_lowercase()
                .split(|c: char| !c.is_alphanumeric() && c != '-' && c != '_')
                .next()
                .unwrap_or(dep_name)
                .to_string();
            let dep_last = j == dep_count - 1;
            if let Some(dep_pkg) = pkg_map.get(&dep_name_norm) {
                render_pkg(dep_pkg, pkg_map, dep_last, &child_prefix, depth + 1, max_depth);
            } else {
                let connector2 = if dep_last { "└──" } else { "├──" };
                println!("{}{} {}", child_prefix, connector2, dep_name.dimmed());
            }
        }
    }
}

fn render_json(lock: &LockFile, env_names: &[String]) -> Result<()> {
    #[derive(serde::Serialize)]
    struct DepNode {
        name: String,
        version: String,
        installed: bool,
    }

    #[derive(serde::Serialize)]
    struct PkgNode {
        name: String,
        version: String,
        installed: bool,
        dependencies: Vec<DepNode>,
    }

    #[derive(serde::Serialize)]
    struct EnvGraph {
        env: String,
        packages: Vec<PkgNode>,
    }

    let mut output: Vec<EnvGraph> = Vec::new();

    for env_name in env_names {
        let pkgs = lock.packages_for_env(env_name);
        let pkg_map: HashMap<String, &LockedPackage> = pkgs
            .iter()
            .map(|p| (p.name.to_lowercase(), *p))
            .collect();

        let packages: Vec<PkgNode> = pkgs
            .iter()
            .map(|pkg| {
                let dependencies: Vec<DepNode> = pkg
                    .dependencies
                    .iter()
                    .filter_map(|dep_name| {
                        let norm = dep_name
                            .to_lowercase()
                            .split(|c: char| !c.is_alphanumeric() && c != '-' && c != '_')
                            .next()
                            .unwrap_or(dep_name)
                            .to_string();
                        pkg_map.get(&norm).map(|dep_pkg| DepNode {
                            name: dep_pkg.name.clone(),
                            version: dep_pkg.version.clone(),
                            installed: dep_pkg.install_path.is_some(),
                        })
                    })
                    .collect();
                PkgNode {
                    name: pkg.name.clone(),
                    version: pkg.version.clone(),
                    installed: pkg.install_path.is_some(),
                    dependencies,
                }
            })
            .collect();

        output.push(EnvGraph {
            env: env_name.clone(),
            packages,
        });
    }

    // Single env: unwrap to object; multiple envs: output array
    if output.len() == 1 {
        println!("{}", serde_json::to_string_pretty(&output[0])?);
    } else {
        println!("{}", serde_json::to_string_pretty(&output)?);
    }
    Ok(())
}
