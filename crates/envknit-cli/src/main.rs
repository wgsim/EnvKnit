mod backends;
mod cli;
mod commands;
mod config;
mod error;
mod lockfile;
mod resolver;

/// Shared mutex for tests that mutate the process working directory.
/// All CWD-sensitive tests must hold this lock to avoid parallel interference.
#[cfg(test)]
pub static GLOBAL_CWD_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

use anyhow::Result;
use clap::Parser;
use cli::Cli;

fn main() -> Result<()> {
    let cli = Cli::parse();
    commands::dispatch(cli)
}
