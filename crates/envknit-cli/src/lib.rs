pub mod backends;
pub mod cli;
pub mod commands;
pub mod config;
pub mod error;
pub mod global_config;
pub mod lockfile;
pub mod node_resolver;
pub mod python_resolver;
pub mod resolver;
pub mod uv_resolver;

/// Shared mutex for tests that mutate the process working directory.
/// All CWD-sensitive tests must hold this lock to avoid parallel interference.
#[cfg(test)]
pub static GLOBAL_CWD_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
