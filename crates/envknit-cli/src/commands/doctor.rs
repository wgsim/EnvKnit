use crate::config::Config;
use crate::lockfile::LockFile;
use anyhow::Result;
use colored::Colorize;
use std::path::Path;
use std::process::Command;

struct Check {
    label: &'static str,
    status: Status,
    detail: String,
}

enum Status {
    Ok,
    Warn,
    Fail,
}

impl Check {
    fn ok(label: &'static str, detail: impl Into<String>) -> Self {
        Check { label, status: Status::Ok, detail: detail.into() }
    }
    fn warn(label: &'static str, detail: impl Into<String>) -> Self {
        Check { label, status: Status::Warn, detail: detail.into() }
    }
    fn fail(label: &'static str, detail: impl Into<String>) -> Self {
        Check { label, status: Status::Fail, detail: detail.into() }
    }
}

fn run_version(cmd: &str, args: &[&str]) -> Option<String> {
    Command::new(cmd)
        .args(args)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
}

fn which(cmd: &str) -> Option<String> {
    Command::new("which")
        .arg(cmd)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
}

pub fn run() -> Result<()> {
    println!("{}", "EnvKnit Doctor".bold());
    println!("{}", "═".repeat(40));
    println!();

    let mut checks: Vec<Check> = Vec::new();
    let mut fail_count = 0usize;
    let mut warn_count = 0usize;

    // --- envknit version ---
    checks.push(Check::ok("envknit", format!("v{}", env!("CARGO_PKG_VERSION"))));

    // --- pip ---
    match run_version("pip", &["--version"]) {
        Some(v) => {
            let short = v.lines().next().unwrap_or(&v).to_string();
            checks.push(Check::ok("pip", short));
        }
        None => match run_version("pip3", &["--version"]) {
            Some(v) => {
                let short = v.lines().next().unwrap_or(&v).to_string();
                checks.push(Check::warn("pip", format!("pip not found, using pip3: {}", short)));
            }
            None => {
                checks.push(Check::fail("pip", "pip not found — install pip to use `envknit install`"));
            }
        },
    }

    // --- python ---
    match run_version("python3", &["--version"]) {
        Some(v) => checks.push(Check::ok("python", v)),
        None => match run_version("python", &["--version"]) {
            Some(v) => checks.push(Check::warn("python", format!("python3 not found, using python: {}", v))),
            None => checks.push(Check::fail("python", "python not found")),
        },
    }

    // --- pyenv ---
    match run_version("pyenv", &["--version"]) {
        Some(v) => checks.push(Check::ok("pyenv", v)),
        None => checks.push(Check::warn("pyenv", "not installed (optional — needed for python_version management)")),
    }

    // --- mise ---
    match run_version("mise", &["--version"]) {
        Some(v) => checks.push(Check::ok("mise", v)),
        None => checks.push(Check::warn("mise", "not installed (optional — alternative to pyenv)")),
    }

    // --- ~/.envknit directory ---
    let envknit_dir = dirs_next::home_dir()
        .map(|h| h.join(".envknit"))
        .unwrap_or_else(|| Path::new(".envknit").to_path_buf());

    if envknit_dir.exists() {
        let packages_dir = envknit_dir.join("packages");
        let cache_dir = envknit_dir.join("cache");
        let mut parts = vec!["exists".to_string()];
        if packages_dir.exists() { parts.push("packages/".to_string()); }
        if cache_dir.exists() { parts.push("cache/".to_string()); }
        checks.push(Check::ok("~/.envknit", parts.join(", ")));
    } else {
        checks.push(Check::warn("~/.envknit", "directory not yet created (run `envknit install` first)"));
    }

    // --- config file ---
    match Config::find(Path::new(".")) {
        Some(p) => {
            match Config::load(&p) {
                Ok(cfg) => {
                    let env_count = cfg.environments.len();
                    checks.push(Check::ok(
                        "config",
                        format!("{} ({} environment{})", p.display(), env_count, if env_count == 1 { "" } else { "s" }),
                    ));
                }
                Err(e) => checks.push(Check::fail("config", format!("{} — parse error: {}", p.display(), e))),
            }
        }
        None => checks.push(Check::warn("config", "no envknit.yaml found in current directory tree")),
    }

    // --- lock file ---
    match LockFile::find(Path::new(".")) {
        Some(p) => {
            match LockFile::load(&p) {
                Ok(lock) => {
                    let env_count = lock.environments.len();
                    checks.push(Check::ok(
                        "lock file",
                        format!("{} ({} environment{})", p.display(), env_count, if env_count == 1 { "" } else { "s" }),
                    ));
                }
                Err(e) => checks.push(Check::fail("lock file", format!("{} — parse error: {}", p.display(), e))),
            }
        }
        None => checks.push(Check::warn("lock file", "no lock file found — run `envknit lock`")),
    }

    // --- PYTHONPATH conflicts ---
    match std::env::var("PYTHONPATH") {
        Ok(pp) if !pp.is_empty() => {
            checks.push(Check::warn(
                "PYTHONPATH",
                format!("already set: {} — may conflict with envknit-managed paths", pp),
            ));
        }
        _ => checks.push(Check::ok("PYTHONPATH", "not set (clean)")),
    }

    // --- git (optional) ---
    match which("git") {
        Some(p) => checks.push(Check::ok("git", p)),
        None => checks.push(Check::warn("git", "not found (optional)")),
    }

    // Print results
    for check in &checks {
        let (icon, label_colored) = match check.status {
            Status::Ok => ("✓".green(), check.label.normal()),
            Status::Warn => {
                warn_count += 1;
                ("!".yellow(), check.label.yellow())
            }
            Status::Fail => {
                fail_count += 1;
                ("✗".red(), check.label.red())
            }
        };
        println!(
            "  {} {:<14} {}",
            icon,
            label_colored,
            check.detail.dimmed()
        );
    }

    println!();

    if fail_count > 0 {
        println!(
            "  {} {} failure(s), {} warning(s)",
            "✗".red().bold(),
            fail_count,
            warn_count
        );
        anyhow::bail!("doctor found {} critical issue(s)", fail_count);
    } else if warn_count > 0 {
        println!(
            "  {} All critical checks passed ({} warning{})",
            "!".yellow().bold(),
            warn_count,
            if warn_count == 1 { "" } else { "s" }
        );
    } else {
        println!("  {} All checks passed.", "✓".green().bold());
    }

    Ok(())
}
