use anyhow::Result;
use colored::Colorize;

pub fn run(env: Option<String>) -> Result<()> {
    let env_display = env.as_deref().unwrap_or("all");
    println!("{} Installing packages for environment: {}", "→".cyan(), env_display);
    // TODO: read lock file, call backend install per package
    println!("{} Install not yet implemented in Rust CLI", "!".yellow());
    println!("  Use the Python CLI: python -m envknit.cli.main install");
    Ok(())
}
