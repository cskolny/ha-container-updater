# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-03-17

### Fixed
- **`parse_status` bug in watcher script** — the previous `if ! parse_output=$(...)` pattern
  used `set -e` suppression but never actually captured the Python subprocess exit code into
  `parse_status`, so JSON parse failures and magic-string mismatches were silently ignored and
  the watcher would proceed with an empty args array. Fixed to `parse_output=$(...) || parse_status=$?`
  which correctly captures the real exit code and triggers the invalid-payload warning path.
- **Unused `MAGIC_STRING` variable removed from watcher** — the variable was declared but never
  referenced; the magic string is validated inside the inline Python snippet where it belongs.
- **`aiohttp` connection leak on rate-limit cache return** — when the GitHub API rate limit was
  nearly exhausted the coordinator returned cached data before reading the response body, leaving
  the aiohttp connection unreleased. Added `await resp.read()` before the early return so the
  connection is always returned cleanly to the pool.
- **`self._entry` unused storage removed from coordinator** — `HAContainerUpdateCoordinator`
  stored the config entry as `self._entry` in `__init__` but never referenced it after
  construction. The entry is now only used locally to read the scan interval.
- **Dead constant `_POST_INSTALL_POLL_DELAY` removed from `update.py`** — the constant was
  defined at module level but never referenced anywhere.
- **`_get_last_backup_summary` silent exception** — the bare `except Exception` block now logs
  at DEBUG level instead of swallowing errors silently, making it easier to diagnose unexpected
  failures in backup state retrieval.

### Changed
- **`hacs.json` schema corrected** — `"domains": ["update"]` (array, wrong key) replaced with
  `"domain": "ha_container_updater"` (string, correct HACS v2 key) to ensure valid HACS
  submission metadata.
- **`manifest.json` version bumped to `1.1.0`**.
- **`manifest.json` quality scale corrected** — downgraded from `"silver"` to `"bronze"`.
  Silver tier has formal HA requirements including test coverage that are not yet met; `"bronze"`
  accurately reflects the current state and avoids issues with HACS validation.
- **`deploy.sh` manifest version stamping made dynamic** — the hardcoded base version
  (`"1.1.0"`) is now read from `manifest.json` at deploy time using `python3 -c "..."`, so the
  stamping step never needs a manual edit after future version bumps.
- **Class names aligned across all Python modules** — `HADockerUpdateCoordinator`,
  `HADockerUpdateEntity`, `HADockerUpdaterConfigFlow`, and `HADockerUpdaterOptionsFlow` all
  renamed to their `HAContainer*` equivalents, consistent with the v1.0.0 rename of the project
  from "HA Docker Updater" to "HA Container Updater".
- **`translation_key=None` documented** — added an inline comment to `UpdateEntityDescription`
  explaining that the entity name is intentionally kept in English regardless of locale because
  it refers to the specific product name "Home Assistant Core".
- **`CONF_LOCK_FILE` usage documented** — added a comment in `update.py` explaining why the
  lock file path is not exposed in the options flow and how to override it via the systemd
  service environment variable.
- **Timeout warning messages made actionable** — the warnings logged when the update watcher
  does not start or finish within the expected time now include the log file path and the
  `systemctl status` command to check, making them easier to act on without consulting the docs.
- **`__init__.py` module docstring corrected** — the architecture overview now lists both
  host-side scripts (`ha-container-updater-watcher.sh` and `ha-container-updater.sh`) instead
  of only the watcher.
- **Watcher script duplicate log line removed** — the back-to-back `"Invoking updater script"`
  and `"Executing updater with args"` log lines were collapsed into a single line.

## [1.0.0] - 2026-03-17

### Added
- Initial release.
- **`UpdateEntity` integration** — appears in **Settings → System → Updates**
  alongside other HA update entities. Supports the Install action from the
  standard HA update card.
- **GitHub release polling** via `DataUpdateCoordinator` — queries the GitHub
  Releases API on a configurable interval (default 1 hour) and compares the
  latest tag against the running HA version using CalVer tuple comparison.
- **Two-part update architecture** — the HA component writes a trigger file to
  a volume-mounted path; a host-side systemd watcher service detects the file
  and executes `docker compose pull` + `up --force-recreate`. This correctly
  solves the fundamental problem that a container cannot restart itself.
- **Atomic trigger file writes** — uses write-then-rename (`os.replace`) so the
  host watcher never sees a partially-written file.
- **Magic string validation** — the trigger file contains `ha_container_updater_REQUESTED`;
  the watcher validates this before acting to prevent stray files from triggering
  unintended updates.
- **Lock file** on the host watcher prevents concurrent update runs.
- **Config flow** — full guided UI setup via **Settings → Devices & Services →
  Add Integration**. No `configuration.yaml` changes required.
- **Options flow** — all settings adjustable post-setup without removing and
  re-adding the integration.
- **Trigger directory validation** in config and options flow — detects missing
  volume mounts before the integration is saved, surfacing a clear error rather
  than a silent runtime failure.
- **GitHub API rate-limit awareness** — reads `X-RateLimit-Remaining` header;
  returns cached data instead of erroring when the limit is nearly exhausted.
- **`docker compose` v1 / v2 detection** — host-side update script automatically
  prefers the v2 plugin (`docker compose`) and falls back to the v1 standalone
  binary (`docker-compose`).
- **Optional image pruning** — configurable `prune_images` option runs
  `docker image prune -af` after a successful update to reclaim disk space.
- **Structured timestamped logging** on both the HA component and the host-side
  scripts, written to `ha-container-updater.log` in the Compose directory.
- **systemd service** (`ha-container-updater-watcher.service`) with resource limits,
  correct Docker socket dependencies, and `Restart=on-failure`.
- **`deploy.sh`** — one-command deployment script supporting `--skip-restart`,
  `--component-only`, and `--host-only` flags.

### Notes on HA compatibility
- **`packaging` dependency removed** — version comparison uses a stdlib
  `tuple(int, ...)` split on `"."`, handling HA's CalVer scheme correctly with
  no external dependencies.
- **`asyncio.timeout`** used instead of the forbidden `async-timeout` package
  (removed in HA 2025.7+).
- **`ConfigFlowResult`** used instead of the removed `FlowResult`
  (removed in HA 2025.9).
- **`OptionsFlow.__init__`** not overridden — storing `self._config_entry`
  manually was deprecated in HA 2024.11 and broke hard in HA 2025.12.
- **`manifest.json` minimum HA version** set to `2025.12.0`.