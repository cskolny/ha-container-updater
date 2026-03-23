"""Pytest configuration for HA Container Updater tests.

Stubs out all ``homeassistant.*`` and third-party imports so the test suite
runs with only the standard library, ``pytest``, and ``voluptuous`` — no HA
installation required.

Run with::

    pip install pytest voluptuous
    pytest tests/ -v
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sys
import types
from unittest.mock import MagicMock

import pytest


def _stub(name: str) -> types.ModuleType:
    """Return an existing stub module or create and register a new one.

    Args:
        name: Fully-qualified module name, e.g. ``"homeassistant.core"``.

    Returns:
        The (possibly newly created) :class:`types.ModuleType` for *name*.
    """
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


def _install_ha_stubs() -> None:
    """Install minimal stubs for every ``homeassistant.*`` module the component imports."""
    stub_names = [
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
    ]
    for name in stub_names:
        _stub(name)

    # ── aiohttp ──────────────────────────────────────────────────────────────
    sys.modules["aiohttp"].ClientError = Exception  # type: ignore[attr-defined]

    # ── homeassistant.const ──────────────────────────────────────────────────
    sys.modules["homeassistant.const"].__version__ = "2026.3.3"  # type: ignore[attr-defined]

    # ── homeassistant.core ───────────────────────────────────────────────────
    sys.modules["homeassistant.core"].HomeAssistant = type(  # type: ignore[attr-defined]
        "HomeAssistant", (), {}
    )
    sys.modules["homeassistant.core"].callback = lambda f: f  # type: ignore[attr-defined]

    # ── homeassistant.config_entries ─────────────────────────────────────────
    # ConfigFlow must accept 'domain' as a keyword in __init_subclass__.
    class _ConfigFlow:
        def __init_subclass__(cls, domain: str | None = None, **kwargs: object) -> None:
            super().__init_subclass__(**kwargs)

    class _OptionsFlow:
        pass

    ce = sys.modules["homeassistant.config_entries"]
    ce.ConfigEntry = MagicMock  # type: ignore[attr-defined]
    ce.ConfigFlowResult = dict  # type: ignore[attr-defined]
    ce.ConfigFlow = _ConfigFlow  # type: ignore[attr-defined]
    ce.OptionsFlow = _OptionsFlow  # type: ignore[attr-defined]

    # ── homeassistant.helpers.update_coordinator ─────────────────────────────
    # Both DataUpdateCoordinator and CoordinatorEntity are used as generic base
    # classes (e.g. DataUpdateCoordinator[dict]). They need __class_getitem__
    # so the subscript syntax works at import time without a real HA install.
    class _DataUpdateCoordinator:
        def __init__(
            self,
            hass: object,
            logger: object,
            *,
            name: str,
            update_interval: object,
        ) -> None:
            self.data: object = None
            self.last_update_success: bool = True

        def __class_getitem__(cls, item: object) -> type:
            return cls

    class _CoordinatorEntity:
        def __init__(self, coordinator: object) -> None:
            self.coordinator = coordinator

        def async_write_ha_state(self) -> None:
            pass

        # Required so that CoordinatorEntity[HAContainerUpdateCoordinator]
        # in update.py's class definition is valid at import time.
        def __class_getitem__(cls, item: object) -> type:
            return cls

    class _UpdateFailed(Exception):
        pass

    uc = sys.modules["homeassistant.helpers.update_coordinator"]
    uc.DataUpdateCoordinator = _DataUpdateCoordinator  # type: ignore[attr-defined]
    uc.CoordinatorEntity = _CoordinatorEntity  # type: ignore[attr-defined]
    uc.UpdateFailed = _UpdateFailed  # type: ignore[attr-defined]

    sys.modules[
        "homeassistant.helpers.aiohttp_client"
    ].async_get_clientsession = MagicMock()  # type: ignore[attr-defined]

    # ── homeassistant.components.update ──────────────────────────────────────
    class _UpdateEntityDescription:
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    class _UpdateEntityFeature:
        INSTALL = 1
        BACKUP = 2
        PROGRESS = 4

    upd = sys.modules["homeassistant.components.update"]
    upd.UpdateEntity = type("UpdateEntity", (), {})  # type: ignore[attr-defined]
    upd.UpdateEntityDescription = _UpdateEntityDescription  # type: ignore[attr-defined]
    upd.UpdateEntityFeature = _UpdateEntityFeature  # type: ignore[attr-defined]

    # ── homeassistant.exceptions ─────────────────────────────────────────────
    sys.modules["homeassistant.exceptions"].HomeAssistantError = type(  # type: ignore[attr-defined]
        "HomeAssistantError", (Exception,), {}
    )

    # ── homeassistant.helpers.entity_platform ────────────────────────────────
    sys.modules[
        "homeassistant.helpers.entity_platform"
    ].AddEntitiesCallback = MagicMock  # type: ignore[attr-defined]

    # ── homeassistant.util.dt ────────────────────────────────────────────────
    sys.modules["homeassistant.util.dt"].utcnow = (  # type: ignore[attr-defined]
        lambda: dt.datetime.now(dt.UTC)
    )

    # ── voluptuous ───────────────────────────────────────────────────────────
    class _Schema:
        def __init__(self, schema: object) -> None:
            self._schema = schema

    vol = sys.modules["voluptuous"]
    vol.Schema = _Schema  # type: ignore[attr-defined]
    vol.Required = lambda key, default=None: key  # type: ignore[attr-defined]
    vol.All = lambda *args: args[0]  # type: ignore[attr-defined]
    vol.Range = lambda min=None, max=None: None  # type: ignore[attr-defined]  # min/max shadow builtins intentionally


# Install stubs once at collection time, before any test module is imported.
_install_ha_stubs()


# ── Shared fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def trigger_path(tmp_path: pathlib.Path) -> str:
    """Return a trigger file path inside a writable temp directory."""
    return str(tmp_path / "ha-container-updater-trigger")


@pytest.fixture
def lock_path(tmp_path: pathlib.Path) -> str:
    """Return a lock file path inside a writable temp directory."""
    return str(tmp_path / "ha-container-updater.lock")
