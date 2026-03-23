"""HA Container Updater — custom integration for updating Home Assistant via Docker.

Architecture overview
─────────────────────
This integration operates in two parts:

**Part 1 — HA component** (this code, runs inside the container):

- ``coordinator.py``   — polls GitHub for the latest HA release.
- ``update.py``        — :class:`UpdateEntity` that reflects coordinator state.
- ``config_flow.py``   — guided UI setup; stores config in a
  :class:`~homeassistant.config_entries.ConfigEntry`.

**Part 2 — Host-side watcher** (runs on the Raspberry Pi / Docker host):

- ``ha-container-updater-watcher.sh``  — polls for the trigger file and
  calls ``ha-container-updater.sh``.
- ``ha-container-updater.sh``          — executes ``docker compose pull`` and
  ``docker compose up -d --force-recreate``.
- ``ha-container-updater-watcher.service`` — systemd unit managing the watcher.

The HA component never calls ``docker compose`` directly — it cannot, because
restarting the container would kill the running process. Instead it writes a
small trigger file to a path that is volume-mounted on the host. The host
watcher detects that file, executes the update, and removes the trigger.

Device registry note
────────────────────
This integration deliberately does **not** create a device entry. Any
integration that creates a device during config-flow setup causes the HA
frontend to show a "Device created" dialog. Since this integration has no
physical hardware to represent, device creation is skipped entirely. The update
entity is accessible directly under **Settings → Devices & Services →
HA Container Updater**.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DOMAIN, LOG_PREFIX
from .coordinator import HAContainerUpdateCoordinator

LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["update"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HA Container Updater from a config entry.

    Creates the coordinator, performs an initial data fetch, and forwards
    platform setup to ``update.py``. Raises
    :exc:`~homeassistant.exceptions.ConfigEntryNotReady` when the first
    coordinator refresh fails so HA will retry automatically.

    Args:
        hass: The Home Assistant instance.
        entry: The active config entry.

    Returns:
        ``True`` on successful setup.
    """
    hass.data.setdefault(DOMAIN, {})

    coordinator = HAContainerUpdateCoordinator(hass, entry)

    # Perform an initial refresh so entities have data on first render.
    # If this raises, ConfigEntryNotReady propagates and HA retries.
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {DATA_COORDINATOR: coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-register update listener so options changes reload the entry.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    LOGGER.info("%s Integration loaded successfully.", LOG_PREFIX)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Tear down the integration cleanly on removal or reload.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being unloaded.

    Returns:
        ``True`` if all platforms were unloaded successfully.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        LOGGER.info("%s Integration unloaded.", LOG_PREFIX)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are changed via the UI.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry whose options changed.
    """
    LOGGER.debug("%s Options changed — reloading entry.", LOG_PREFIX)
    await hass.config_entries.async_reload(entry.entry_id)
