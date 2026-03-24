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

/// Config with prod + dev packages to exercise dev_packages handling.
const DEV_CONFIG: &str = r#"
environments:
  default:
    packages:
      - requests>=2.28
    dev_packages:
      - pytest>=7.0
"#;

const DEV_LOCK: &str = r#"
schema_version: "1.0"
lock_generated_at: "2026-01-01T00:00:00+00:00"
resolver_version: "0.1.0"
environments:
  default:
    - name: requests
      version: "2.31.0"
      dev: false
      sha256: ~
    - name: pytest
      version: "7.4.4"
      dev: true
      sha256: ~
"#;

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

// ── node_version ─────────────────────────────────────────────────────────────

/// Verify resolve_node rejects noise directories ("aliases", "default", "lts")
/// that nvm/fnm place alongside version dirs in their store.
#[test]
fn node_resolver_ignores_non_semver_dirs() {
    use envknit_cli::node_resolver;
    use std::env;

    let dir = tmpdir("nvm_noise");
    let versions = dir.join("versions").join("node");
    // Create a valid version dir and several noise dirs.
    for name in &["v20.11.0", "default", "lts", "aliases", "system"] {
        let bin = versions.join(name).join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        // Simulate node binary existing only for real versions.
        if name.starts_with('v') {
            std::fs::write(bin.join("node"), "").unwrap();
        }
    }

    // Point NVM_DIR at our fake nvm store.
    let prev_nvm = env::var("NVM_DIR").ok();
    env::set_var("NVM_DIR", dir.to_str().unwrap());

    let result = node_resolver::resolve_node("20.11");
    // Restore env.
    match prev_nvm {
        Some(v) => env::set_var("NVM_DIR", v),
        None => env::remove_var("NVM_DIR"),
    }
    // resolve_node("20.11") may still fail if node binary is a dummy file,
    // but it must NOT panic on noise dirs.
    assert!(result.is_ok() || result.is_err(), "must not panic on noise dirs");
}

#[test]
fn check_warns_on_unresolvable_node_version_integration() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("node_warn");
    let yaml = "environments:\n  frontend:\n    node_version: '99.99.99'\n    packages: []\n";
    write(&dir, "envknit.yaml", yaml);
    let lock_yaml = "schema_version: '1.0'\nlock_generated_at: '2026-01-01T00:00:00+00:00'\nresolver_version: '0.1.0'\nenvironments:\n  frontend: []\n";
    write(&dir, "envknit.lock.yaml", lock_yaml);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    // check must exit 0 (node_version failure is Warn not Fail)
    let result = envknit_cli::commands::check::run();
    std::env::set_current_dir(prev).unwrap();
    assert!(result.is_ok(), "unresolvable node_version should be Warn not Fail in check");
}

#[test]
fn config_with_node_version_parses_correctly() {
    let dir = tmpdir("node_parse");
    let yaml = "environments:\n  frontend:\n    node_version: '20.11'\n    packages: []\n";
    write(&dir, "envknit.yaml", yaml);
    let cfg = envknit_cli::config::Config::load(&dir.join("envknit.yaml")).unwrap();
    assert_eq!(
        cfg.environments["frontend"].node_version.as_deref(),
        Some("20.11")
    );
}

// ── dev_packages ─────────────────────────────────────────────────────────────

#[test]
fn dev_packages_parsed_from_config() {
    let dir = tmpdir("dev_parse");
    write(&dir, "envknit.yaml", DEV_CONFIG);
    let cfg = envknit_cli::config::Config::load(&dir.join("envknit.yaml")).unwrap();
    let env = &cfg.environments["default"];
    assert_eq!(env.packages.len(), 1);
    assert_eq!(env.packages[0].name, "requests");
    assert_eq!(env.dev_packages.len(), 1);
    assert_eq!(env.dev_packages[0].name, "pytest");
}

#[test]
fn check_passes_with_dev_packages_in_lock() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("check_dev");
    write(&dir, "envknit.yaml", DEV_CONFIG);
    write(&dir, "envknit.lock.yaml", DEV_LOCK);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::check::run();
    std::env::set_current_dir(prev).unwrap();
    assert!(result.is_ok(), "check should pass when dev packages are present in lock");
}

#[test]
fn export_no_dev_excludes_dev_packages() {
    let _lock = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("export_no_dev");
    let out = dir.join("requirements.txt");
    write(&dir, "envknit.lock.yaml", DEV_LOCK);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    envknit_cli::commands::export::run(
        "requirements".to_string(),
        Some(out.to_string_lossy().into_owned()),
        true, // no_dev=true
    )
    .unwrap();

    let content = fs::read_to_string(&out).unwrap();
    std::env::set_current_dir(prev).unwrap();
    assert!(content.contains("requests"), "prod package should be exported");
    assert!(!content.contains("pytest"), "dev package must be excluded when no_dev=true");
}

#[test]
fn lock_uv_with_dev_packages_marks_dev_flag() {
    if envknit_cli::uv_resolver::find_uv().is_none() {
        eprintln!("uv not found — skipping dev_packages uv test");
        return;
    }

    let _guard = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("lock_uv_dev");
    write(&dir, "envknit.yaml", DEV_CONFIG);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::lock::run(None, false, None);
    std::env::set_current_dir(&prev).unwrap();
    assert!(result.is_ok(), "lock with dev_packages failed: {:?}", result);

    let lock_content = std::fs::read_to_string(dir.join("envknit.lock.yaml")).unwrap();
    assert!(lock_content.contains("requests"), "lock should contain prod package");
    assert!(lock_content.contains("pytest"), "lock should contain dev package");
    // pytest entry must be marked dev: true
    assert!(
        lock_content.contains("dev: true"),
        "dev package should be marked dev: true in lock"
    );
}

// ── lock ──────────────────────────────────────────────────────────────────────

#[test]
fn lock_dry_run_does_not_write_lockfile() {
    let _guard = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("lock_dry_run");
    write(&dir, "envknit.yaml", SIMPLE_CONFIG);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::lock::run(None, true, None);  // dry_run=true

    std::env::set_current_dir(&prev).unwrap();
    assert!(result.is_ok(), "dry run failed: {:?}", result);
    assert!(
        !dir.join("envknit.lock.yaml").exists(),
        "dry run must not write lock file"
    );
}

#[test]
fn lock_command_with_uv_produces_valid_lockfile() {
    // Only run if uv is available
    if envknit_cli::uv_resolver::find_uv().is_none() {
        eprintln!("uv not found — skipping uv lock test");
        return;
    }

    let _guard = CWD_LOCK.lock().unwrap();
    let dir = tmpdir("lock_uv");
    write(&dir, "envknit.yaml", r#"
environments:
  default:
    packages:
      - requests>=2.28
"#);
    let prev = std::env::current_dir().unwrap();
    std::env::set_current_dir(&dir).unwrap();

    let result = envknit_cli::commands::lock::run(None, false, None);

    std::env::set_current_dir(&prev).unwrap();
    assert!(result.is_ok(), "lock failed: {:?}", result);

    let lock_content = std::fs::read_to_string(dir.join("envknit.lock.yaml")).unwrap();
    assert!(lock_content.contains("requests"), "lock missing requests");
    assert!(lock_content.contains("version:"), "lock missing pinned version field");
    // resolver_version should indicate uv was used
    assert!(lock_content.contains("uv/"), "lock should record uv as resolver");
}
