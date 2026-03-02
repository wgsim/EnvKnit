use clap::{Parser, Subcommand};

#[derive(Subcommand)]
pub enum EnvAction {
    /// List all environments
    List,
}

#[derive(Subcommand)]
pub enum StoreAction {
    /// List installed packages
    List {
        #[arg(long)]
        package: Option<String>,
    },
    /// Show store disk usage statistics
    Stats,
    /// Remove packages not referenced by current lock file
    Cleanup {
        #[arg(long)]
        dry_run: bool,
    },
}

#[derive(Parser)]
#[command(
    name = "envknit",
    version,
    about = "Multi-version Python package manager",
    long_about = None,
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Initialize a new EnvKnit project
    Init {
        #[arg(long, default_value = "default")]
        env: String,
        #[arg(long)]
        backend: Option<String>,
    },
    /// Add a package to the configuration
    Add {
        /// Package spec (e.g. numpy, numpy==1.26.4, numpy>=1.24)
        package: String,
        #[arg(long, default_value = "default")]
        env: String,
        #[arg(long)]
        backend: Option<String>,
        /// Add as a development dependency
        #[arg(long)]
        dev: bool,
    },
    /// Remove a package from the configuration
    Remove {
        package: String,
        #[arg(long, default_value = "default")]
        env: String,
    },
    /// Resolve dependencies and write lock file
    Lock {
        #[arg(long)]
        update: Option<String>,
        #[arg(long)]
        dry_run: bool,
    },
    /// Install packages from lock file
    Install {
        #[arg(long)]
        env: Option<String>,
    },
    /// Show status of installed environments
    Status {
        #[arg(long)]
        env: Option<String>,
    },
    /// Show dependency tree
    Tree {
        #[arg(long)]
        env: Option<String>,
        #[arg(long, default_value = "3")]
        depth: usize,
    },
    /// Show dependency graph from lock file
    Graph {
        #[arg(long)]
        env: Option<String>,
        #[arg(long)]
        json: bool,
        #[arg(long, default_value = "0")]
        depth: usize,
    },
    /// Show why a package is installed
    Why {
        package: String,
        #[arg(long)]
        env: Option<String>,
    },
    /// Export configuration in various formats
    Export {
        #[arg(long, default_value = "requirements")]
        format: String,
        #[arg(long)]
        output: Option<String>,
    },
    /// Manage environments
    Env {
        #[command(subcommand)]
        action: EnvAction,
    },
    /// Run a command in an environment's package context
    Run {
        #[arg(long, default_value = "default")]
        env: String,
        /// Command and arguments (everything after --)
        #[arg(last = true)]
        command: Vec<String>,
    },
    /// Manage the package store
    Store {
        #[command(subcommand)]
        action: StoreAction,
    },
    /// Upgrade package(s) to latest (removes == pins; keeps flexible constraints)
    Upgrade {
        /// Package name (upgrades all if omitted)
        package: Option<String>,
        #[arg(long, default_value = "default")]
        env: String,
        /// Pin to an explicit version instead of unpinning
        #[arg(long)]
        version: Option<String>,
    },
}
