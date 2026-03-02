use anyhow::{Context, Result};
use colored::Colorize;
use dirs_next::home_dir;
use std::path::PathBuf;

const SHIM_SH: &str = r#"# EnvKnit shell integration
# Source this file or add to your .bashrc/.zshrc:
#   eval "$(envknit init-shell)"

# envknit-activate: activate an environment by prepending install_paths to PYTHONPATH
envknit-activate() {
    local env="${1:-default}"
    local paths
    paths=$(envknit run --env "$env" -- python3 -c "import sys; print(':'.join(sys.path))" 2>/dev/null)
    if [ -z "$paths" ]; then
        echo "envknit: no install paths for env '$env'" >&2
        return 1
    fi
    export PYTHONPATH="$paths"
    export ENVKNIT_ENV="$env"
    echo "  Activated EnvKnit env: $env" >&2
}

# envknit-deactivate: restore PYTHONPATH
envknit-deactivate() {
    unset PYTHONPATH
    unset ENVKNIT_ENV
    echo "  Deactivated EnvKnit env" >&2
}

# Prompt integration: show active env in PS1 (optional)
_envknit_ps1() {
    if [ -n "$ENVKNIT_ENV" ]; then
        printf '(envknit:%s) ' "$ENVKNIT_ENV"
    fi
}
"#;

fn shim_path() -> Option<PathBuf> {
    home_dir().map(|h| h.join(".envknit").join("shim.sh"))
}

pub fn run(shell: Option<String>) -> Result<()> {
    let shell = shell.unwrap_or_else(|| {
        std::env::var("SHELL")
            .unwrap_or_default()
            .rsplit('/')
            .next()
            .unwrap_or("bash")
            .to_string()
    });

    let shim = shim_path().context("Cannot determine home directory")?;
    let shim_dir = shim.parent().unwrap();
    std::fs::create_dir_all(shim_dir)?;
    std::fs::write(&shim, SHIM_SH)?;

    // Emit the eval-able line to stdout
    match shell.as_str() {
        "fish" => {
            // fish uses `source` and different syntax; print a warning
            eprintln!(
                "{} Fish shell: source {} manually (fish syntax differs)",
                "!".yellow(),
                shim.display()
            );
            println!("# Fish shell not yet supported. Source shim.sh manually.");
        }
        _ => {
            // bash / zsh / sh compatible
            println!("source {}", shim.display());
        }
    }

    Ok(())
}

pub fn write_shim_only() -> Result<PathBuf> {
    let shim = shim_path().context("Cannot determine home directory")?;
    std::fs::create_dir_all(shim.parent().unwrap())?;
    std::fs::write(&shim, SHIM_SH)?;
    Ok(shim)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_write_shim_creates_file() {
        // write_shim_only writes to ~/.envknit/shim.sh; just ensure it doesn't error.
        // (Only run if HOME is available)
        if home_dir().is_none() {
            return;
        }
        let path = write_shim_only().unwrap();
        assert!(path.exists());
        let content = std::fs::read_to_string(&path).unwrap();
        assert!(content.contains("envknit-activate"));
        assert!(content.contains("envknit-deactivate"));
    }

    #[test]
    fn test_shim_contains_ps1_helper() {
        assert!(SHIM_SH.contains("_envknit_ps1"));
    }
}
