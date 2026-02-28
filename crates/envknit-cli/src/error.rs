use thiserror::Error;

#[derive(Error, Debug)]
pub enum EnvKnitError {
    #[error("Lock file not found: {0}")]
    LockFileNotFound(String),
    #[error("Config file not found: {0}")]
    ConfigNotFound(String),
    #[error("Backend error: {0}")]
    BackendError(String),
    #[error("Resolution failed: {0}")]
    ResolutionFailed(String),
    #[error("Schema version mismatch: file={file}, supported={supported}")]
    SchemaVersionMismatch { file: String, supported: String },
}
