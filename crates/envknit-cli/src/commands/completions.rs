use crate::cli::Cli;
use anyhow::Result;
use clap::CommandFactory;
use clap_complete::{generate, Shell};
use std::io;

pub fn run(shell: Shell) -> Result<()> {
    let mut cmd = Cli::command();
    generate(shell, &mut cmd, "envknit", &mut io::stdout());
    Ok(())
}
