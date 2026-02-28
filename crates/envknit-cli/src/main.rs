mod backends;
mod cli;
mod commands;
mod config;
mod error;
mod lockfile;
mod resolver;

use anyhow::Result;
use clap::Parser;
use cli::Cli;

fn main() -> Result<()> {
    let cli = Cli::parse();
    commands::dispatch(cli)
}
