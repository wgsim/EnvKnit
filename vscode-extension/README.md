# EnvKnit VS Code Extension

VS Code integration for [EnvKnit](https://github.com/envknit/envknit), a multi-version Python package manager.

## Features

- **YAML validation** for `envknit.yaml` and `envknit.lock.yaml` via JSON Schema (requires the [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml))
- **Command palette commands**:
  - `EnvKnit: Install Dependencies` — runs `envknit install` in the workspace root
  - `EnvKnit: Add Package` — prompts for a package name, then runs `envknit add <name>`
  - `EnvKnit: Show Status` — runs `envknit status` and displays output in the Output Channel

## Requirements

- The `envknit` CLI binary must be installed and on your `PATH`, or configured via the `envknit.cliPath` setting.
- The [YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) (`redhat.vscode-yaml`) for schema validation.

## Settings

| Setting | Default | Description |
|---|---|---|
| `envknit.cliPath` | `"envknit"` | Path to the `envknit` CLI binary. Override if not on PATH (e.g. `/usr/local/bin/envknit`). |

## Schema Validation

Once the YAML extension is installed, opening `envknit.yaml` or `envknit.lock.yaml` will automatically provide:

- Property autocompletion
- Inline error highlighting for invalid values
- Hover documentation for each field
