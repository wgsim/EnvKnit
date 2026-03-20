"""
Isolation module for runtime package separation.

Provides import hooks and shim generation to ensure packages
from different environments don't interfere with each other.

Also provides CLI tool shims for automatic version switching
when changing directories (similar to pyenv/rbenv/direnv).
"""

from envknit.isolation.import_hook import (
    # Manager
    ImportHookManager,
    IsolationContext,
    # Legacy
    IsolationImporter,
    VersionContext,
    VersionedFinder,
    VersionedLoader,
    VersionedModule,
    # Versioned imports
    VersionRegistry,
    configure_from_lock,
    disable,
    # Convenience API
    enable,
    get_manager,
    import_version,
    set_default,
    use,
)
from envknit.isolation.subinterpreter import (
    CExtIncompatibleError,
    SubInterpreterEnv,
    UnsupportedPlatformError,
)
from envknit.isolation.shim import (
    CLIShimGenerator,
    ShellIntegration,
    ShimConfig,
    ShimGenerator,
    ToolDispatcher,
    ToolShimConfig,
    get_shell_integration,
    get_shim_generator,
    get_tool_dispatcher,
)

__all__ = [
    # Legacy import shims
    "ShimGenerator",
    "ShimConfig",
    "IsolationImporter",
    "IsolationContext",
    # CLI tool shims
    "CLIShimGenerator",
    "ToolShimConfig",
    "ShellIntegration",
    "ToolDispatcher",
    # Versioned imports
    "VersionRegistry",
    "VersionedFinder",
    "VersionedLoader",
    "VersionedModule",
    # Manager
    "ImportHookManager",
    "VersionContext",
    # Sub-interpreter strict isolation
    "SubInterpreterEnv",
    "UnsupportedPlatformError",
    "CExtIncompatibleError",
    # Convenience functions - CLI
    "get_shim_generator",
    "get_shell_integration",
    "get_tool_dispatcher",
    # Convenience functions - Import hooks
    "enable",
    "disable",
    "use",
    "import_version",
    "set_default",
    "configure_from_lock",
    "get_manager",
]
