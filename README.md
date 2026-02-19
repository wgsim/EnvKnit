# EnvKnit

Multi-environment package manager for Python with dependency isolation.

## Overview

EnvKnit is a package manager that enables multiple isolated environments within a single project. It provides:

- **Dependency Isolation**: Each package can have its own isolated dependency tree
- **Multi-backend Support**: Works with conda, pip, and other package managers
- **Conflict Resolution**: Automatically resolves version conflicts between environments
- **Import Isolation**: Shim-based import system for runtime isolation

## Installation

```bash
# Using pip
pip install envknit

# Using conda
conda install -c conda-forge envknit

# From source
git clone https://github.com/envknit/envknit.git
cd envknit
pip install -e ".[dev]"
```

## Quick Start

### Initialize a new project

```bash
envknit init
```

This creates an `envknit.yaml` configuration file in your project.

### Add packages

```bash
# Add a package to the default environment
envknit add numpy

# Add a package to a specific environment
envknit add pandas --env data-analysis

# Add a package with version constraint
envknit add "scipy>=1.10.0" --env scientific
```

### Install dependencies

```bash
# Install all dependencies
envknit install

# Install dependencies for a specific environment
envknit install --env data-analysis
```

### Run commands in isolated environment

```bash
# Run a script with isolated imports
envknit run python my_script.py

# Run with a specific environment
envknit run --env data-analysis python analyze.py
```

### Manage environments

```bash
# List all environments
envknit env list

# Create a new environment
envknit env create my-env

# Remove an environment
envknit env remove my-env
```

## Configuration

EnvKnit uses `envknit.yaml` for project configuration:

```yaml
name: my-project
version: 1.0.0

environments:
  default:
    python: "3.11"
    packages:
      - requests>=2.28.0

  data-analysis:
    python: "3.11"
    packages:
      - pandas>=2.0.0
      - numpy>=1.24.0
      - matplotlib>=3.7.0

  scientific:
    python: "3.11"
    packages:
      - scipy>=1.10.0
      - sympy>=1.12

backends:
  conda:
    channels:
      - conda-forge
      - defaults
```

## Project Structure

```
envknit/
├── core/           # Core resolution and locking logic
├── isolation/      # Import hooks and shims for isolation
├── backends/       # Package manager backends (conda, pip, etc.)
├── storage/        # Environment storage management
├── cli/            # Command-line interface
├── config/         # Configuration schema and parsing
└── utils/          # Utility functions
```

## Development

```bash
# Clone the repository
git clone https://github.com/envknit/envknit.git
cd envknit

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=envknit --cov-report=html
```

## License

MIT License - see [LICENSE](LICENSE) for details.
