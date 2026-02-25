#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# build-cli.sh — Build the envknit standalone binary using PyInstaller
#
# Usage:
#   ./scripts/build-cli.sh [--clean] [--strip] [--upx]
#
# Options:
#   --clean   Remove dist/ and build/ before building
#   --strip   Strip debug symbols from the binary (Linux/macOS only)
#   --upx     Enable UPX compression (requires upx in PATH)
#
# Output:
#   dist/envknit          (Linux/macOS)
#   dist/envknit.exe      (Windows)
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SPEC_FILE="${PROJECT_ROOT}/envknit-cli.spec"
DIST_DIR="${PROJECT_ROOT}/dist"
BUILD_DIR="${PROJECT_ROOT}/build"

# ── Parse arguments ──────────────────────────────────────────────────────────
DO_CLEAN=false
DO_STRIP=false
DO_UPX=false

for arg in "$@"; do
    case "$arg" in
        --clean) DO_CLEAN=true ;;
        --strip) DO_STRIP=true ;;
        --upx)   DO_UPX=true ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Usage: $0 [--clean] [--strip] [--upx]" >&2
            exit 1
            ;;
    esac
done

# ── Pre-flight ────────────────────────────────────────────────────────────────
echo "==> EnvKnit CLI builder"
echo "    Project root : ${PROJECT_ROOT}"
echo "    Spec file    : ${SPEC_FILE}"

if [[ ! -f "${SPEC_FILE}" ]]; then
    echo "ERROR: spec file not found: ${SPEC_FILE}" >&2
    exit 1
fi

# Ensure PyInstaller is available
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "==> PyInstaller not found. Installing build extras..."
    pip install "pyinstaller>=6.0"
fi

PYINSTALLER_VERSION=$(python -c "import PyInstaller; print(PyInstaller.__version__)")
echo "    PyInstaller  : ${PYINSTALLER_VERSION}"

# Ensure CLI extras are installed (click, pyyaml, rich)
if ! python -c "import click, yaml, rich" 2>/dev/null; then
    echo "==> CLI extras not found. Installing envknit[cli]..."
    pip install -e "${PROJECT_ROOT}[cli]"
fi

# ── Clean ─────────────────────────────────────────────────────────────────────
if [[ "${DO_CLEAN}" == "true" ]]; then
    echo "==> Cleaning dist/ and build/..."
    rm -rf "${DIST_DIR}" "${BUILD_DIR}"
fi

# ── Patch spec for strip/upx flags ───────────────────────────────────────────
# PyInstaller reads strip/upx from the spec file. We use sed to toggle them
# rather than maintaining separate spec variants.
STRIP_VAL="False"
UPX_VAL="False"
[[ "${DO_STRIP}" == "true" ]] && STRIP_VAL="True"
[[ "${DO_UPX}" == "true" ]]   && UPX_VAL="True"

# Build in a temp copy so we don't dirty the committed spec
TMP_SPEC=$(mktemp /tmp/envknit-cli-XXXXXX.spec)
trap 'rm -f "${TMP_SPEC}"' EXIT

sed -e "s/strip=False/strip=${STRIP_VAL}/" \
    -e "s/upx=False/upx=${UPX_VAL}/" \
    "${SPEC_FILE}" > "${TMP_SPEC}"

# ── Build ─────────────────────────────────────────────────────────────────────
echo "==> Running PyInstaller..."
cd "${PROJECT_ROOT}"
python -m PyInstaller \
    --noconfirm \
    --distpath "${DIST_DIR}" \
    --workpath "${BUILD_DIR}" \
    "${TMP_SPEC}"

# ── Report ────────────────────────────────────────────────────────────────────
if [[ -f "${DIST_DIR}/envknit" ]]; then
    BINARY="${DIST_DIR}/envknit"
elif [[ -f "${DIST_DIR}/envknit.exe" ]]; then
    BINARY="${DIST_DIR}/envknit.exe"
else
    echo "ERROR: expected binary not found in ${DIST_DIR}" >&2
    exit 1
fi

BINARY_SIZE=$(du -sh "${BINARY}" | cut -f1)
echo ""
echo "==> Build complete"
echo "    Binary : ${BINARY}"
echo "    Size   : ${BINARY_SIZE}"
echo ""
echo "Smoke test:"
"${BINARY}" --version
