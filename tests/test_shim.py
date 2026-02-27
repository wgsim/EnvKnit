"""
Tests for isolation/shim.py.

Covers ShimConfig, ShimGenerator, ToolShimConfig, CLIShimGenerator,
ShellIntegration, ToolDispatcher, and convenience functions.
"""

import os
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


class TestShimConfig:
    def test_fields(self, tmp_path):
        cfg = ShimConfig(
            target_package="numpy",
            target_path=tmp_path / "site-packages",
            shim_path=tmp_path / "shims",
            environment="myenv",
        )
        assert cfg.target_package == "numpy"
        assert cfg.environment == "myenv"

    def test_tool_shim_config_shim_path(self, tmp_path):
        cfg = ToolShimConfig(tool_name="python", shim_dir=tmp_path / "shims")
        assert cfg.shim_path == tmp_path / "shims" / "python"

    def test_tool_shim_config_default_envknit_root(self, tmp_path):
        cfg = ToolShimConfig(tool_name="pip", shim_dir=tmp_path)
        assert cfg.envknit_root == Path.home() / ".envknit"


class TestShimGenerator:
    def test_default_output_dir(self):
        gen = ShimGenerator()
        assert gen.output_dir == Path(".envknit/shims")

    def test_custom_output_dir(self, tmp_path):
        gen = ShimGenerator(output_dir=tmp_path / "custom")
        assert gen.output_dir == tmp_path / "custom"

    def test_generate_creates_init_file(self, tmp_path):
        gen = ShimGenerator()
        cfg = ShimConfig(
            target_package="pandas",
            target_path=tmp_path / "site-packages",
            shim_path=tmp_path / "shims",
            environment="testenv",
        )
        shim_file = gen.generate(cfg)
        assert shim_file.exists()
        assert shim_file.name == "__init__.py"
        assert shim_file.parent.name == "pandas"

    def test_generate_shim_content(self, tmp_path):
        gen = ShimGenerator()
        cfg = ShimConfig(
            target_package="pandas",
            target_path=tmp_path / "site-packages",
            shim_path=tmp_path / "shims",
            environment="testenv",
        )
        shim_file = gen.generate(cfg)
        content = shim_file.read_text()
        assert "pandas" in content
        assert "testenv" in content
        assert str(tmp_path / "site-packages") in content
        assert "import_module" in content

    def test_generate_batch(self, tmp_path):
        gen = ShimGenerator()
        configs = [
            ShimConfig(
                target_package=pkg,
                target_path=tmp_path / "site-packages",
                shim_path=tmp_path / "shims",
                environment="env",
            )
            for pkg in ["numpy", "pandas"]
        ]
        paths = gen.generate_batch(configs)
        assert len(paths) == 2
        for p in paths:
            assert p.exists()

    def test_clean_specific_environment(self, tmp_path):
        gen = ShimGenerator(output_dir=tmp_path / "shims")
        env_dir = tmp_path / "shims" / "myenv"
        env_dir.mkdir(parents=True)
        (env_dir / "dummy.txt").write_text("x")
        gen.clean(environment="myenv")
        assert not env_dir.exists()

    def test_clean_all(self, tmp_path):
        gen = ShimGenerator(output_dir=tmp_path / "shims")
        shim_dir = tmp_path / "shims"
        shim_dir.mkdir(parents=True)
        (shim_dir / "someenv").mkdir()
        gen.clean()
        assert not shim_dir.exists()

    def test_clean_nonexistent_environment_is_noop(self, tmp_path):
        gen = ShimGenerator(output_dir=tmp_path / "shims")
        gen.clean(environment="nonexistent")

    def test_clean_nonexistent_output_dir_is_noop(self, tmp_path):
        gen = ShimGenerator(output_dir=tmp_path / "missing_shims")
        gen.clean()


class TestCLIShimGenerator:
    def test_default_shim_dir(self):
        gen = CLIShimGenerator()
        assert gen.shim_dir == Path.home() / ".envknit" / "shims"

    def test_custom_shim_dir(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        assert gen.shim_dir == tmp_path / "shims"

    def test_generate_shim_creates_file(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        path = gen.generate_shim("python")
        assert path.exists()
        assert path.name == "python"

    def test_generate_shim_is_executable(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        path = gen.generate_shim("pip")
        mode = path.stat().st_mode
        assert mode & stat.S_IXUSR
        assert mode & stat.S_IXGRP
        assert mode & stat.S_IXOTH

    def test_generate_shim_content_has_shebang(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        path = gen.generate_shim("mamba")
        content = path.read_text()
        assert "#!/usr/bin/env python3" in content

    def test_generate_shim_content_embeds_tool_name(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        path = gen.generate_shim("conda")
        content = path.read_text()
        assert "conda" in content

    def test_generate_all_shims_default(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        paths = gen.generate_all_shims()
        assert len(paths) == len(CLIShimGenerator.DEFAULT_TOOLS)
        for p in paths:
            assert p.exists()

    def test_generate_all_shims_custom_list(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        paths = gen.generate_all_shims(["mytool", "othertool"])
        assert len(paths) == 2
        assert (tmp_path / "shims" / "mytool").exists()

    def test_remove_shim_existing(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        gen.generate_shim("python")
        result = gen.remove_shim("python")
        assert result is True
        assert not (tmp_path / "shims" / "python").exists()

    def test_remove_shim_nonexistent(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        result = gen.remove_shim("nope")
        assert result is False

    def test_remove_all_shims(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        gen.generate_all_shims(["a", "b", "c"])
        count = gen.remove_all_shims()
        assert count == 3
        assert gen.list_shims() == []

    def test_remove_all_shims_empty_dir(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        count = gen.remove_all_shims()
        assert count == 0

    def test_list_shims_empty(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        assert gen.list_shims() == []

    def test_list_shims(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        gen.generate_all_shims(["python", "pip"])
        shims = gen.list_shims()
        assert set(shims) == {"python", "pip"}

    def test_list_shims_excludes_dotfiles(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        gen.generate_shim("python")
        (tmp_path / "shims" / ".hidden").write_text("x")
        shims = gen.list_shims()
        assert ".hidden" not in shims

    def test_is_installed_false_when_no_dir(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        assert gen.is_installed() is False

    def test_is_installed_true_after_generate(self, tmp_path):
        gen = CLIShimGenerator(shim_dir=tmp_path / "shims")
        gen.generate_shim("python")
        assert gen.is_installed() is True


class TestShellIntegration:
    def test_default_shim_dir(self):
        si = ShellIntegration()
        assert si.shim_dir == Path.home() / ".envknit" / "shims"

    def test_custom_shim_dir(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        assert si.shim_dir == tmp_path / "shims"

    def test_get_init_script_bash(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        script = si.get_init_script("bash")
        assert str(tmp_path / "shims") in script
        assert "PATH" in script
        assert "_envknit_cd" in script

    def test_get_init_script_zsh(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        script = si.get_init_script("zsh")
        assert "chpwd" in script
        assert "PATH" in script

    def test_get_init_script_fish(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        script = si.get_init_script("fish")
        assert "set -gx PATH" in script
        assert "on-variable PWD" in script

    def test_install_to_shell_creates_config(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".bashrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"bash": str(config_path)}):
            result = si._install_to_shell("bash")
        assert result is True
        content = config_path.read_text()
        assert ShellIntegration.MARKER_START in content
        assert ShellIntegration.MARKER_END in content

    def test_install_idempotent(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".bashrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"bash": str(config_path)}):
            si._install_to_shell("bash")
            result = si._install_to_shell("bash")
        assert result is True
        content = config_path.read_text()
        assert content.count(ShellIntegration.MARKER_START) == 1

    def test_uninstall_removes_block(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".zshrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"zsh": str(config_path)}):
            si._install_to_shell("zsh")
            result = si._uninstall_from_shell("zsh")
        assert result is True
        content = config_path.read_text()
        assert ShellIntegration.MARKER_START not in content

    def test_uninstall_nonexistent_config(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / "nonexistent.rc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"bash": str(config_path)}):
            result = si._uninstall_from_shell("bash")
        assert result is False

    def test_uninstall_not_installed(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".bashrc"
        config_path.write_text("# existing content\n")
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"bash": str(config_path)}):
            result = si._uninstall_from_shell("bash")
        assert result is False

    def test_detect_shell_zsh(self):
        si = ShellIntegration()
        with patch.dict(os.environ, {"SHELL": "/bin/zsh"}):
            assert si.detect_current_shell() == "zsh"

    def test_detect_shell_bash(self):
        si = ShellIntegration()
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            assert si.detect_current_shell() == "bash"

    def test_detect_shell_fish(self):
        si = ShellIntegration()
        with patch.dict(os.environ, {"SHELL": "/usr/bin/fish"}):
            assert si.detect_current_shell() == "fish"

    def test_detect_shell_unknown(self):
        si = ShellIntegration()
        with patch.dict(os.environ, {"SHELL": ""}):
            assert si.detect_current_shell() == "unknown"

    def test_get_path_export_bash(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        with patch.dict(os.environ, {"SHELL": "/bin/bash"}):
            export = si.get_path_export()
        assert "export PATH=" in export
        assert str(tmp_path / "shims") in export

    def test_get_path_export_fish(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        with patch.dict(os.environ, {"SHELL": "/usr/bin/fish"}):
            export = si.get_path_export()
        assert export.startswith("set -gx PATH")

    def test_install_bash_public_method(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".bashrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"bash": str(config_path)}):
            assert si.install_bash() is True

    def test_install_zsh_public_method(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".zshrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"zsh": str(config_path)}):
            assert si.install_zsh() is True

    def test_install_fish_public_method(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / "config.fish"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"fish": str(config_path)}):
            assert si.install_fish() is True

    def test_uninstall_bash(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".bashrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"bash": str(config_path)}):
            si.install_bash()
            assert si.uninstall_bash() is True

    def test_uninstall_zsh(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / ".zshrc"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"zsh": str(config_path)}):
            si.install_zsh()
            assert si.uninstall_zsh() is True

    def test_uninstall_fish(self, tmp_path):
        si = ShellIntegration(shim_dir=tmp_path / "shims")
        config_path = tmp_path / "config.fish"
        with patch.dict(ShellIntegration.SHELL_CONFIGS, {"fish": str(config_path)}):
            si.install_fish()
            assert si.uninstall_fish() is True


class TestToolDispatcher:
    def test_default_envknit_root(self):
        td = ToolDispatcher()
        assert td.envknit_root == Path.home() / ".envknit"

    def test_custom_envknit_root(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        assert td.envknit_root == tmp_path / ".envknit"

    def test_find_project_root_finds_envknit_yaml(self, tmp_path):
        (tmp_path / "envknit.yaml").write_text("packages: []")
        sub = tmp_path / "sub" / "sub2"
        sub.mkdir(parents=True)
        td = ToolDispatcher()
        result = td.find_project_root(start_path=sub)
        assert result == tmp_path

    def test_find_project_root_finds_dot_envknit_yaml(self, tmp_path):
        (tmp_path / ".envknit.yaml").write_text("packages: []")
        td = ToolDispatcher()
        result = td.find_project_root(start_path=tmp_path)
        assert result == tmp_path

    def test_find_project_root_returns_none_when_not_found(self, tmp_path):
        td = ToolDispatcher()
        result = td.find_project_root(start_path=tmp_path)
        assert result is None

    def test_find_lock_file_envknit_lock_yaml(self, tmp_path):
        lock = tmp_path / "envknit-lock.yaml"
        lock.write_text("locked: true")
        td = ToolDispatcher()
        result = td.find_lock_file(tmp_path)
        assert result == lock

    def test_find_lock_file_dot_envknit_lock_yaml(self, tmp_path):
        lock = tmp_path / ".envknit-lock.yaml"
        lock.write_text("locked: true")
        td = ToolDispatcher()
        result = td.find_lock_file(tmp_path)
        assert result == lock

    def test_find_lock_file_envknit_lock(self, tmp_path):
        lock = tmp_path / "envknit.lock"
        lock.write_text("locked: true")
        td = ToolDispatcher()
        result = td.find_lock_file(tmp_path)
        assert result == lock

    def test_find_lock_file_returns_none(self, tmp_path):
        td = ToolDispatcher()
        result = td.find_lock_file(tmp_path)
        assert result is None

    def test_get_tool_path_no_project_root(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        result = td.get_tool_path("python", project_root=None)
        assert result is None

    def test_get_tool_path_finds_in_store(self, tmp_path):
        envknit_root = tmp_path / ".envknit"
        pkg_dir = envknit_root / "packages" / "numpy" / "1.24.0" / "env" / "bin"
        pkg_dir.mkdir(parents=True)
        python_tool = pkg_dir / "python"
        python_tool.write_text("#!/bin/bash")
        python_tool.chmod(0o755)

        (tmp_path / "envknit.yaml").write_text("packages: []")
        td = ToolDispatcher(envknit_root=envknit_root)
        result = td.get_tool_path("python", project_root=tmp_path)
        assert result == python_tool

    def test_dispatch_calls_subprocess(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("envknit.isolation.shim.subprocess.run", return_value=mock_result) as mock_run:
            ret = td.dispatch("python", ["--version"])
        assert ret == 0
        mock_run.assert_called_once_with(["python", "--version"])

    def test_dispatch_file_not_found(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        with patch("envknit.isolation.shim.subprocess.run", side_effect=FileNotFoundError()):
            ret = td.dispatch("notarealtool", [])
        assert ret == 127

    def test_dispatch_generic_exception(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        with patch("envknit.isolation.shim.subprocess.run", side_effect=RuntimeError("boom")):
            ret = td.dispatch("python", [])
        assert ret == 1

    def test_find_tool_in_store_missing_packages_dir(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        result = td._find_tool_in_store("python", tmp_path)
        assert result is None

    def test_find_tool_in_composite_env_no_projects_dir(self, tmp_path):
        td = ToolDispatcher(envknit_root=tmp_path / ".envknit")
        result = td._find_tool_in_composite_env("python", tmp_path)
        assert result is None

    def test_find_tool_in_composite_env_no_lock_file(self, tmp_path):
        envknit_root = tmp_path / ".envknit"
        (envknit_root / "projects").mkdir(parents=True)
        td = ToolDispatcher(envknit_root=envknit_root)
        result = td._find_tool_in_composite_env("python", tmp_path)
        assert result is None

    def test_find_tool_in_composite_env_bad_lock_file(self, tmp_path):
        envknit_root = tmp_path / ".envknit"
        (envknit_root / "projects").mkdir(parents=True)
        lock = tmp_path / "envknit.lock"
        lock.write_text(": invalid: yaml")
        td = ToolDispatcher(envknit_root=envknit_root)
        result = td._find_tool_in_composite_env("python", tmp_path)
        assert result is None


class TestConvenienceFunctions:
    def test_get_shim_generator(self):
        gen = get_shim_generator()
        assert isinstance(gen, CLIShimGenerator)

    def test_get_shell_integration(self):
        si = get_shell_integration()
        assert isinstance(si, ShellIntegration)

    def test_get_tool_dispatcher(self):
        td = get_tool_dispatcher()
        assert isinstance(td, ToolDispatcher)
