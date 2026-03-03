use anyhow::Result;
use clap::Parser;
use envknit_cli::cli::Cli;
use envknit_cli::commands;

fn main() -> Result<()> {
    let cli = Cli::parse();
    commands::dispatch(cli)
}
