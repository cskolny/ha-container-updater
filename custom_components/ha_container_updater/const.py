"""Constants for the HA Container Updater integration."""

from __future__ import annotations

# ── Integration identity ──────────────────────────────────────────────────────
DOMAIN: str = "ha_container_updater"
INTEGRATION_NAME: str = "HA Container Updater"

# ── Entity display ────────────────────────────────────────────────────────────
# DEVICE_NAME is used as the UpdateEntity.title property — shown inside the
# update more-info dialog as the software title line.
DEVICE_NAME: str = "Home Assistant Core"

# ── Config-entry keys (stored in entry.data / entry.options) ─────────────────
CONF_COMPOSE_DIR: str = "compose_dir"
CONF_COMPOSE_FILE: str = "compose_file"
CONF_HA_SERVICE_NAME: str = "ha_service_name"
CONF_TRIGGER_FILE_PATH: str = "trigger_file_path"
CONF_PRUNE_IMAGES: str = "prune_images"
CONF_SCAN_INTERVAL: str = "scan_interval"
CONF_LOCK_FILE: str = "lock_file"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_COMPOSE_DIR: str = "/home/pi/homeassistant"
# Intentional /tmp use — path is volume-mounted from the host into the HA container.
DEFAULT_LOCK_FILE: str = "/tmp/ha-container-updater.lock"
DEFAULT_COMPOSE_FILE: str = "docker-compose.yml"
DEFAULT_HA_SERVICE_NAME: str = "homeassistant"
# Intentional /tmp use — must match HA_UPDATER_TRIGGER_FILE in the systemd service.
DEFAULT_TRIGGER_FILE: str = "/tmp/ha-container-updater-trigger"
DEFAULT_PRUNE_IMAGES: bool = True
DEFAULT_SCAN_INTERVAL: int = 3600  # seconds — poll GitHub once per hour

# ── GitHub API ────────────────────────────────────────────────────────────────
REPO_API_URL: str = (
    "https://api.github.com/repos/home-assistant/core/releases/latest"
)
GITHUB_TIMEOUT: int = 15  # seconds
GITHUB_RATE_LIMIT_HEADER: str = "X-RateLimit-Remaining"

# ── Trigger file protocol ─────────────────────────────────────────────────────
# The HA component writes this file; the host-side watcher detects and acts on it.
# Content written to the trigger file so the watcher can validate authenticity.
TRIGGER_FILE_MAGIC: str = "ha_container_updater_REQUESTED"

# ── Status / state tracking ───────────────────────────────────────────────────
# Keys stored in hass.data[DOMAIN]
DATA_COORDINATOR: str = "coordinator"

# ── Logging ───────────────────────────────────────────────────────────────────
# Prefix prepended to every log message emitted by this integration.
# Kept as a constant so grep/filtering on the host log is trivial.
LOG_PREFIX: str = "[ha-container-updater]"
