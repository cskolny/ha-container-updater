"""Tests for coordinator.py — version parsing, comparison, and GitHub API fetch."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so the module can be imported without a real HA environment
# ---------------------------------------------------------------------------
import sys, types

# Stub out all homeassistant.* imports the coordinator needs
for mod in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

# homeassistant.const needs __version__
sys.modules["homeassistant.const"].__version__ = "2026.3.1"

# DataUpdateCoordinator stub
class _FakeCoordinator:
    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass
        self.data = None
        self.last_update_success = True

    async def async_config_entry_first_refresh(self):
        pass

    async def async_request_refresh(self):
        pass

sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _FakeCoordinator

class _UpdateFailed(Exception):
    pass

sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = _UpdateFailed
sys.modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = MagicMock()

# Now we can import the module under test
from custom_components.ha_container_updater.coordinator import (  # noqa: E402
    _is_update_available,
    _parse_version,
)


# ===========================================================================
# _parse_version
# ===========================================================================


class TestParseVersion:
    def test_standard_calver(self):
        assert _parse_version("2026.3.1") == (2026, 3, 1)

    def test_leading_v(self):
        assert _parse_version("v2026.3.1") == (2026, 3, 1)

    def test_two_part(self):
        """HA sometimes ships two-part versions like 2026.3 (no patch)."""
        assert _parse_version("2026.3") == (2026, 3)

    def test_whitespace_stripped(self):
        assert _parse_version("  2026.3.1  ") == (2026, 3, 1)

    def test_returns_none_on_non_numeric(self):
        """Pre-release tags like 2026.3.0b1 should return None gracefully."""
        assert _parse_version("2026.3.0b1") is None

    def test_returns_none_on_empty(self):
        assert _parse_version("") is None

    def test_returns_none_on_garbage(self):
        assert _parse_version("not-a-version") is None


# ===========================================================================
# _is_update_available
# ===========================================================================


class TestIsUpdateAvailable:
    # ── Numeric comparison (normal path) ───────────────────────────────────

    def test_newer_patch(self):
        assert _is_update_available("2026.3.0", "2026.3.1") is True

    def test_newer_minor(self):
        assert _is_update_available("2026.3.1", "2026.4.0") is True

    def test_newer_year(self):
        assert _is_update_available("2025.12.0", "2026.1.0") is True

    def test_same_version(self):
        assert _is_update_available("2026.3.1", "2026.3.1") is False

    def test_older_patch(self):
        """Latest is *older* than installed — should not report an update."""
        assert _is_update_available("2026.3.1", "2026.3.0") is False

    def test_older_minor(self):
        assert _is_update_available("2026.4.0", "2026.3.9") is False

    # ── Leading-v stripped ──────────────────────────────────────────────────

    def test_latest_has_leading_v(self):
        """GitHub tags often include a leading 'v'."""
        assert _is_update_available("2026.3.0", "v2026.3.1") is True

    def test_installed_has_leading_v(self):
        assert _is_update_available("v2026.3.0", "2026.3.1") is True

    # ── Two-part versions ───────────────────────────────────────────────────

    def test_two_vs_three_part_newer(self):
        """(2026, 4) > (2026, 3, 1) — month bump is a newer release."""
        assert _is_update_available("2026.3.1", "2026.4") is True

    def test_two_vs_three_part_older(self):
        assert _is_update_available("2026.4.0", "2026.3") is False

    # ── Fallback to string comparison when parsing fails ───────────────────

    def test_parse_failure_different_strings(self):
        """Falls back to string inequality — different strings → True."""
        assert _is_update_available("2026.3.0b1", "2026.3.0b2") is True

    def test_parse_failure_same_strings(self):
        """Falls back to string inequality — same strings → False."""
        assert _is_update_available("2026.3.0b1", "2026.3.0b1") is False
