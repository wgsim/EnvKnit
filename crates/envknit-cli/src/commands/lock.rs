use anyhow::Result;
use colored::Colorize;

pub fn run(update: Option<String>, dry_run: bool) -> Result<()> {
    if dry_run {
        println!("{} Dry run — would resolve dependencies", "→".cyan());
    }
    if let Some(pkg) = &update {
        println!("{} Would update: {}", "→".cyan(), pkg);
    }
    // Resolution is delegated to the Python CLI (PubGrub resolver)
    // until the Rust resolver is ported (v1.0 roadmap).
    println!("{} Resolution not yet implemented in Rust CLI", "!".yellow());
    println!("  Use the Python CLI: python -m envknit.cli.main lock");
    Ok(())
}
