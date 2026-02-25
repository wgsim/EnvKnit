# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for the envknit-cli standalone binary.

Build with:
    pyinstaller envknit-cli.spec

Output: dist/envknit  (dist/envknit.exe on Windows)

The binary bundles all CLI deps (click, pyyaml, rich, packaging) so it can
run without any Python installation.  It does NOT bundle conda/pip — those
are invoked as external subprocesses at runtime, same as the source install.

Multiprocessing note:
    envknit.isolation.worker uses multiprocessing.get_context("spawn").  In a
    frozen binary, the spawned child re-launches the same executable with
    special __mp_main__ flags.  multiprocessing.freeze_support() (called in
    __main__.py) intercepts those flags and runs _worker_main instead of the
    full CLI.  Without freeze_support() the child would endlessly restart the
    CLI instead of becoming a worker subprocess.
"""

import sys
from pathlib import Path

block_cipher = None

# ---------------------------------------------------------------------------
# Hidden imports — modules PyInstaller's static analysis may miss
# ---------------------------------------------------------------------------

hidden_imports = [
    # Click
    "click",
    "click.core",
    "click.decorators",
    "click.exceptions",
    "click.formatting",
    "click.globals",
    "click.shell_completion",
    "click.types",
    "click.utils",
    # PyYAML — the C accelerator (_yaml) is optional but listed for completeness
    "yaml",
    "yaml.constructor",
    "yaml.dumper",
    "yaml.loader",
    "yaml.representer",
    "yaml.resolver",
    "yaml.scanner",
    # Rich — explicitly list submodules that may be imported dynamically
    "rich",
    "rich.console",
    "rich.color",
    "rich.markup",
    "rich.panel",
    "rich.progress",
    "rich.prompt",
    "rich.style",
    "rich.syntax",
    "rich.table",
    "rich.text",
    "rich.theme",
    "rich.traceback",
    # packaging
    "packaging",
    "packaging.requirements",
    "packaging.specifiers",
    "packaging.version",
    # multiprocessing (spawn support for worker pool)
    "multiprocessing",
    "multiprocessing.connection",
    "multiprocessing.context",
    "multiprocessing.process",
    "multiprocessing.reduction",
    "multiprocessing.resource_tracker",
    "multiprocessing.spawn",
    # EnvKnit — enumerate all internal packages so they survive tree-shaking
    "envknit",
    "envknit.ai",
    "envknit.backends",
    "envknit.backends.base",
    "envknit.backends.conda",
    "envknit.backends.pip",
    "envknit.backends.poetry",
    "envknit.cli",
    "envknit.cli.main",
    "envknit.config",
    "envknit.config.schema",
    "envknit.core",
    "envknit.core.graph",
    "envknit.core.lock",
    "envknit.core.resolver",
    "envknit.isolation",
    "envknit.isolation.import_hook",
    "envknit.isolation.shim",
    "envknit.isolation.worker",
    "envknit.security",
    "envknit.security.models",
    "envknit.security.scanner",
    "envknit.storage",
    "envknit.storage.cache",
    "envknit.storage.store",
    "envknit.utils",
    "envknit.utils.version",
]

# ---------------------------------------------------------------------------
# Modules to exclude — reduces binary size; none of these are used by CLI
# ---------------------------------------------------------------------------

excludes = [
    # GUI toolkits — never needed in a CLI tool
    "tkinter",
    # Test frameworks — not imported at runtime
    "test",
    "unittest",
    # Data science packages — not bundled (user installs these separately)
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PIL",
    "IPython",
    "notebook",
    "jupyter",
]

a = Analysis(
    ["src/envknit/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# One-file executable — everything packed into a single self-extracting binary
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="envknit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,   # set True on Linux/macOS to reduce size (may affect debug info)
    upx=False,     # UPX compression; disabled by default — enable if size matters
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,  # macOS only: emulate argv0 for app bundles
    target_arch=None,      # None = native arch; override with "x86_64" or "arm64"
    codesign_identity=None,
    entitlements_file=None,
)
