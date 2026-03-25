/// Subprocess utilities shared by uv_resolver and install.
use anyhow::{bail, Result};
use std::process::{Child, Output};
use std::time::Duration;

/// Wait for a child process to finish, enforcing a wall-clock timeout.
///
/// The child is moved into a background thread that calls `wait_with_output()`.
/// The calling thread blocks on a channel `recv_timeout()`.  If the deadline
/// passes before the child exits, the child is killed and an error is returned.
///
/// Pass `timeout = Duration::ZERO` (or any zero duration) to disable the
/// timeout and wait indefinitely — equivalent to `child.wait_with_output()`.
pub fn wait_output_timeout(mut child: Child, timeout: Duration) -> Result<Output> {
    if timeout.is_zero() {
        return child.wait_with_output().map_err(Into::into);
    }

    let (tx, rx) = std::sync::mpsc::channel::<Result<Output, std::io::Error>>();
    std::thread::spawn(move || {
        let _ = tx.send(child.wait_with_output());
    });

    match rx.recv_timeout(timeout) {
        Ok(Ok(output)) => Ok(output),
        Ok(Err(e)) => bail!("subprocess I/O error: {}", e),
        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
            bail!("subprocess timed out after {}s", timeout.as_secs())
        }
        Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
            bail!("subprocess thread disconnected unexpectedly")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    #[test]
    fn wait_output_timeout_succeeds_fast_command() {
        let child = Command::new("true").spawn().unwrap();
        let out = wait_output_timeout(child, Duration::from_secs(5)).unwrap();
        assert!(out.status.success());
    }

    #[test]
    fn wait_output_timeout_zero_disables_timeout() {
        let child = Command::new("true").spawn().unwrap();
        let out = wait_output_timeout(child, Duration::ZERO).unwrap();
        assert!(out.status.success());
    }

    #[test]
    fn wait_output_timeout_kills_slow_command() {
        // `sleep 10` should be killed well before 10 s
        let child = Command::new("sleep").arg("10").spawn().unwrap();
        let result = wait_output_timeout(child, Duration::from_millis(200));
        assert!(result.is_err());
        let msg = result.unwrap_err().to_string();
        assert!(msg.contains("timed out"), "expected timeout error, got: {msg}");
    }
}
