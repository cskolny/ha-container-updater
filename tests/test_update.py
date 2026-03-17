"""Tests for update.py — trigger file writing and update entity helpers."""

from __future__ import annotations

import json
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
    "homeassistant.components",
    "homeassistant.components.update",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.util",
    "homeassistant.util.dt",
]:
    if mod not in sys.modules:
        sys.modules[mod] = types.ModuleType(mod)

# UpdateEntity stub
class _UpdateEntity:
    pass

class _UpdateEntityDescription:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class _UpdateEntityFeature:
    INSTALL = 1
    BACKUP = 2
    PROGRESS = 4

sys.modules["homeassistant.components.update"].UpdateEntity = _UpdateEntity
sys.modules["homeassistant.components.update"].UpdateEntityDescription = _UpdateEntityDescription
sys.modules["homeassistant.components.update"].UpdateEntityFeature = _UpdateEntityFeature

# CoordinatorEntity stub
class _CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator
    def async_write_ha_state(self):
        pass

sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _CoordinatorEntity

class _HomeAssistantError(Exception):
    pass

sys.modules["homeassistant.exceptions"].HomeAssistantError = _HomeAssistantError

# dt_util stub
import datetime as _dt
_dt_mod = sys.modules["homeassistant.util.dt"]
_dt_mod.utcnow = lambda: _dt.datetime.now(_dt.timezone.utc)

sys.modules["homeassistant.config_entries"].ConfigEntry = MagicMock

from custom_components.ha_container_updater.update import HAContainerUpdateEntity  # noqa: E402
from custom_components.ha_container_updater.const import TRIGGER_FILE_MAGIC  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(tmp_path, options=None):
    """Return a minimally configured HAContainerUpdateEntity for testing."""
    trigger = str(tmp_path / "ha-container-updater-trigger")
    lock = str(tmp_path / "ha-container-updater.lock")

    coordinator = MagicMock()
    coordinator.data = {
        "installed_version": "2026.3.0",
        "latest_version": "2026.3.1",
        "update_available": True,
        "release_url": "https://github.com/home-assistant/core/releases/tag/2026.3.1",
        "rate_limit_remaining": 55,
    }
    coordinator.last_update_success = True

    entry = MagicMock()
    defaults = {
        "trigger_file_path": trigger,
        "lock_file": lock,
        "compose_dir": "/home/pi/homeassistant",
        "compose_file": "docker-compose.yml",
        "ha_service_name": "homeassistant",
        "prune_images": True,
    }
    merged = {**(options or {}), **defaults}
    # options.get falls through to data.get
    entry.options.get = lambda key, default=None: merged.get(key, default)
    entry.data.get = lambda key, default=None: merged.get(key, default)

    entity = HAContainerUpdateEntity.__new__(HAContainerUpdateEntity)
    _CoordinatorEntity.__init__(entity, coordinator)
    entity._entry = entry
    entity._attr_unique_id = "ha_container_updater_update"
    entity._attr_supported_features = 7
    entity._attr_in_progress = False
    entity._trigger_path = trigger
    entity._lock_file = lock
    entity._compose_dir = "/home/pi/homeassistant"
    entity._compose_file = "docker-compose.yml"
    entity._ha_service_name = "homeassistant"
    entity._prune_images = True
    entity._last_update_requested = None
    entity.hass = MagicMock()
    return entity


# ===========================================================================
# _write_trigger_file (static method — pure filesystem, no HA needed)
# ===========================================================================


class TestWriteTriggerFile:
    def test_writes_valid_json_payload(self, tmp_path):
        path = str(tmp_path / "trigger")
        payload = json.dumps({"magic": TRIGGER_FILE_MAGIC, "compose_dir": "/home/pi/homeassistant"})
        HAContainerUpdateEntity._write_trigger_file(path, payload)
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["magic"] == TRIGGER_FILE_MAGIC
        assert data["compose_dir"] == "/home/pi/homeassistant"

    def test_file_ends_with_newline(self, tmp_path):
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, "{}")
        with open(path) as f:
            content = f.read()
        assert content.endswith("\n")

    def test_tmp_file_cleaned_up_on_success(self, tmp_path):
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, "{}")
        assert not os.path.exists(path + ".tmp")

    def test_raises_oserror_on_missing_directory(self, tmp_path):
        path = str(tmp_path / "nonexistent" / "trigger")
        with pytest.raises(OSError, match="does not exist"):
            HAContainerUpdateEntity._write_trigger_file(path, "{}")

    def test_atomic_replace(self, tmp_path):
        """The final file must exist and the .tmp file must not."""
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, '{"key": "value"}')
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")

    def test_overwrites_existing_trigger(self, tmp_path):
        """Calling write twice should overwrite cleanly."""
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, '{"first": true}')
        HAContainerUpdateEntity._write_trigger_file(path, '{"second": true}')
        with open(path) as f:
            data = json.load(f)
        assert data == {"second": True}


# ===========================================================================
# Entity properties
# ===========================================================================


class TestEntityProperties:
    def test_installed_version(self, tmp_path):
        entity = _make_entity(tmp_path)
        assert entity.installed_version == "2026.3.0"

    def test_latest_version(self, tmp_path):
        entity = _make_entity(tmp_path)
        assert entity.latest_version == "2026.3.1"

    def test_available_true_when_coordinator_ok(self, tmp_path):
        entity = _make_entity(tmp_path)
        assert entity.available is True

    def test_available_false_when_coordinator_fails(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.last_update_success = False
        assert entity.available is False

    def test_in_progress_default_false(self, tmp_path):
        entity = _make_entity(tmp_path)
        assert entity.in_progress is False

    def test_title_is_home_assistant_core(self, tmp_path):
        entity = _make_entity(tmp_path)
        assert entity.title == "Home Assistant Core"

    def test_release_url(self, tmp_path):
        entity = _make_entity(tmp_path)
        assert "2026.3.1" in entity.release_url

    def test_installed_version_none_when_no_data(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.installed_version is None

    def test_latest_version_none_when_no_data(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.latest_version is None

    def test_release_url_none_when_no_data(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.release_url is None

    def test_release_summary_contains_version(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.hass.states.async_all = MagicMock(return_value=[])
        assert "2026.3.1" in entity.release_summary

    def test_release_summary_none_when_no_update(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.data["update_available"] = False
        assert entity.release_summary is None

    def test_release_summary_none_when_no_data(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.release_summary is None


# ===========================================================================
# extra_state_attributes
# ===========================================================================


class TestExtraStateAttributes:
    def test_contains_all_expected_keys(self, tmp_path):
        entity = _make_entity(tmp_path)
        attrs = entity.extra_state_attributes
        for key in [
            "trigger_file_path",
            "compose_dir",
            "compose_file",
            "ha_service_name",
            "prune_images",
            "lock_file",
            "last_update_requested",
            "in_progress",
            "github_rate_limit_remaining",
        ]:
            assert key in attrs, f"Missing key: {key}"

    def test_rate_limit_omitted_when_none(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity.coordinator.data["rate_limit_remaining"] = None
        assert "github_rate_limit_remaining" not in entity.extra_state_attributes

    def test_in_progress_reflects_attr(self, tmp_path):
        entity = _make_entity(tmp_path)
        entity._attr_in_progress = True
        assert entity.extra_state_attributes["in_progress"] is True


# ===========================================================================
# Trigger file magic string
# ===========================================================================


class TestMagicString:
    def test_magic_string_value(self):
        assert TRIGGER_FILE_MAGIC == "ha_container_updater_REQUESTED"

    def test_trigger_payload_contains_magic(self, tmp_path):
        """The payload written by async_install must include the magic string."""
        path = str(tmp_path / "trigger")
        payload = json.dumps({
            "magic": TRIGGER_FILE_MAGIC,
            "compose_dir": "/home/pi/homeassistant",
            "compose_file": "docker-compose.yml",
            "service_name": "homeassistant",
            "prune_images": True,
        })
        HAContainerUpdateEntity._write_trigger_file(path, payload)
        with open(path) as f:
            data = json.load(f)
        assert data["magic"] == TRIGGER_FILE_MAGIC
