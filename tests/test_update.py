"""Tests for update.py — trigger file writing and update entity properties."""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stubs for homeassistant imports (conftest.py installs most; top-up here).
# ---------------------------------------------------------------------------
for _mod in [
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
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)


class _UpdateEntity:
    pass


class _UpdateEntityDescription:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class _UpdateEntityFeature:
    INSTALL = 1
    BACKUP = 2
    PROGRESS = 4


_upd = sys.modules["homeassistant.components.update"]
_upd.UpdateEntity = _UpdateEntity  # type: ignore[attr-defined]
_upd.UpdateEntityDescription = _UpdateEntityDescription  # type: ignore[attr-defined]
_upd.UpdateEntityFeature = _UpdateEntityFeature  # type: ignore[attr-defined]


class _CoordinatorEntity:
    def __init__(self, coordinator: object) -> None:
        self.coordinator = coordinator

    def async_write_ha_state(self) -> None:
        pass

    # Required so CoordinatorEntity[HAContainerUpdateCoordinator] is subscriptable
    # at class-definition time when update.py is imported.
    def __class_getitem__(cls, item: object) -> type:
        return cls


sys.modules[
    "homeassistant.helpers.update_coordinator"
].CoordinatorEntity = _CoordinatorEntity  # type: ignore[attr-defined]


class _HomeAssistantError(Exception):
    pass


_exc = sys.modules["homeassistant.exceptions"]
_exc.HomeAssistantError = _HomeAssistantError  # type: ignore[attr-defined]

_dt_mod = sys.modules["homeassistant.util.dt"]
_dt_mod.utcnow = lambda: _dt.datetime.now(_dt.UTC)  # type: ignore[attr-defined]

sys.modules["homeassistant.config_entries"].ConfigEntry = MagicMock  # type: ignore[attr-defined]

# Imports below must follow stub setup (E402 + I001 suppressed via pyproject.toml).
from custom_components.ha_container_updater.const import TRIGGER_FILE_MAGIC
from custom_components.ha_container_updater.update import HAContainerUpdateEntity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(tmp_path: pathlib.Path) -> HAContainerUpdateEntity:
    """Construct a minimally configured HAContainerUpdateEntity for testing.

    Args:
        tmp_path: Pytest's ``tmp_path`` fixture providing a writable directory.

    Returns:
        An :class:`HAContainerUpdateEntity` instance with sensible test defaults.
    """
    trigger = str(tmp_path / "ha-container-updater-trigger")
    lock = str(tmp_path / "ha-container-updater.lock")

    coordinator = MagicMock()
    coordinator.data = {
        "installed_version": "2026.3.0",
        "latest_version": "2026.3.3",
        "update_available": True,
        "release_url": "https://github.com/home-assistant/core/releases/tag/2026.3.3",
        "rate_limit_remaining": 55,
    }
    coordinator.last_update_success = True

    defaults: dict[str, Any] = {
        "trigger_file_path": trigger,
        "lock_file": lock,
        "compose_dir": "/home/pi/homeassistant",
        "compose_file": "docker-compose.yml",
        "ha_service_name": "homeassistant",
        "prune_images": True,
    }

    entry = MagicMock()
    entry.options.get = lambda key, default=None: defaults.get(key, default)
    entry.data.get = lambda key, default=None: defaults.get(key, default)

    entity: HAContainerUpdateEntity = HAContainerUpdateEntity.__new__(
        HAContainerUpdateEntity
    )
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
# _write_trigger_file
# ===========================================================================


class TestWriteTriggerFile:
    """Unit tests for the atomic trigger file writer."""

    def test_writes_valid_json_payload(self, tmp_path: pathlib.Path) -> None:
        """The written file deserialises to the expected JSON payload."""
        path = str(tmp_path / "trigger")
        payload = json.dumps(
            {"magic": TRIGGER_FILE_MAGIC, "compose_dir": "/home/pi/homeassistant"}
        )
        HAContainerUpdateEntity._write_trigger_file(path, payload)
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert data["magic"] == TRIGGER_FILE_MAGIC
        assert data["compose_dir"] == "/home/pi/homeassistant"

    def test_file_ends_with_newline(self, tmp_path: pathlib.Path) -> None:
        """The trigger file always ends with a newline character."""
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, "{}")
        with open(path) as fh:
            content = fh.read()
        assert content.endswith("\n")

    def test_tmp_file_cleaned_up_on_success(self, tmp_path: pathlib.Path) -> None:
        """The ``.tmp`` staging file is removed after a successful rename."""
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, "{}")
        assert not os.path.exists(path + ".tmp")

    def test_raises_oserror_on_missing_directory(self, tmp_path: pathlib.Path) -> None:
        """Writing to a path whose parent does not exist raises OSError."""
        path = str(tmp_path / "nonexistent" / "trigger")
        with pytest.raises(OSError, match="does not exist"):
            HAContainerUpdateEntity._write_trigger_file(path, "{}")

    def test_atomic_replace_leaves_no_tmp_file(self, tmp_path: pathlib.Path) -> None:
        """The final file exists and no staging ``.tmp`` file remains."""
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, '{"key": "value"}')
        assert os.path.exists(path)
        assert not os.path.exists(path + ".tmp")

    def test_overwrites_existing_trigger_file(self, tmp_path: pathlib.Path) -> None:
        """A second write cleanly replaces the previous trigger file."""
        path = str(tmp_path / "trigger")
        HAContainerUpdateEntity._write_trigger_file(path, '{"first": true}')
        HAContainerUpdateEntity._write_trigger_file(path, '{"second": true}')
        with open(path) as fh:
            data = json.load(fh)
        assert data == {"second": True}


# ===========================================================================
# Entity properties
# ===========================================================================


class TestEntityProperties:
    """Unit tests for HAContainerUpdateEntity read-only properties."""

    def test_installed_version(self, tmp_path: pathlib.Path) -> None:
        assert _make_entity(tmp_path).installed_version == "2026.3.0"

    def test_latest_version(self, tmp_path: pathlib.Path) -> None:
        assert _make_entity(tmp_path).latest_version == "2026.3.3"

    def test_available_true_when_coordinator_ok(self, tmp_path: pathlib.Path) -> None:
        assert _make_entity(tmp_path).available is True

    def test_available_false_when_coordinator_fails(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.coordinator.last_update_success = False
        assert entity.available is False

    def test_in_progress_default_is_false(self, tmp_path: pathlib.Path) -> None:
        assert _make_entity(tmp_path).in_progress is False

    def test_title_is_home_assistant_core(self, tmp_path: pathlib.Path) -> None:
        assert _make_entity(tmp_path).title == "Home Assistant Core"

    def test_release_url_contains_version(self, tmp_path: pathlib.Path) -> None:
        assert "2026.3.3" in _make_entity(tmp_path).release_url  # type: ignore[operator]

    def test_installed_version_none_when_no_data(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.installed_version is None

    def test_latest_version_none_when_no_data(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.latest_version is None

    def test_release_url_none_when_no_data(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.release_url is None

    def test_release_summary_contains_version(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.hass.states.async_all = MagicMock(return_value=[])
        assert "2026.3.3" in (entity.release_summary or "")

    def test_release_summary_none_when_no_update(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.coordinator.data["update_available"] = False
        assert entity.release_summary is None

    def test_release_summary_none_when_no_data(self, tmp_path: pathlib.Path) -> None:
        entity = _make_entity(tmp_path)
        entity.coordinator.data = None
        assert entity.release_summary is None


# ===========================================================================
# extra_state_attributes
# ===========================================================================


class TestExtraStateAttributes:
    """Unit tests for the entity's extra_state_attributes property."""

    EXPECTED_KEYS = frozenset(
        {
            "trigger_file_path",
            "compose_dir",
            "compose_file",
            "ha_service_name",
            "prune_images",
            "lock_file",
            "last_update_requested",
            "in_progress",
            "github_rate_limit_remaining",
        }
    )

    def test_contains_all_expected_keys(self, tmp_path: pathlib.Path) -> None:
        """All documented attribute keys must be present."""
        attrs = _make_entity(tmp_path).extra_state_attributes
        for key in self.EXPECTED_KEYS:
            assert key in attrs, f"Missing key: {key!r}"

    def test_rate_limit_omitted_when_none(self, tmp_path: pathlib.Path) -> None:
        """github_rate_limit_remaining must be absent when the value is None."""
        entity = _make_entity(tmp_path)
        entity.coordinator.data["rate_limit_remaining"] = None
        assert "github_rate_limit_remaining" not in entity.extra_state_attributes

    def test_in_progress_reflects_internal_attr(self, tmp_path: pathlib.Path) -> None:
        """The in_progress attribute mirrors _attr_in_progress."""
        entity = _make_entity(tmp_path)
        entity._attr_in_progress = True
        assert entity.extra_state_attributes["in_progress"] is True


# ===========================================================================
# Trigger file magic string
# ===========================================================================


class TestMagicString:
    """Unit tests for the trigger file magic string constant and payload."""

    def test_magic_string_value(self) -> None:
        """The magic constant must match the value the watcher validates."""
        assert TRIGGER_FILE_MAGIC == "ha_container_updater_REQUESTED"

    def test_trigger_payload_contains_magic(self, tmp_path: pathlib.Path) -> None:
        """A payload written with the magic string reads back correctly."""
        path = str(tmp_path / "trigger")
        payload = json.dumps(
            {
                "magic": TRIGGER_FILE_MAGIC,
                "compose_dir": "/home/pi/homeassistant",
                "compose_file": "docker-compose.yml",
                "service_name": "homeassistant",
                "prune_images": True,
            }
        )
        HAContainerUpdateEntity._write_trigger_file(path, payload)
        with open(path) as fh:
            data = json.load(fh)
        assert data["magic"] == TRIGGER_FILE_MAGIC
