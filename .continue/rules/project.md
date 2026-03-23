---
name: ha-container-updater
globs: "**/*.py"
alwaysApply: false
description: Rules for the ha-container-updater HA integration
---

# ha-container-updater

- Domain: `container_updater`
- Polls container registries via DataUpdateCoordinator
- Entities: sensor (current vs latest tag) + binary_sensor (update available)
- unique_id pattern: `{domain}_{container_name}_{entity_type}`
- Registry credentials in config_entry.data only — never logged
- Pin any docker SDK version in manifest.json requirements