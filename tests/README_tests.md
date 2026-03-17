# Running the Tests

## Setup

The tests use only the standard library plus `pytest` and `voluptuous`
(the same schema library HA itself uses — no HA installation needed).

```bash
pip install pytest voluptuous
```

Place the test files alongside your repository root:

```
ha-container-updater/
├── custom_components/
│   └── ha_container_updater/
│       ├── __init__.py
│       ├── coordinator.py
│       ├── update.py
│       ├── config_flow.py
│       └── const.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_coordinator.py
│   ├── test_config_flow.py
│   └── test_update.py
└── pytest.ini
```

## pytest.ini

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

## Run all tests

```bash
pytest -v
```

## Run a single file

```bash
pytest tests/test_coordinator.py -v
```

## What is covered

| File | What is tested |
|---|---|
| `test_coordinator.py` | `_parse_version` — standard CalVer, leading-v, two-part, whitespace, non-numeric (pre-release), empty, garbage |
| `test_coordinator.py` | `_is_update_available` — newer patch/minor/year, same version, older, leading-v on either side, two-vs-three-part, string-fallback |
| `test_config_flow.py` | `_validate_trigger_dir` — valid dir, missing dir, unwritable dir, bare filename, root path |
| `test_config_flow.py` | Default constant values — guards against accidental changes to defaults |
| `test_update.py` | `_write_trigger_file` — valid write, newline, tmp cleanup, missing directory error, atomic replace, overwrite |
| `test_update.py` | Entity properties — installed/latest/release_url with and without coordinator data, available, in_progress, title |
| `test_update.py` | `extra_state_attributes` — all expected keys present, rate_limit omitted when None, in_progress reflects attr |
| `test_update.py` | Magic string value and presence in trigger payload |

## What is NOT covered (requires a real HA test harness)

- `async_install` end-to-end (backup call, trigger write, lock polling)
- `_wait_for_update_start` / `_wait_for_update_finish` timing behaviour
- Config flow / options flow UI steps (`async_step_user`, `async_step_init`)
- Coordinator `_async_update_data` with a mocked aiohttp session

These would require `pytest-homeassistant-custom-component` and are the
natural next step toward meeting the silver quality scale requirements.
