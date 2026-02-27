"""Unit tests for envknit.utils.version (targeting 100% coverage)."""

import pytest

from envknit.utils.version import (
    VERSION_INFO,
    VersionInfo,
    __version__,
    compare_versions,
    get_version_info,
    parse_version,
)


# ---------------------------------------------------------------------------
# VersionInfo
# ---------------------------------------------------------------------------


class TestVersionInfo:
    def test_fields(self):
        v = VersionInfo(1, 2, 3)
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_str(self):
        assert str(VersionInfo(1, 2, 3)) == "1.2.3"

    def test_str_zeros(self):
        assert str(VersionInfo(0, 0, 0)) == "0.0.0"

    def test_named_tuple_equality(self):
        assert VersionInfo(1, 2, 3) == VersionInfo(1, 2, 3)
        assert VersionInfo(1, 2, 3) != VersionInfo(1, 2, 4)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_version_info_type(self):
        assert isinstance(VERSION_INFO, VersionInfo)

    def test_version_info_values(self):
        assert VERSION_INFO.major == 0
        assert VERSION_INFO.minor == 1
        assert VERSION_INFO.patch == 0

    def test_dunder_version_matches_version_info(self):
        assert __version__ == str(VERSION_INFO)


# ---------------------------------------------------------------------------
# get_version_info
# ---------------------------------------------------------------------------


class TestGetVersionInfo:
    def test_returns_version_info(self):
        result = get_version_info()
        assert isinstance(result, VersionInfo)

    def test_returns_module_constant(self):
        assert get_version_info() is VERSION_INFO


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------


class TestParseVersion:
    def test_three_part(self):
        v = parse_version("1.2.3")
        assert v == VersionInfo(1, 2, 3)

    def test_two_part_patch_defaults_to_zero(self):
        v = parse_version("2.5")
        assert v == VersionInfo(2, 5, 0)

    def test_zero_version(self):
        assert parse_version("0.0.0") == VersionInfo(0, 0, 0)

    def test_large_numbers(self):
        assert parse_version("10.20.30") == VersionInfo(10, 20, 30)

    def test_too_few_parts_raises(self):
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("1")

    def test_too_many_parts_raises(self):
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("1.2.3.4")

    def test_non_numeric_major_raises(self):
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("a.2.3")

    def test_non_numeric_minor_raises(self):
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("1.b.3")

    def test_non_numeric_patch_raises(self):
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("1.2.c")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid version string"):
            parse_version("")


# ---------------------------------------------------------------------------
# compare_versions
# ---------------------------------------------------------------------------


class TestCompareVersions:
    def test_equal(self):
        assert compare_versions(VersionInfo(1, 2, 3), VersionInfo(1, 2, 3)) == 0

    def test_v1_less_major(self):
        assert compare_versions(VersionInfo(0, 9, 9), VersionInfo(1, 0, 0)) == -1

    def test_v1_greater_major(self):
        assert compare_versions(VersionInfo(2, 0, 0), VersionInfo(1, 9, 9)) == 1

    def test_v1_less_minor(self):
        assert compare_versions(VersionInfo(1, 1, 5), VersionInfo(1, 2, 0)) == -1

    def test_v1_greater_minor(self):
        assert compare_versions(VersionInfo(1, 3, 0), VersionInfo(1, 2, 9)) == 1

    def test_v1_less_patch(self):
        assert compare_versions(VersionInfo(1, 2, 2), VersionInfo(1, 2, 3)) == -1

    def test_v1_greater_patch(self):
        assert compare_versions(VersionInfo(1, 2, 4), VersionInfo(1, 2, 3)) == 1

    def test_zeros_equal(self):
        assert compare_versions(VersionInfo(0, 0, 0), VersionInfo(0, 0, 0)) == 0
