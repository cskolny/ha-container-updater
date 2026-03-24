"""DataUpdateCoordinator for HA Container Updater.

Responsible for:
- Polling the GitHub Releases API on a configurable interval.
- Parsing and comparing CalVer version strings correctly.
- Surfacing structured errors and availability state to entities.
- Respecting GitHub API rate-limit headers to avoid throttling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GITHUB_RATE_LIMIT_HEADER,
    GITHUB_TIMEOUT,
    LOG_PREFIX,
    REPO_API_URL,
)

LOGGER = logging.getLogger(__name__)

# Type alias for the coordinator's data payload.
_CoordinatorData = dict[str, Any]


def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """Parse a HA CalVer string into a comparable integer tuple.

    Strips a leading ``v`` if present. Returns ``None`` if any part of the
    version string is non-numeric (e.g. pre-release tags like ``2026.3.0b1``)
    so callers can fall back gracefully rather than raising.

    Args:
        version_str: Raw version string, e.g. ``"2026.3.1"`` or ``"v2026.3"``.

    Returns:
        A tuple of integers such as ``(2026, 3, 1)``, or ``None`` on failure.
    """
    cleaned = version_str.strip().lstrip("v")
    try:
        return tuple(int(part) for part in cleaned.split("."))
    except ValueError:
        LOGGER.warning("%s Could not parse version string: %r", LOG_PREFIX, version_str)
        return None


def _is_update_available(installed: str, latest: str) -> bool:
    """Return ``True`` only when *latest* is strictly newer than *installed*.

    Uses tuple comparison of integer version parts, which correctly handles
    HA's CalVer scheme (``YYYY.M.patch``). Falls back to string inequality on
    parse failure to avoid false positives.

    Args:
        installed: The currently running HA version string.
        latest: The latest GitHub release tag (with or without leading ``v``).

    Returns:
        ``True`` if an update is available, ``False`` otherwise.
    """
    installed_tuple = _parse_version(installed)
    latest_tuple = _parse_version(latest)
    if installed_tuple is None or latest_tuple is None:
        # Non-numeric versions (pre-releases): fall back to string comparison.
        return installed.lstrip("v") != latest.lstrip("v")
    return latest_tuple > installed_tuple


class HAContainerUpdateCoordinator(DataUpdateCoordinator[_CoordinatorData]):  # type: ignore[misc]
    """Coordinator that fetches the latest HA release from GitHub.

    The data dict returned by :meth:`_async_update_data` has the shape::

        {
            "installed_version": str,        # Running HA version
            "latest_version":    str,        # Latest GitHub release tag (stripped)
            "release_url":       str,        # URL to the GitHub release page
            "update_available":  bool,       # Parsed comparison result
            "rate_limit_remaining": int | None,
        }
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise the coordinator with the configured poll interval.

        Args:
            hass: The Home Assistant instance.
            entry: The active config entry. Used here only to read the scan
                interval at construction time; not stored as an instance attr.
        """
        scan_seconds: int = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_seconds),
        )

    async def _async_update_data(self) -> _CoordinatorData:
        """Fetch the latest release information from the GitHub API.

        Raises:
            UpdateFailed: On any network error, unexpected HTTP status, or
                missing response field. The base class will mark the entity as
                unavailable and retry with exponential back-off.

        Returns:
            A dict describing the current and latest HA versions.
        """
        session = async_get_clientsession(self.hass)
        installed = HA_VERSION.lstrip("v")
        rate_remaining: int | None = None

        try:
            async with asyncio.timeout(GITHUB_TIMEOUT):
                async with session.get(
                    REPO_API_URL,
                    headers={"Accept": "application/vnd.github+json"},
                ) as resp:
                    # Read the rate-limit header before anything else.
                    raw_rate = resp.headers.get(GITHUB_RATE_LIMIT_HEADER)
                    if raw_rate is not None:
                        try:
                            rate_remaining = int(raw_rate)
                        except ValueError:
                            pass

                    if rate_remaining is not None and rate_remaining < 5:
                        LOGGER.warning(
                            "%s GitHub API rate limit nearly exhausted (%s remaining)."
                            " Returning cached data.",
                            LOG_PREFIX,
                            rate_remaining,
                        )
                        # Consume the body so aiohttp releases the connection.
                        await resp.read()
                        if self.data:
                            return {
                                **self.data,
                                "rate_limit_remaining": rate_remaining,
                                "_from_cache": True,
                            }

                    if resp.status == 403:
                        raise UpdateFailed(
                            f"{LOG_PREFIX} GitHub API rate limited (HTTP 403)."
                            " Will retry at the next scheduled interval."
                        )

                    if resp.status == 404:
                        raise UpdateFailed(
                            f"{LOG_PREFIX} GitHub release endpoint not found (HTTP 404)."
                            " Check REPO_API_URL in const.py."
                        )

                    if resp.status != 200:
                        raise UpdateFailed(
                            f"{LOG_PREFIX} GitHub API returned unexpected status"
                            f" {resp.status}."
                        )

                    payload: dict[str, Any] = await resp.json()

        except (aiohttp.ClientError, TimeoutError) as exc:
            raise UpdateFailed(
                f"{LOG_PREFIX} Network error fetching GitHub release: {exc}"
            ) from exc

        tag: str | None = payload.get("tag_name")
        if not tag:
            raise UpdateFailed(
                f"{LOG_PREFIX} GitHub response missing 'tag_name' field."
            )

        latest = tag.lstrip("v")
        update_available = _is_update_available(installed, latest)

        if update_available:
            LOGGER.info(
                "%s Update available: installed=%s  latest=%s",
                LOG_PREFIX,
                installed,
                latest,
            )
        else:
            LOGGER.debug(
                "%s Up to date: installed=%s  latest=%s",
                LOG_PREFIX,
                installed,
                latest,
            )

        return {
            "installed_version": installed,
            "latest_version": latest,
            "release_url": (
                f"https://github.com/home-assistant/core/releases/tag/{tag}"
            ),
            "update_available": update_available,
            "rate_limit_remaining": rate_remaining,
        }
