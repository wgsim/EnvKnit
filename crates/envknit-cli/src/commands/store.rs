use anyhow::Result;
use colored::Colorize;
use dirs_next::home_dir;
use std::collections::HashSet;
use std::path::{Path, PathBuf};

use crate::lockfile::LockFile;

fn store_base() -> Option<PathBuf> {
    home_dir().map(|h| h.join(".envknit").join("packages"))
}

fn dir_size(path: &Path) -> u64 {
    let Ok(entries) = std::fs::read_dir(path) else {
        return 0;
    };
    entries
        .flatten()
        .map(|e| {
            let p = e.path();
            if p.is_dir() {
                dir_size(&p)
            } else {
                p.metadata().map(|m| m.len()).unwrap_or(0)
            }
        })
        .sum()
}

fn format_size(bytes: u64) -> String {
    if bytes >= 1_000_000 {
        format!("{:.1} MB", bytes as f64 / 1_000_000.0)
    } else if bytes >= 1_000 {
        format!("{:.1} KB", bytes as f64 / 1_000.0)
    } else {
        format!("{} B", bytes)
    }
}

pub fn list(package: Option<String>) -> Result<()> {
    let base = match store_base() {
        Some(b) => b,
        None => {
            eprintln!("{}", "Cannot determine home directory.".red());
            return Ok(());
        }
    };

    if !base.exists() {
        println!("{}", "Store is empty (directory does not exist).".yellow());
        return Ok(());
    }

    // Collect (name, version, path) triples
    let mut entries: Vec<(String, String, PathBuf)> = Vec::new();

    let pkg_dirs = std::fs::read_dir(&base)?;
    for pkg_entry in pkg_dirs.flatten() {
        let pkg_name = pkg_entry.file_name().to_string_lossy().to_string();

        if let Some(ref filter) = package {
            if pkg_name != *filter {
                continue;
            }
        }

        let pkg_path = pkg_entry.path();
        if !pkg_path.is_dir() {
            continue;
        }

        let ver_dirs = std::fs::read_dir(&pkg_path)?;
        for ver_entry in ver_dirs.flatten() {
            let version = ver_entry.file_name().to_string_lossy().to_string();
            let ver_path = ver_entry.path();
            if ver_path.is_dir() {
                entries.push((pkg_name.clone(), version, ver_path));
            }
        }
    }

    entries.sort_by(|a, b| a.0.cmp(&b.0).then(a.1.cmp(&b.1)));

    let count = entries.len();
    let header = if let Some(ref filter) = package {
        format!(
            "~/.envknit/packages/{} ({} version{})",
            filter,
            count,
            if count == 1 { "" } else { "s" }
        )
    } else {
        // count unique package names
        let unique: HashSet<&str> = entries.iter().map(|(n, _, _)| n.as_str()).collect();
        format!(
            "~/.envknit/packages/ ({} package{})",
            unique.len(),
            if unique.len() == 1 { "" } else { "s" }
        )
    };

    println!("{}", header.bold());

    let name_width = entries.iter().map(|(n, _, _)| n.len()).max().unwrap_or(10);
    let ver_width = entries.iter().map(|(_, v, _)| v.len()).max().unwrap_or(8);

    for (name, version, path) in &entries {
        let display_path = path
            .to_string_lossy()
            .replace(&dirs_next::home_dir().unwrap_or_default().to_string_lossy().as_ref(), "~");
        println!(
            "  {:<name_width$}  {:<ver_width$}  {}",
            name.cyan(),
            version.green(),
            display_path.dimmed(),
            name_width = name_width,
            ver_width = ver_width,
        );
    }

    if entries.is_empty() {
        println!("  {}", "(no packages found)".dimmed());
    }

    Ok(())
}

pub fn stats() -> Result<()> {
    let base = match store_base() {
        Some(b) => b,
        None => {
            eprintln!("{}", "Cannot determine home directory.".red());
            return Ok(());
        }
    };

    let display_base = base
        .to_string_lossy()
        .replace(&dirs_next::home_dir().unwrap_or_default().to_string_lossy().as_ref(), "~");

    if !base.exists() {
        println!("{}", "EnvKnit Store Stats".bold());
        println!("{}", "═".repeat(40));
        println!("  {:<10} {}", "Location:".dimmed(), display_base);
        println!("  {:<10} {}", "Packages:".dimmed(), "0");
        println!("  {:<10} {}", "Versions:".dimmed(), "0");
        println!("  {:<10} {}", "Disk used:".dimmed(), "0 B");
        return Ok(());
    }

    let mut package_count = 0usize;
    let mut version_count = 0usize;
    let mut total_bytes = 0u64;

    let pkg_dirs = std::fs::read_dir(&base)?;
    for pkg_entry in pkg_dirs.flatten() {
        let pkg_path = pkg_entry.path();
        if !pkg_path.is_dir() {
            continue;
        }
        package_count += 1;

        let ver_dirs = std::fs::read_dir(&pkg_path)?;
        for ver_entry in ver_dirs.flatten() {
            let ver_path = ver_entry.path();
            if ver_path.is_dir() {
                version_count += 1;
                total_bytes += dir_size(&ver_path);
            }
        }
    }

    println!("{}", "EnvKnit Store Stats".bold());
    println!("{}", "═".repeat(40));
    println!("  {:<12} {}", "Location:".dimmed(), display_base);
    println!("  {:<12} {}", "Packages:".dimmed(), package_count);
    println!("  {:<12} {}", "Versions:".dimmed(), version_count);
    println!("  {:<12} {}", "Disk used:".dimmed(), format_size(total_bytes).cyan());

    Ok(())
}

pub fn cleanup(dry_run: bool) -> Result<()> {
    let base = match store_base() {
        Some(b) => b,
        None => {
            eprintln!("{}", "Cannot determine home directory.".red());
            return Ok(());
        }
    };

    if !base.exists() {
        println!("{}", "Store is empty — nothing to clean up.".yellow());
        return Ok(());
    }

    // Build set of referenced install_paths from lock file
    let lock_path = LockFile::find(Path::new("."));
    let referenced_paths: HashSet<String> = if let Some(ref lp) = lock_path {
        if let Ok(lock) = LockFile::load(lp) {
            let mut paths = HashSet::new();
            for pkg in lock.packages.iter() {
                if let Some(ref ip) = pkg.install_path {
                    paths.insert(ip.clone());
                }
            }
            for env_pkgs in lock.environments.values() {
                for pkg in env_pkgs {
                    if let Some(ref ip) = pkg.install_path {
                        paths.insert(ip.clone());
                    }
                }
            }
            paths
        } else {
            HashSet::new()
        }
    } else {
        HashSet::new()
    };

    if lock_path.is_none() {
        println!(
            "{}",
            "No lock file found in current directory tree — all store entries are unreferenced."
                .yellow()
        );
    }

    // Walk store and find unreferenced version dirs
    let mut candidates: Vec<PathBuf> = Vec::new();

    let pkg_dirs = std::fs::read_dir(&base)?;
    for pkg_entry in pkg_dirs.flatten() {
        let pkg_path = pkg_entry.path();
        if !pkg_path.is_dir() {
            continue;
        }

        let ver_dirs = std::fs::read_dir(&pkg_path)?;
        for ver_entry in ver_dirs.flatten() {
            let ver_path = ver_entry.path();
            if !ver_path.is_dir() {
                continue;
            }

            let ver_str = ver_path.to_string_lossy().to_string();
            if !referenced_paths.contains(&ver_str) {
                candidates.push(ver_path);
            }
        }
    }

    candidates.sort();

    if candidates.is_empty() {
        println!("{}", "Nothing to clean up — all versions are referenced.".green());
        return Ok(());
    }

    let home = dirs_next::home_dir().unwrap_or_default();
    let home_str = home.to_string_lossy().to_string();

    if dry_run {
        println!(
            "{} ({} director{})",
            "Dry run — would remove:".yellow().bold(),
            candidates.len(),
            if candidates.len() == 1 { "y" } else { "ies" }
        );
        for p in &candidates {
            let display = p.to_string_lossy().replace(&home_str, "~");
            println!("  {} {}", "–".red(), display);
        }
    } else {
        println!(
            "{} ({} director{})",
            "Removing unreferenced versions:".bold(),
            candidates.len(),
            if candidates.len() == 1 { "y" } else { "ies" }
        );
        for p in &candidates {
            let display = p.to_string_lossy().replace(&home_str, "~");
            match std::fs::remove_dir_all(p) {
                Ok(_) => println!("  {} {}", "removed".green(), display),
                Err(e) => println!("  {} {} ({})", "failed".red(), display, e),
            }
        }
    }

    Ok(())
}
