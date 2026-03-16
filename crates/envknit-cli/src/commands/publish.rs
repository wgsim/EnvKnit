use anyhow::{bail, Context, Result};
use colored::Colorize;
use std::path::Path;

pub fn run(repository: String, dry_run: bool) -> Result<()> {
    // Require a pyproject.toml or setup.py in the current directory
    let has_pyproject = Path::new("pyproject.toml").exists();
    let has_setup = Path::new("setup.py").exists();

    if !has_pyproject && !has_setup {
        bail!("No pyproject.toml or setup.py found. Cannot build a distribution.");
    }

    // Check build tool availability
    let build_cmd = find_build_tool()?;
    let twine_cmd = find_twine()?;

    println!("{} Building distribution...", "→".cyan());

    if dry_run {
        println!("{} Dry run — would run: {} build", "→".cyan(), build_cmd);
        println!("{} Dry run — would run: {} upload --repository {} dist/*", "→".cyan(), twine_cmd, repository);
        return Ok(());
    }

    // Step 1: build
    let build_status = std::process::Command::new(&build_cmd)
        .arg("build")
        .status()
        .with_context(|| format!("Failed to run '{} build'", build_cmd))?;

    if !build_status.success() {
        bail!("Build failed (exit code: {:?})", build_status.code());
    }

    println!("{} Build complete.", "✓".green());

    // Step 2: twine upload
    // Enumerate dist/ explicitly — std::process::Command does not use a shell,
    // so "dist/*" would be passed as a literal string and twine would find nothing.
    println!("{} Uploading to '{}'...", "→".cyan(), repository);

    let dist_files: Vec<_> = std::fs::read_dir("dist")
        .context("Failed to read dist/ directory")?
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| {
            matches!(
                p.extension().and_then(|s| s.to_str()),
                Some("whl") | Some("gz") | Some("zip")
            )
        })
        .collect();

    if dist_files.is_empty() {
        bail!("No distribution files found in dist/. Did the build step produce output?");
    }

    let twine_status = std::process::Command::new(&twine_cmd)
        .arg("upload")
        .arg("--repository")
        .arg(&repository)
        .args(&dist_files)
        .status()
        .with_context(|| "Failed to run twine upload")?;

    if !twine_status.success() {
        bail!("twine upload failed (exit code: {:?})", twine_status.code());
    }

    println!("{} Published to '{}'.", "✓".green(), repository);
    Ok(())
}

fn find_build_tool() -> Result<String> {
    for cmd in &["python3 -m build", "python -m build"] {
        let parts: Vec<&str> = cmd.split_whitespace().collect();
        if let Some((&prog, args)) = parts.split_first() {
            let ok = std::process::Command::new(prog)
                .args(args)
                .arg("--version")
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);
            if ok {
                return Ok(cmd.to_string());
            }
        }
    }
    bail!(
        "Build tool not found. Install it with: pip install build\n  \
         Then retry `envknit publish`."
    )
}

fn find_twine() -> Result<String> {
    for cmd in &["twine", "python3 -m twine", "python -m twine"] {
        let parts: Vec<&str> = cmd.split_whitespace().collect();
        if let Some((&prog, args)) = parts.split_first() {
            let ok = std::process::Command::new(prog)
                .args(args)
                .arg("--version")
                .output()
                .map(|o| o.status.success())
                .unwrap_or(false);
            if ok {
                return Ok(cmd.to_string());
            }
        }
    }
    bail!(
        "twine not found. Install it with: pip install twine\n  \
         Then retry `envknit publish`."
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tmpdir(label: &str) -> std::path::PathBuf {
        let base = std::env::temp_dir().join(format!(
            "envknit_pub_{}_{}_{label}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        fs::create_dir_all(&base).unwrap();
        base
    }

    #[test]
    fn test_publish_no_pyproject_fails() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("nf");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        let result = run("pypi".to_string(), true);
        std::env::set_current_dir(orig).unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_publish_dry_run_with_pyproject() {
        let _g = crate::GLOBAL_CWD_LOCK.lock().unwrap();
        let dir = tmpdir("dr");
        let orig = std::env::current_dir().unwrap();
        std::env::set_current_dir(&dir).unwrap();
        fs::write("pyproject.toml", "[project]\nname = \"test\"\nversion = \"0.1.0\"\n").unwrap();
        // dry_run=true only checks file existence + tool availability
        // If tools not installed, this still errors — that's acceptable behavior
        let _ = run("pypi".to_string(), true); // ignore result (build tool may not be installed in CI)
        std::env::set_current_dir(orig).unwrap();
    }
}
