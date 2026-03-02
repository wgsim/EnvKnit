pub mod add;
pub mod env_list;
pub mod export;
pub mod graph;
pub mod init;
pub mod install;
pub mod lock;
pub mod remove;
pub mod run;
pub mod status;
pub mod store;
pub mod tree;
pub mod why;

use crate::cli::{Cli, Commands, EnvAction, StoreAction};
use anyhow::Result;

pub fn dispatch(cli: Cli) -> Result<()> {
    match cli.command {
        Commands::Init { env, backend } => init::run(env, backend),
        Commands::Add { package, env, backend } => add::run(package, env, backend),
        Commands::Remove { package, env } => remove::run(package, env),
        Commands::Lock { update, dry_run } => lock::run(update, dry_run),
        Commands::Install { env } => install::run(env),
        Commands::Status { env } => status::run(env),
        Commands::Tree { env, depth } => tree::run(env, depth),
        Commands::Graph { env, json, depth } => graph::run(env, json, depth),
        Commands::Why { package, env } => why::run(package, env),
        Commands::Export { format, output } => export::run(format, output),
        Commands::Env { action } => match action {
            EnvAction::List => env_list::run(),
        },
        Commands::Run { env, command } => run::run(env, command),
        Commands::Store { action } => match action {
            StoreAction::List { package } => store::list(package),
            StoreAction::Stats => store::stats(),
            StoreAction::Cleanup { dry_run } => store::cleanup(dry_run),
        },
    }
}
