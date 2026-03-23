"""Tests for coordinator.py — version parsing and comparison logic."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without a real HA environment.
# (conftest.py installs most stubs; we top-up any that coordinator.py needs.)
# ---------------------------------------------------------------------------
for _mod in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

sys.modules["homeassistant.const"].__version__ = "2026.3.3"  # type: ignore[attr-defined]


class _FakeCoordinator:
    """Minimal DataUpdateCoordinator stand-in for import purposes."""

    def __init__(
        self,
        hass: object,
        logger: object,
        *,
        name: str,
        update_interval: object,
    ) -> None:
        self.hass = hass
        self.data: object = None
        self.last_update_success: bool = True

    async def async_config_entry_first_refresh(self) -> None:
        """No-op stub."""

    async def async_request_refresh(self) -> None:
        """No-op stub."""


class _UpdateFailed(Exception):
    """Stub for homeassistant.helpers.update_coordinator.UpdateFailed."""


sys.modules[
    "homeassistant.helpers.update_coordinator"
].DataUpdateCoordinator = _FakeCoordinator  # type: ignore[attr-defined]
sys.modules[
    "homeassistant.helpers.update_coordinator"
].UpdateFailed = _UpdateFailed  # type: ignore[attr-defined]
sys.modules[
    "homeassistant.helpers.aiohttp_client"
].async_get_clientsession = MagicMock()  # type: ignore[attr-defined]

# This import must follow the stub setup above (E402 suppressed in pyproject.toml per-file-ignores).
from custom_components.ha_container_updater.coordinator import (
    _is_update_available,
    _parse_version,
)


# ===========================================================================
# _parse_version
# ===========================================================================


class TestParseVersion:
    """Unit tests for the _parse_version helper."""

    def test_standard_calver(self) -> None:
        """Standard three-part CalVer parses to a three-element tuple."""
        assert _parse_version("2026.3.1") == (2026, 3, 1)

    def test_leading_v_stripped(self) -> None:
        """A leading 'v' is stripped before parsing."""
        assert _parse_version("v2026.3.1") == (2026, 3, 1)

    def test_two_part_version(self) -> None:
        """HA sometimes ships two-part versions like 2026.3 (no patch)."""
        assert _parse_version("2026.3") == (2026, 3)

    def test_whitespace_stripped(self) -> None:
        """Leading and trailing whitespace is ignored."""
        assert _parse_version("  2026.3.1  ") == (2026, 3, 1)

    def test_returns_none_on_non_numeric(self) -> None:
        """Pre-release tags such as '2026.3.0b1' return None gracefully."""
        assert _parse_version("2026.3.0b1") is None

    def test_returns_none_on_empty_string(self) -> None:
        """An empty string returns None without raising."""
        assert _parse_version("") is None

    def test_returns_none_on_garbage(self) -> None:
        """Completely non-version strings return None."""
        assert _parse_version("not-a-version") is None


# ===========================================================================
# _is_update_available
# ===========================================================================


class TestIsUpdateAvailable:
    """Unit tests for the _is_update_available helper."""

    # ── Numeric comparison (normal path) ───────────────────────────────────

    def test_newer_patch(self) -> None:
        assert _is_update_available("2026.3.0", "2026.3.1") is True

    def test_newer_minor(self) -> None:
        assert _is_update_available("2026.3.1", "2026.4.0") is True

    def test_newer_year(self) -> None:
        assert _is_update_available("2025.12.0", "2026.1.0") is True

    def test_same_version(self) -> None:
        assert _is_update_available("2026.3.1", "2026.3.1") is False

    def test_older_patch_is_not_update(self) -> None:
        """Latest is *older* than installed — must not report an update."""
        assert _is_update_available("2026.3.1", "2026.3.0") is False

    def test_older_minor_is_not_update(self) -> None:
        assert _is_update_available("2026.4.0", "2026.3.9") is False

    # ── Leading-v stripped ──────────────────────────────────────────────────

    def test_latest_has_leading_v(self) -> None:
        """GitHub tags often include a leading 'v'."""
        assert _is_update_available("2026.3.0", "v2026.3.1") is True

    def test_installed_has_leading_v(self) -> None:
        assert _is_update_available("v2026.3.0", "2026.3.1") is True

    # ── Two-part versions ───────────────────────────────────────────────────

    def test_two_vs_three_part_newer(self) -> None:
        """(2026, 4) > (2026, 3, 1) — a month bump is a newer release."""
        assert _is_update_available("2026.3.1", "2026.4") is True

    def test_two_vs_three_part_older(self) -> None:
        assert _is_update_available("2026.4.0", "2026.3") is False

    # ── Fallback to string comparison when parsing fails ───────────────────

    def test_parse_failure_different_strings(self) -> None:
        """Falls back to string inequality — different strings → True."""
        assert _is_update_available("2026.3.0b1", "2026.3.0b2") is True

    def test_parse_failure_same_strings(self) -> None:
        """Falls back to string inequality — identical strings → False."""
        assert _is_update_available("2026.3.0b1", "2026.3.0b1") is False
