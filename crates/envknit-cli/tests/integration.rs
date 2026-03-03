/// Integration tests for the EnvKnit CLI command logic.
///
/// These tests exercise the *commands* end-to-end using temporary directories
/// and pre-written fixture files.  They do NOT call the network.
///
/// CWD-sensitive tests must hold `CWD_LOCK` to prevent parallel interference,
/// since Rust integration tests run concurrently in the same process.
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

static CWD_LOCK: Mutex<()> = Mutex::new(());

// ── helpers ───────────────────────────────────────────────────────────────────

fn tmpdir(label: &str) -> PathBuf {
    let base = std::env::temp_dir().join(format!(
        "envknit_integ_{}_{}_{label}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .subsec_nanos()
    ));
    fs::create_dir_all(&base).unwrap();
    base
}

fn write(dir: &Path, name: &str, content: &str) -> PathBuf {
    let p = dir.join(name);
    fs::write(&p, content).unwrap();
    p
}

/// Config with only production packages (no dev) to avoid lock-drift in `check` tests.
const SIMPLE_CONFIG: &str = r#"
environments:
  default:
    python_version: "3.11"
    packages:
      - requests>=2.28
"#;

const SIMPLE_LOCK: &str = r#"
schema_version: "1.0"
lock_generated_at: "2026-01-01T00:00:00+00:00"
resolver_version: "0.1.0"
environments:
  default:
    - name: requests
      version: "2.31.0"
      dev: false
      sha256: ~
"#;

// ── init ─────────────────────────────────────────────────────────────────────

#[test]
fn init_creates_config_file() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("init");
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::init::run("default".to_string(), None).unwrap();

    assert!(dir.join("envknit.yaml").exists());
    std::env::set_current_dir(prev).unwrap();
}

#[test]
fn init_fails_when_config_exists() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("init_exists");
    write(&dir, "envknit.yaml", SIMPLE_CONFIG);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::init::run("default".to_string(), None);
    assert!(result.is_err(), "init should fail if config already exists");

    std::env::set_current_dir(prev).unwrap();
}

// ── add / remove ─────────────────────────────────────────────────────────────

#[test]
fn add_then_remove_package() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("add_rm");
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::init::run("default".to_string(), None).unwrap();
    envknit_cli::commands::add::run(
        "numpy>=1.24".to_string(),
        "default".to_string(),
        None,
        false,
    )
    .unwrap();

    let content = fs::read_to_string(dir.join("envknit.yaml")).unwrap();
    assert!(content.contains("numpy"), "add should persist to config");

    envknit_cli::commands::remove::run("numpy".to_string(), "default".to_string(), false).unwrap();

    let content = fs::read_to_string(dir.join("envknit.yaml")).unwrap();
    assert!(!content.contains("numpy"), "remove should delete from config");

    std::env::set_current_dir(prev).unwrap();
}

#[test]
fn add_dev_package() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("add_dev");
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::init::run("default".to_string(), None).unwrap();
    envknit_cli::commands::add::run(
        "pytest>=7.0".to_string(),
        "default".to_string(),
        None,
        true, // dev
    )
    .unwrap();

    let content = fs::read_to_string(dir.join("envknit.yaml")).unwrap();
    assert!(content.contains("pytest"), "dev package should be in config");

    std::env::set_current_dir(prev).unwrap();
}

// ── check ─────────────────────────────────────────────────────────────────────

#[test]
fn check_passes_when_in_sync() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("check_sync");
    write(&dir, "envknit.yaml", SIMPLE_CONFIG);
    write(&dir, "envknit.lock.yaml", SIMPLE_LOCK);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::check::run();
    assert!(result.is_ok(), "check should pass when config and lock match");

    std::env::set_current_dir(prev).unwrap();
}

#[test]
fn check_fails_when_package_missing_from_lock() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("check_drift");
    let drifted_lock = r#"
schema_version: "1.0"
lock_generated_at: "2026-01-01T00:00:00+00:00"
resolver_version: "0.1.0"
environments:
  default: []
"#;
    write(&dir, "envknit.yaml", SIMPLE_CONFIG);
    write(&dir, "envknit.lock.yaml", drifted_lock);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::check::run();
    assert!(result.is_err(), "check should fail on drift");

    std::env::set_current_dir(prev).unwrap();
}

// ── diff ──────────────────────────────────────────────────────────────────────

#[test]
fn diff_identical_locks_shows_no_changes() {
    let dir = tmpdir("diff_same");
    let base = write(&dir, "base.lock.yaml", SIMPLE_LOCK);
    let head = write(&dir, "head.lock.yaml", SIMPLE_LOCK);

    let result = envknit_cli::commands::diff::run(
        base.to_string_lossy().into_owned(),
        head.to_string_lossy().into_owned(),
        None,
    );
    assert!(result.is_ok());
}

#[test]
fn diff_detects_added_package() {
    let dir = tmpdir("diff_added");
    let head_lock = r#"
schema_version: "1.0"
lock_generated_at: "2026-01-01T00:00:00+00:00"
resolver_version: "0.1.0"
environments:
  default:
    - name: requests
      version: "2.31.0"
      dev: false
      sha256: ~
    - name: urllib3
      version: "2.1.0"
      dev: false
      sha256: ~
"#;
    let base = write(&dir, "base.lock.yaml", SIMPLE_LOCK);
    let head = write(&dir, "head.lock.yaml", head_lock);

    let result = envknit_cli::commands::diff::run(
        base.to_string_lossy().into_owned(),
        head.to_string_lossy().into_owned(),
        None,
    );
    assert!(result.is_ok());
}

// ── pin ───────────────────────────────────────────────────────────────────────

#[test]
fn pin_writes_exact_versions_to_config() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("pin");
    write(&dir, "envknit.yaml", SIMPLE_CONFIG);
    write(&dir, "envknit.lock.yaml", SIMPLE_LOCK);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::pin::run("default".to_string(), None).unwrap();

    let content = fs::read_to_string(dir.join("envknit.yaml")).unwrap();
    assert!(
        content.contains("==2.31.0"),
        "pin should write ==version to config: got\n{content}"
    );

    std::env::set_current_dir(prev).unwrap();
}

// ── export ────────────────────────────────────────────────────────────────────

#[test]
fn export_requirements_format() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("export_req");
    let out = dir.join("requirements.txt");
    write(&dir, "envknit.lock.yaml", SIMPLE_LOCK);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::export::run(
        "requirements".to_string(),
        Some(out.to_string_lossy().into_owned()),
        false,
    )
    .unwrap();

    let content = fs::read_to_string(&out).unwrap();
    assert!(
        content.contains("requests==2.31.0"),
        "requirements export should contain pinned package: got\n{content}"
    );

    std::env::set_current_dir(prev).unwrap();
}

#[test]
fn export_json_format() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("export_json");
    let out = dir.join("lock.json");
    write(&dir, "envknit.lock.yaml", SIMPLE_LOCK);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::export::run(
        "json".to_string(),
        Some(out.to_string_lossy().into_owned()),
        false,
    )
    .unwrap();

    let content = fs::read_to_string(&out).unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&content).unwrap();
    assert!(parsed.is_object() || parsed.is_array(), "export json should be valid JSON");

    std::env::set_current_dir(prev).unwrap();
}

// ── store list ────────────────────────────────────────────────────────────────

#[test]
fn store_list_does_not_panic() {
    // store list reads from ~/.envknit/packages/ — just verify it doesn't crash.
    let result = envknit_cli::commands::store::list(None);
    assert!(result.is_ok());
}
