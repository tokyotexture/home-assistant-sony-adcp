# Development and protocol references

The integration adds no external Python runtime dependency. Contributions,
projector compatibility reports and reproducible bug reports are welcome.

## Local checks

Use Python 3.13 or newer for lint and the offline tests:

```bash
python -m pip install ruff voluptuous
ruff check .
python -m unittest discover -s tests -v
```

The offline suite covers ADCP/SDAP framing, authentication, power transitions,
refresh scheduling, custom conversion, action requests and configuration/lifecycle
behavior. HA interfaces use a minimal harness; UI schemas use real Voluptuous.

## Real Home Assistant tests

CI runs HACS, Hassfest, Ruff/offline tests, and real HA registry/action/documentation
tests on **2026.3.0** and **2026.10.2**. The latter run separately from offline
stubs, in Python 3.14 environments with the selected HA version installed:

```bash
python -m pip install homeassistant==2026.10.2
python -m unittest discover -s tests/native -v
```

Use `homeassistant==2026.3.0` to check the minimum supported version instead.
These tests cover device ownership, beta 1 migration, service permissions,
responses/deadlines, and the [automation guide's](automation-examples.md) copyable
YAML, payloads and choice/startup/state guards. The single-owner-only historical
bug reproduction is skipped on older registry APIs.

Automated tests do not establish support for every model-specific Sony command.
Test harmless changes on real hardware and respect startup/cooldown. Avoid
unnecessary Reset/Execute operations, which may discard settings.

## Official Sony protocol references

- [Protocol Manual — Common](https://pro.sony/s3/2018/07/05125823/Sony_Protocol-Manual_1st-Edition.pdf)
- [Supported Command List — Revised 1](https://pro.sony/s3/2018/07/19110602/Sony_Protocol-Manual_Supported-Command-List_1st-Edition-Revised-1.pdf)

Model columns matter. Professional-model choices do not automatically apply to
VW/XW home-cinema models. The [action guide](custom-commands.md#official-sony-examples)
includes printed-page references and model-dependent examples.

[Back to the README](../README.md)
