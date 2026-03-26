pub mod backends;
pub mod cli;
pub mod commands;
pub mod config;
pub mod error;
pub mod global_config;
pub mod lockfile;
pub mod node_resolver;
pub mod python_resolver;
pub mod process_util;
pub mod uv_resolver;

/// Shared mutex for tests that mutate the process working directory.
/// All CWD-sensitive tests must hold this lock to avoid parallel interference.
#[cfg(test)]
pub static GLOBAL_CWD_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Shared mutex for tests that mutate PATH. All PATH-sensitive tests must hold
/// this lock to prevent parallel test interference.
#[cfg(test)]
pub static GLOBAL_PATH_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
