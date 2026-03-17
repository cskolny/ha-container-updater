"""
Pytest configuration for HA Container Updater tests.

Stubs out all homeassistant.* and third-party imports so the test suite
runs with only the standard library + pytest + voluptuous — no HA
installation required.

Run with:
    pip install pytest voluptuous
    pytest tests/ -v
"""

from __future__ import annotations

import datetime as dt
import sys
import types
from unittest.mock import MagicMock

import pytest


def _stub(name: str) -> types.ModuleType:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


def _install_ha_stubs() -> None:
    """Install minimal stubs for every homeassistant.* module the component imports."""
    for mod in [
        "aiohttp",
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.components",
        "homeassistant.components.update",
        "homeassistant.exceptions",
        "homeassistant.helpers.entity_platform",
        "homeassistant.util",
        "homeassistant.util.dt",
        "voluptuous",
    ]:
        _stub(mod)

    # ── aiohttp ──────────────────────────────────────────────────────────────
    sys.modules["aiohttp"].ClientError = Exception

    # ── homeassistant.const ──────────────────────────────────────────────────
    sys.modules["homeassistant.const"].__version__ = "2026.3.1"

    # ── homeassistant.core ───────────────────────────────────────────────────
    sys.modules["homeassistant.core"].HomeAssistant = type("HomeAssistant", (), {})
    sys.modules["homeassistant.core"].callback = lambda f: f

    # ── homeassistant.config_entries ─────────────────────────────────────────
    # ConfigFlow must accept 'domain' as a keyword in __init_subclass__
    class _ConfigFlow:
        def __init_subclass__(cls, domain=None, **kw):
            super().__init_subclass__(**kw)

    class _OptionsFlow:
        pass

    ce = sys.modules["homeassistant.config_entries"]
    ce.ConfigEntry = MagicMock
    ce.ConfigFlowResult = dict
    ce.ConfigFlow = _ConfigFlow
    ce.OptionsFlow = _OptionsFlow

    # ── homeassistant.helpers.update_coordinator ─────────────────────────────
    # DataUpdateCoordinator and CoordinatorEntity need __class_getitem__ so
    # the generic subscript syntax (e.g. DataUpdateCoordinator[dict]) works.
    class _DataUpdateCoordinator:
        def __init__(self, hass, logger, *, name, update_interval):
            self.data = None
            self.last_update_success = True
        def __class_getitem__(cls, item):
            return cls

    class _CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator
        def async_write_ha_state(self):
            pass
        def __class_getitem__(cls, item):
            return cls

    class _UpdateFailed(Exception):
        pass

    uc = sys.modules["homeassistant.helpers.update_coordinator"]
    uc.DataUpdateCoordinator = _DataUpdateCoordinator
    uc.CoordinatorEntity = _CoordinatorEntity
    uc.UpdateFailed = _UpdateFailed

    sys.modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = MagicMock()

    # ── homeassistant.components.update ──────────────────────────────────────
    class _UpdateEntityDescription:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class _UpdateEntityFeature:
        INSTALL = 1
        BACKUP = 2
        PROGRESS = 4

    upd = sys.modules["homeassistant.components.update"]
    upd.UpdateEntity = type("UpdateEntity", (), {})
    upd.UpdateEntityDescription = _UpdateEntityDescription
    upd.UpdateEntityFeature = _UpdateEntityFeature

    # ── homeassistant.exceptions ─────────────────────────────────────────────
    sys.modules["homeassistant.exceptions"].HomeAssistantError = type(
        "HomeAssistantError", (Exception,), {}
    )

    # ── homeassistant.helpers.entity_platform ────────────────────────────────
    sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = MagicMock

    # ── homeassistant.util.dt ────────────────────────────────────────────────
    sys.modules["homeassistant.util.dt"].utcnow = lambda: dt.datetime.now(dt.timezone.utc)

    # ── voluptuous ───────────────────────────────────────────────────────────
    class _Schema:
        def __init__(self, schema):
            self._schema = schema

    vol = sys.modules["voluptuous"]
    vol.Schema = _Schema
    vol.Required = lambda key, default=None: key
    vol.All = lambda *a: a[0]
    vol.Range = lambda min=None, max=None: None


# Install stubs once at collection time, before any test module is imported.
_install_ha_stubs()


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def trigger_path(tmp_path):
    """A trigger file path inside a writable temp directory."""
    return str(tmp_path / "ha-container-updater-trigger")


@pytest.fixture
def lock_path(tmp_path):
    """A lock file path inside a writable temp directory."""
    return str(tmp_path / "ha-container-updater.lock")
