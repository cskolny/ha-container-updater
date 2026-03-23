"""Update entity for HA Container Updater.

This module is intentionally thin — all version-fetching logic lives in
:mod:`coordinator`. The entity's sole runtime responsibilities are:

1. Reflecting coordinator state in the HA UI.
2. On install: writing the trigger file that the host-side watcher detects.
3. Surfacing meaningful error states rather than silently failing.

Naming and device design
────────────────────────
This integration does **not** register a device. The HA frontend shows a
"Device created" dialog after every config flow that produces a new device
entry — and for :class:`~homeassistant.components.update.UpdateEntity` this
dialog is especially intrusive. By omitting ``device_info`` entirely the
dialog never appears.

Without a device the naming rules are::

    has_entity_name = True  +  name = "Home Assistant Core Update"
    → friendly_name = "Home Assistant Core Update"
    → entity_id     = update.home_assistant_core_update

The :attr:`title` property (separate from entity name) is shown inside the
update more-info dialog as the software title line.

Progress tracking
─────────────────
:attr:`in_progress` is set to ``True`` as soon as the trigger file is written
and cleared only after the host lock file disappears (or timeouts are reached).
The lock file is written by the watcher when it starts the update and removed
when it finishes — regardless of success or failure. If the HA container
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

LOGGER = logging.getLogger(__name__)

# Entity description for the single update entity exposed by this integration.
# translation_key is intentionally None: the entity name is fixed in English
# regardless of locale because it refers to the specific product name
# "Home Assistant Core". Translating it would cause confusion.
UPDATE_ENTITY_DESCRIPTION = UpdateEntityDescription(
    key="ha_container_updater",
    name="Home Assistant Core Update",
    icon="mdi:home-assistant",
    translation_key=None,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the update entity from a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The active config entry.
        async_add_entities: Callback to register new entities.
    """
    coordinator: HAContainerUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    async_add_entities([HAContainerUpdateEntity(coordinator, entry)])


class HAContainerUpdateEntity(
    CoordinatorEntity[HAContainerUpdateCoordinator], UpdateEntity
):
    """Represents the Home Assistant Docker container update state.

    Attributes:
        entity_description: Shared metadata for this entity type.
    """

    entity_description = UPDATE_ENTITY_DESCRIPTION
    # has_entity_name=False (default) means ``name`` is the full friendly name,
    # not a suffix appended to a device name.
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HAContainerUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise the update entity.

        Args:
            coordinator: The data coordinator supplying version information.
            entry: The active config entry used to read user-configured paths.
        """
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_update"
        self._attr_supported_features = (
            UpdateEntityFeature.INSTALL
            | UpdateEntityFeature.BACKUP
            | UpdateEntityFeature.PROGRESS
        )
        self._attr_in_progress = False

        # Resolve all path/config values once at construction time so property
        # accessors remain cheap — options always take precedence over data.
        def _opt(key: str, default: Any) -> Any:
            return entry.options.get(key, entry.data.get(key, default))

        self._trigger_path: str = _opt(CONF_TRIGGER_FILE_PATH, DEFAULT_TRIGGER_FILE)
        # CONF_LOCK_FILE is not exposed in the config/options flow. Users who
        # need a custom path can set HA_UPDATER_LOCK_FILE in the systemd
        # service environment. The default matches the service Environment=
        # value in ha-container-updater-watcher.service.
        self._lock_file: str = _opt(CONF_LOCK_FILE, DEFAULT_LOCK_FILE)
        self._compose_dir: str = _opt(CONF_COMPOSE_DIR, "/home/pi/homeassistant")
        self._compose_file: str = _opt(CONF_COMPOSE_FILE, "docker-compose.yml")
        self._ha_service_name: str = _opt(CONF_HA_SERVICE_NAME, "homeassistant")
        self._prune_images: bool = _opt(CONF_PRUNE_IMAGES, True)
        self._last_update_requested: str | None = None

    # ── UpdateEntity property overrides ──────────────────────────────────────

    @property
    def installed_version(self) -> str | None:
        """Return the currently running HA version, or ``None`` if unknown."""
        if self.coordinator.data:
            return self.coordinator.data.get("installed_version")
        return None

    @property
    def latest_version(self) -> str | None:
        """Return the latest HA release version, or ``None`` if unknown."""
        if self.coordinator.data:
            return self.coordinator.data.get("latest_version")
        return None

    @property
    def release_url(self) -> str | None:
        """Return a URL to the GitHub release page, or ``None`` if unknown."""
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
            f"Home Assistant {latest} is available."
            " See the release notes for details before updating."
        )
        last_backup = self._get_last_backup_summary()
        if last_backup:
            summary += f"\n\n{last_backup}"
        return summary

    def _get_last_backup_summary(self) -> str | None:
        """Return a human-readable age string for the most recent HA backup.

        Returns:
            A string such as ``"Last automatic backup 3 hours ago."`` if a
            backup entity exists, or ``None`` if none is found or an error
            occurs. Failures are logged at DEBUG level to aid diagnosis without
            cluttering the log under normal conditions.
        """
        try:
            backup_states = self.hass.states.async_all("backup")
            if not backup_states:
                return None
            latest_state = max(backup_states, key=lambda s: s.last_changed)
            delta = dt_util.utcnow() - latest_state.last_changed
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                age = "less than 1 hour ago"
            elif hours == 1:
                age = "1 hour ago"
            else:
                age = f"{hours} hours ago"
            return f"Last automatic backup {age}."
        except Exception as exc:
            LOGGER.debug(
                "%s Could not retrieve backup summary: %s", LOG_PREFIX, exc
            )
            return None

    @property
    def available(self) -> bool:
        """Return ``True`` when the coordinator last updated successfully."""
        return self.coordinator.last_update_success

    @property
    def in_progress(self) -> bool:
        """Return ``True`` while an update is in flight."""
        return self._attr_in_progress

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic state attributes visible in the developer tools."""
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
        """Optionally back up, then trigger the host-side watcher to update.

        Writes a JSON trigger file to the volume-mounted path. The host-side
        watcher service detects the file, validates the magic string, and runs
        ``docker compose pull`` + ``docker compose up -d --force-recreate``.

        Args:
            version: Target version string (unused; HA passes it for parity).
            backup: If ``True``, create a full HA backup before updating.
            **kwargs: Additional keyword arguments forwarded by the HA core.

        Raises:
            HomeAssistantError: If an update is already in progress, the
                backup fails, or the trigger file cannot be written.
        """
        LOGGER.info(
            "%s async_install called — version=%s backup=%s kwargs=%s",
            LOG_PREFIX,
            version,
            backup,
            kwargs,
        )
        if self._attr_in_progress:
            raise HomeAssistantError(
                "An update is already in progress. Please wait."
            )

        self._last_update_requested = dt_util.utcnow().isoformat()
        self._attr_in_progress = True
        self.async_write_ha_state()

        if backup:
            LOGGER.info(
                "%s Backup requested — creating backup before update.", LOG_PREFIX
            )
            try:
                await self.hass.services.async_call(
                    "backup", "create", blocking=True
                )
                LOGGER.info("%s Backup completed successfully.", LOG_PREFIX)
            except Exception as exc:
                LOGGER.error(
                    "%s Backup failed: %s — aborting update.", LOG_PREFIX, exc
                )
                self._attr_in_progress = False
                self.async_write_ha_state()
                raise HomeAssistantError("Backup failed; update aborted.") from exc

        payload = json.dumps(
            {
                "magic": TRIGGER_FILE_MAGIC,
                "compose_dir": self._compose_dir,
                "compose_file": self._compose_file,
                "service_name": self._ha_service_name,
                "prune_images": self._prune_images,
            }
        )
        LOGGER.info("%s Writing trigger file: %s", LOG_PREFIX, self._trigger_path)

        try:
            await self.hass.async_add_executor_job(
                self._write_trigger_file, self._trigger_path, payload
            )
            LOGGER.info(
                "%s Trigger file written. Host watcher will perform the update: %s",
                LOG_PREFIX,
                self._trigger_path,
            )
        except OSError as exc:
            LOGGER.error(
                "%s Failed to write trigger file %r: %s",
                LOG_PREFIX,
                self._trigger_path,
                exc,
            )
            self._attr_in_progress = False
            self.async_write_ha_state()
            raise HomeAssistantError(
                "Failed to write trigger file."
                " Verify the trigger file path is writable and volume-mounted."
            ) from exc

        try:
            update_started = await self._wait_for_update_start()
            if not update_started:
                LOGGER.warning(
                    "%s Update watcher did not acquire lock within 90 s after trigger"
                    " was written. The watcher service may not be running. Check:"
                    " sudo systemctl status ha-container-updater-watcher",
                    LOG_PREFIX,
                )
            else:
                LOGGER.info(
                    "%s Update started (lock acquired). Waiting for completion…",
                    LOG_PREFIX,
                )
                update_finished = await self._wait_for_update_finish()
                if not update_finished:
                    # This almost always means the container restarted mid-update
                    # (i.e. the update succeeded and HA came back up fresh).
                    # It can also mean the update script ran for >30 min or the
                    # watcher died without releasing the lock. Either way we
                    # clear in_progress and let the next coordinator poll resolve
                    # the true installed version.
                    LOGGER.warning(
                        "%s Lock file still present after 30-minute timeout."
                        " The update may have succeeded (container restarted)"
                        " or failed. Check: tail -f %s/ha-container-updater.log",
                        LOG_PREFIX,
                        self._compose_dir,
                    )

            try:
                await self.coordinator.async_request_refresh()
            except Exception as exc:
                LOGGER.warning(
                    "%s Coordinator refresh after update failed: %s", LOG_PREFIX, exc
                )
        finally:
            self._attr_in_progress = False
            self.async_write_ha_state()

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _wait_for_update_start(self, timeout: int = 90) -> bool:
        """Wait for the host watcher to acquire the lock file.

        The lock file's appearance signals that the watcher has picked up the
        trigger and begun the update sequence.

        Args:
            timeout: Maximum seconds to wait before giving up.

        Returns:
            ``True`` if the lock appeared within *timeout* seconds.
        """
        end_time = dt_util.utcnow().timestamp() + timeout
        while dt_util.utcnow().timestamp() < end_time:
            if os.path.exists(self._lock_file):
                return True
            await asyncio.sleep(1)
        return False

    async def _wait_for_update_finish(self, timeout: int = 1800) -> bool:
        """Wait for the host lock file to disappear.

        The lock is released by the watcher whether the update succeeded or
        failed. A successful update typically causes the HA container to restart
        before this timeout is reached, resetting ``in_progress`` naturally.

        Args:
            timeout: Maximum seconds to wait before giving up (default 30 min).

        Returns:
            ``True`` if the lock disappeared within *timeout* seconds.
        """
        end_time = dt_util.utcnow().timestamp() + timeout
        while dt_util.utcnow().timestamp() < end_time:
            if not os.path.exists(self._lock_file):
                return True
            await asyncio.sleep(2)
        return False

    @staticmethod
    def _write_trigger_file(path: str, payload: str) -> None:
        """Write the trigger payload atomically using a write-then-rename pattern.

        Using :func:`os.replace` ensures the watcher never observes a
        partially-written file — it either sees the complete JSON or nothing.

        Args:
            path: Destination path for the trigger file.
            payload: JSON string to write.

        Raises:
            OSError: If the parent directory does not exist or the write fails.
        """
        trigger_dir = os.path.dirname(path)
        if trigger_dir and not os.path.isdir(trigger_dir):
            raise OSError(
                f"Trigger file directory does not exist: {trigger_dir!r}."
                " Ensure the path is volume-mounted from the host."
            )
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.write("\n")
            os.replace(tmp_path, path)
        finally:
            # Best-effort cleanup of the temp file if os.replace failed.
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
