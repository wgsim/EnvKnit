pub mod add;
pub mod env_create;
pub mod env_list;
pub mod env_remove;
pub mod export;
pub mod graph;
pub mod init;
pub mod init_shell;
pub mod install;
pub mod lock;
pub mod remove;
pub mod run;
pub mod status;
pub mod store;
pub mod tree;
pub mod upgrade;
pub mod why;

use crate::cli::{Cli, Commands, EnvAction, StoreAction};

use anyhow::Result;

pub fn dispatch(cli: Cli) -> Result<()> {
    match cli.command {
        Commands::Init { env, backend } => init::run(env, backend),
        Commands::Add { package, env, backend, dev } => add::run(package, env, backend, dev),
        Commands::Remove { package, env, dev } => remove::run(package, env, dev),
        Commands::Lock { update, dry_run, env } => lock::run(update, dry_run, env),
        Commands::Install { env, no_dev } => install::run(env, no_dev),
        Commands::Status { env } => status::run(env),
        Commands::Tree { env, depth } => tree::run(env, depth),
        Commands::Graph { env, json, depth } => graph::run(env, json, depth),
        Commands::Why { package, env } => why::run(package, env),
        Commands::Export { format, output, no_dev } => export::run(format, output, no_dev),
        Commands::Env { action } => match action {
            EnvAction::List => env_list::run(),
            EnvAction::Create { name, backend } => env_create::run(name, backend),
            EnvAction::Remove { name } => env_remove::run(name),
        },
        Commands::Run { env, command } => run::run(env, command),
        Commands::Store { action } => match action {
            StoreAction::List { package } => store::list(package),
            StoreAction::Stats => store::stats(),
            StoreAction::Cleanup { dry_run } => store::cleanup(dry_run),
        },
        Commands::InitShell { shell } => init_shell::run(shell),
        Commands::Upgrade { package, env, version } => upgrade::run(package, env, version),
    }
}
