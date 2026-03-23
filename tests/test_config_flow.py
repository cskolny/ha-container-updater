"""Tests for config_flow.py — trigger directory validation and default constants."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stubs for homeassistant imports (conftest.py installs most; top-up here).
# ---------------------------------------------------------------------------
for _mod in [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

_ce = sys.modules["homeassistant.config_entries"]


class _ConfigFlow:
    def __init_subclass__(cls, domain: str | None = None, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)


class _OptionsFlow:
    pass


_ce.ConfigFlow = _ConfigFlow  # type: ignore[attr-defined]
_ce.OptionsFlow = _OptionsFlow  # type: ignore[attr-defined]
_ce.ConfigFlowResult = dict  # type: ignore[attr-defined]

sys.modules["homeassistant.core"].callback = lambda f: f  # type: ignore[attr-defined]

# voluptuous is a real runtime dependency — install with: pip install voluptuous
import voluptuous as vol  # noqa: E402  (must follow stub setup)

from custom_components.ha_container_updater.config_flow import (  # noqa: E402
    _validate_trigger_dir,
)
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
    """Unit tests for the _validate_trigger_dir validation helper."""

    def test_valid_writable_directory(self, tmp_path: object) -> None:
        """A path inside a writable temp directory passes validation."""
        import pathlib

        trigger = str(pathlib.Path(str(tmp_path)) / "ha-container-updater-trigger")
        assert _validate_trigger_dir(trigger) is None

    def test_missing_directory_returns_error_key(self, tmp_path: object) -> None:
        """A path whose parent directory does not exist returns the expected key."""
        import pathlib

        trigger = str(pathlib.Path(str(tmp_path)) / "nonexistent" / "trigger")
        assert _validate_trigger_dir(trigger) == "trigger_dir_not_found"

    def test_root_level_path(self) -> None:
        """A path directly in '/' resolves its parent to '/', which exists."""
        result = _validate_trigger_dir("/trigger")
        # '/' exists on all POSIX systems but may not be writable in CI.
        assert result in (None, "trigger_dir_not_writable")

    def test_unwritable_directory_returns_error_key(self, tmp_path: object) -> None:
        """An existing but unwritable directory returns the expected key."""
        import pathlib

        trigger = str(pathlib.Path(str(tmp_path)) / "trigger")
        with patch("os.access", return_value=False):
            assert _validate_trigger_dir(trigger) == "trigger_dir_not_writable"

    def test_bare_filename_falls_back_to_root(self) -> None:
        """A filename with no directory component uses '/' as its parent."""
        with (
            patch("os.path.isdir", return_value=True),
            patch("os.access", return_value=True),
        ):
            assert _validate_trigger_dir("trigger") is None


# ===========================================================================
# Default constant values
# ===========================================================================


class TestDefaults:
    """Guard tests that catch accidental changes to default constant values."""

    def test_default_trigger_file(self) -> None:
        assert DEFAULT_TRIGGER_FILE == "/tmp/ha-container-updater-trigger"

    def test_default_compose_dir(self) -> None:
        assert DEFAULT_COMPOSE_DIR == "/home/pi/homeassistant"

    def test_default_compose_file(self) -> None:
        assert DEFAULT_COMPOSE_FILE == "docker-compose.yml"

    def test_default_ha_service_name(self) -> None:
        assert DEFAULT_HA_SERVICE_NAME == "homeassistant"

    def test_default_prune_images(self) -> None:
        assert DEFAULT_PRUNE_IMAGES is True

    def test_default_scan_interval(self) -> None:
        assert DEFAULT_SCAN_INTERVAL == 3600

    def test_scan_interval_satisfies_minimum(self) -> None:
        """The schema enforces min=300; verify the default satisfies it."""
        assert DEFAULT_SCAN_INTERVAL >= 300

    def test_scan_interval_satisfies_maximum(self) -> None:
        """The schema enforces max=86400; verify the default satisfies it."""
        assert DEFAULT_SCAN_INTERVAL <= 86400
