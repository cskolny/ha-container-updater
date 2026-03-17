"""Tests for config_flow.py — trigger directory validation and schema building."""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stubs for homeassistant imports
# ---------------------------------------------------------------------------
for mod in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

# config_entries needs ConfigFlow, OptionsFlow, and ConfigFlowResult
_ce = sys.modules["homeassistant.config_entries"]

class _ConfigFlow:
    pass

class _OptionsFlow:
    pass

_ce.ConfigFlow = _ConfigFlow
_ce.OptionsFlow = _OptionsFlow
_ce.ConfigFlowResult = dict  # type alias stub

# voluptuous is a real dependency — install with: pip install voluptuous
import voluptuous as vol  # noqa: E402

# callback decorator stub
sys.modules["homeassistant.core"].callback = lambda f: f

from custom_components.ha_container_updater.config_flow import _validate_trigger_dir  # noqa: E402
from custom_components.ha_container_updater.const import (  # noqa: E402
    DEFAULT_COMPOSE_DIR,
    DEFAULT_COMPOSE_FILE,
    DEFAULT_HA_SERVICE_NAME,
    DEFAULT_PRUNE_IMAGES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRIGGER_FILE,
)


# ===========================================================================
# _validate_trigger_dir
# ===========================================================================


class TestValidateTriggerDir:
    def test_valid_writable_directory(self, tmp_path):
        trigger = str(tmp_path / "ha-container-updater-trigger")
        assert _validate_trigger_dir(trigger) is None

    def test_missing_directory(self, tmp_path):
        trigger = str(tmp_path / "nonexistent" / "trigger")
        assert _validate_trigger_dir(trigger) == "trigger_dir_not_found"

    def test_root_level_path(self):
        """A path directly in / (e.g. /trigger) should resolve to '/' which exists."""
        # /trigger doesn't exist as a dir but its parent '/' does and is readable.
        # We only check the parent exists; writability of '/' may vary by OS.
        result = _validate_trigger_dir("/trigger")
        # On most systems / exists but may not be writable — accept either outcome
        assert result in (None, "trigger_dir_not_writable")

    def test_unwritable_directory(self, tmp_path):
        """Simulate an unwritable directory by patching os.access."""
        trigger = str(tmp_path / "trigger")
        with patch("os.access", return_value=False):
            assert _validate_trigger_dir(trigger) == "trigger_dir_not_writable"

    def test_empty_dirname_falls_back_to_root(self):
        """A bare filename with no directory component uses '/' as parent."""
        with patch("os.path.isdir", return_value=True), \
             patch("os.access", return_value=True):
            assert _validate_trigger_dir("trigger") is None


# ===========================================================================
# Default constant values — guard against accidental changes
# ===========================================================================


class TestDefaults:
    def test_default_trigger_file(self):
        assert DEFAULT_TRIGGER_FILE == "/tmp/ha-container-updater-trigger"

    def test_default_compose_dir(self):
        assert DEFAULT_COMPOSE_DIR == "/home/pi/homeassistant"

    def test_default_compose_file(self):
        assert DEFAULT_COMPOSE_FILE == "docker-compose.yml"

    def test_default_ha_service_name(self):
        assert DEFAULT_HA_SERVICE_NAME == "homeassistant"

    def test_default_prune_images(self):
        assert DEFAULT_PRUNE_IMAGES is True

    def test_default_scan_interval(self):
        assert DEFAULT_SCAN_INTERVAL == 3600

    def test_scan_interval_minimum_is_300(self):
        """The schema enforces min=300; verify the default satisfies it."""
        assert DEFAULT_SCAN_INTERVAL >= 300

    def test_scan_interval_maximum_is_86400(self):
        assert DEFAULT_SCAN_INTERVAL <= 86400
