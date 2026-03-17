"""Update entity for HA Container Updater.

This module is intentionally thin — all version-fetching logic lives in
``coordinator.py``.  The entity's sole runtime responsibility is:

  1. Reflecting coordinator state in the HA UI.
  2. On install: writing the trigger file that the host-side watcher detects.
  3. Surfacing meaningful error states rather than silently failing.

Naming / device design
──────────────────────
This integration does NOT register a device.  The HA frontend shows a
"Device created" dialog after *every* config flow that produces a new device
entry — and for UpdateEntity this dialog is especially intrusive.  By omitting
``device_info`` entirely the dialog never appears.

Without a device the naming rules are:
  ``has_entity_name = True``  +  ``name = "Home Assistant Core Update"``
  →  friendly_name  = "Home Assistant Core Update"
  →  entity_id      = update.home_assistant_core_update

The ``title`` property (separate from entity name) is shown inside the update
more-info dialog as the software title line.

Progress tracking
─────────────────
``in_progress`` is set to True as soon as the trigger file is written and
cleared only after the host lock file disappears (or timeouts are reached).
The lock file is written by the watcher when it starts the update and removed
when it finishes — regardless of success or failure.  If the HA container
restarts mid-update (the normal case for a successful update), HA itself
restarts and ``in_progress`` resets naturally via entity reconstruction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from homeassistant.components.update import (
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COMPOSE_DIR,
    CONF_COMPOSE_FILE,
    CONF_HA_SERVICE_NAME,
    CONF_LOCK_FILE,
    CONF_PRUNE_IMAGES,
    CONF_TRIGGER_FILE_PATH,
    DATA_COORDINATOR,
    DEFAULT_LOCK_FILE,
    DEFAULT_TRIGGER_FILE,
    DEVICE_NAME,
    DOMAIN,
    LOG_PREFIX,
    TRIGGER_FILE_MAGIC,
)
from .coordinator import HAContainerUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

UPDATE_ENTITY_DESCRIPTION = UpdateEntityDescription(
    key="ha_container_updater",
    name="Home Assistant Core Update",
    icon="mdi:home-assistant",
    # translation_key is intentionally None: the entity name is fixed in
    # English regardless of locale because it refers to the specific software
    # product "Home Assistant Core".  Translating it would cause confusion.
    translation_key=None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the update entity from a config entry."""
    coordinator: HAContainerUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([HAContainerUpdateEntity(coordinator, entry)])


class HAContainerUpdateEntity(CoordinatorEntity[HAContainerUpdateCoordinator], UpdateEntity):
    """Represents the Home Assistant Docker container update state."""

    entity_description = UPDATE_ENTITY_DESCRIPTION
    # has_entity_name=False (default) means name is the full friendly name,
    # not a suffix appended to a device name.
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HAContainerUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_update"
        self._attr_supported_features = (
            UpdateEntityFeature.INSTALL
            | UpdateEntityFeature.BACKUP
            | UpdateEntityFeature.PROGRESS
        )
        self._attr_in_progress = False
        self._trigger_path: str = entry.options.get(
            CONF_TRIGGER_FILE_PATH,
            entry.data.get(CONF_TRIGGER_FILE_PATH, DEFAULT_TRIGGER_FILE),
        )
        # CONF_LOCK_FILE is not exposed in the config/options flow — users who
        # need a custom path can set HA_UPDATER_LOCK_FILE in the systemd service
        # and update this value via a future options field.  The default matches
        # the systemd service Environment= value in ha-container-updater-watcher.service.
        self._lock_file: str = entry.options.get(
            CONF_LOCK_FILE,
            entry.data.get(CONF_LOCK_FILE, DEFAULT_LOCK_FILE),
        )
        self._compose_dir: str = entry.options.get(
            CONF_COMPOSE_DIR,
            entry.data.get(CONF_COMPOSE_DIR, "/home/pi/homeassistant"),
        )
        self._compose_file: str = entry.options.get(
            CONF_COMPOSE_FILE,
            entry.data.get(CONF_COMPOSE_FILE, "docker-compose.yml"),
        )
        self._ha_service_name: str = entry.options.get(
            CONF_HA_SERVICE_NAME,
            entry.data.get(CONF_HA_SERVICE_NAME, "homeassistant"),
        )
        self._prune_images: bool = entry.options.get(
            CONF_PRUNE_IMAGES,
            entry.data.get(CONF_PRUNE_IMAGES, True),
        )
        self._last_update_requested: str | None = None

    # ── UpdateEntity property overrides ──────────────────────────────────────

    @property
    def installed_version(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.get("installed_version")
        return None

    @property
    def latest_version(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.get("latest_version")
        return None

    @property
    def release_url(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.get("release_url")
        return None

    @property
    def title(self) -> str | None:
        """Software title shown inside the update more-info dialog."""
        return DEVICE_NAME  # "Home Assistant Core"

    @property
    def release_summary(self) -> str | None:
        """Short summary shown when an update is available."""
        if not self.coordinator.data:
            return None
        if not self.coordinator.data.get("update_available"):
            return None
        latest = self.coordinator.data.get("latest_version")
        if not latest:
            return None
        summary = (
            f"Home Assistant {latest} is available. "
            "See the release notes for details before updating."
        )
        last_backup = self._get_last_backup_summary()
        if last_backup:
            summary += f"\n\n{last_backup}"
        return summary

    def _get_last_backup_summary(self) -> str | None:
        """Return a human-readable age string for the most recent HA backup, or None."""
        try:
            backup_states = self.hass.states.async_all("backup")
            if not backup_states:
                return None
            latest = max(backup_states, key=lambda s: s.last_changed)
            delta = dt_util.utcnow() - latest.last_changed
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                age = "less than 1 hour ago"
            elif hours == 1:
                age = "1 hour ago"
            else:
                age = f"{hours} hours ago"
            return f"Last automatic backup {age}."
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("%s Could not retrieve backup summary: %s", LOG_PREFIX, exc)
            return None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def in_progress(self) -> bool:
        return self._attr_in_progress

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self.coordinator.data:
            rate = self.coordinator.data.get("rate_limit_remaining")
            if rate is not None:
                attrs["github_rate_limit_remaining"] = rate
        attrs["trigger_file_path"] = self._trigger_path
        attrs["compose_dir"] = self._compose_dir
        attrs["compose_file"] = self._compose_file
        attrs["ha_service_name"] = self._ha_service_name
        attrs["prune_images"] = self._prune_images
        attrs["lock_file"] = self._lock_file
        attrs["last_update_requested"] = self._last_update_requested
        attrs["in_progress"] = self._attr_in_progress
        return attrs

    # ── Install action ────────────────────────────────────────────────────────

    async def async_install(
        self,
        version: str | None = None,
        backup: bool = False,
        **kwargs: Any,
    ) -> None:
        """Optionally back up, then trigger the host-side watcher to update."""
        _LOGGER.info(
            "%s async_install called with version=%s backup=%s kwargs=%s",
            LOG_PREFIX,
            version,
            backup,
            kwargs,
        )
        if self._attr_in_progress:
            raise HomeAssistantError("An update is already in progress. Please wait.")

        self._last_update_requested = dt_util.utcnow().isoformat()
        self._attr_in_progress = True
        self.async_write_ha_state()

        if backup:
            _LOGGER.info("%s Backup requested — creating backup before update.", LOG_PREFIX)
            try:
                await self.hass.services.async_call("backup", "create", blocking=True)
                _LOGGER.info("%s Backup completed successfully.", LOG_PREFIX)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("%s Backup failed: %s — aborting update.", LOG_PREFIX, exc)
                self._attr_in_progress = False
                self.async_write_ha_state()
                raise HomeAssistantError("Backup failed; update aborted.") from exc

        _LOGGER.info("%s Writing trigger file: %s", LOG_PREFIX, self._trigger_path)
        payload = {
            "magic": TRIGGER_FILE_MAGIC,
            "compose_dir": self._compose_dir,
            "compose_file": self._compose_file,
            "service_name": self._ha_service_name,
            "prune_images": self._prune_images,
        }

        try:
            await self.hass.async_add_executor_job(
                self._write_trigger_file, self._trigger_path, json.dumps(payload)
            )
            _LOGGER.info(
                "%s Trigger file written. Host watcher will perform the update: %s",
                LOG_PREFIX,
                self._trigger_path,
            )
        except OSError as exc:
            _LOGGER.error(
                "%s Failed to write trigger file %r: %s",
                LOG_PREFIX,
                self._trigger_path,
                exc,
            )
            self._attr_in_progress = False
            self.async_write_ha_state()
            raise HomeAssistantError(
                "Failed to write trigger file. Verify trigger file path is writable and volume-mounted."
            ) from exc

        try:
            update_started = await self._wait_for_update_start()
            if not update_started:
                _LOGGER.warning(
                    "%s Update watcher did not acquire lock within 90 s after trigger was written. "
                    "The watcher service may not be running. Check: "
                    "sudo systemctl status ha-container-updater-watcher",
                    LOG_PREFIX,
                )
            else:
                _LOGGER.info("%s Update started (lock acquired). Waiting for completion...", LOG_PREFIX)
                update_finished = await self._wait_for_update_finish()
                if not update_finished:
                    # This almost always means the container restarted mid-update
                    # (i.e. the update succeeded and HA came back up fresh).
                    # It can also mean the update script ran for > 30 min or the
                    # watcher died without releasing the lock.  Either way we
                    # clear in_progress and let the next coordinator poll resolve
                    # the true installed version.
                    _LOGGER.warning(
                        "%s Lock file still present after 30 min timeout. "
                        "The update may have succeeded (container restarted) or failed. "
                        "Check: tail -f %s/ha-container-updater.log",
                        LOG_PREFIX,
                        self._compose_dir,
                    )

            try:
                await self.coordinator.async_request_refresh()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "%s Coordinator refresh after update failed: %s", LOG_PREFIX, exc
                )
        finally:
            self._attr_in_progress = False
            self.async_write_ha_state()

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _wait_for_update_start(self, timeout: int = 90) -> bool:
        """Wait for the host watcher to acquire the lock file (signals update started)."""
        end_time = dt_util.utcnow().timestamp() + timeout
        while dt_util.utcnow().timestamp() < end_time:
            if os.path.exists(self._lock_file):
                return True
            await asyncio.sleep(1)
        return False

    async def _wait_for_update_finish(self, timeout: int = 1800) -> bool:
        """Wait for the host lock file to disappear (signals update finished).

        The lock is released by the watcher whether the update succeeded or
        failed.  A successful update typically causes the HA container to
        restart before this timeout is reached, resetting in_progress naturally.
        """
        end_time = dt_util.utcnow().timestamp() + timeout
        while dt_util.utcnow().timestamp() < end_time:
            if not os.path.exists(self._lock_file):
                return True
            await asyncio.sleep(2)
        return False

    @staticmethod
    def _write_trigger_file(path: str, payload: str) -> None:
        """Atomic trigger payload write (write-then-rename).

        Using os.replace ensures the watcher never observes a partially-written
        file — it either sees the complete JSON or nothing at all.
        """
        trigger_dir = os.path.dirname(path)
        if trigger_dir and not os.path.isdir(trigger_dir):
            raise OSError(
                f"Trigger file directory does not exist: {trigger_dir!r}. "
                "Ensure the path is volume-mounted from the host."
            )
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.write("\n")
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass