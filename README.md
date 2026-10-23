<p align="center">
  <img
    src="https://raw.githubusercontent.com/tokyotexture/home-assistant-sony-adcp/master/custom_components/sony_adcp/brand/icon@2x.png"
    alt="Sony ADCP Projector"
    width="160"
  >
</p>

<h1 align="center">Sony ADCP Projector</h1>

<p align="center">
  Local control and automation for Sony projectors in Home Assistant.
</p>

<p align="center">
  <a href="https://github.com/tokyotexture/home-assistant-sony-adcp/releases">
    <img
      src="https://img.shields.io/github/v/release/tokyotexture/home-assistant-sony-adcp?style=flat-square"
      alt="Latest stable release"
    >
  </a>
  <a href="https://github.com/tokyotexture/home-assistant-sony-adcp/actions">
    <img
      src="https://img.shields.io/github/actions/workflow/status/tokyotexture/home-assistant-sony-adcp/validate.yml?branch=master&style=flat-square&label=validation"
      alt="Validation status"
    >
  </a>
  <a href="LICENSE">
    <img
      src="https://img.shields.io/github/license/tokyotexture/home-assistant-sony-adcp?style=flat-square&cacheSeconds=300&v=2"
      alt="Apache-2.0 license"
    >
  </a>
  <img
    src="https://img.shields.io/badge/Home%20Assistant-2026.3%2B-18BCF2?style=flat-square&logo=home-assistant&logoColor=white"
    alt="Home Assistant 2026.3 or newer"
  >
</p>

---

Control power and inputs, see projector status, and build automations around
your display. The integration uses Sony's local ADCP/SDAP protocols and presents
the projector as a Home Assistant `media_player`—not a streaming player.

> **2.4.1b2 testing:** this branch preserves known picture controls across
> restarts while the projector is off. In HACS, enable **Show beta versions**,
> select **v2.4.1b2** through **Redownload**, and restart HA. Turn the projector
> on once to learn and save its capabilities, then test an HA restart in standby.
> Controls should remain present but unavailable, and recover when fully on.
> Beta 2 retries temporarily inactive picture settings at the configured interval
> during the first minute after confirmed power-on, rather than waiting 60 seconds.
> See the [beta test checklist](docs/state-updates.md#241-beta-testing).
> Stable **v2.4.0** is unchanged.

> **New in 2.4:** custom sensors and Query/Send ADCP actions are now stable.
> Update through HACS and restart Home Assistant; prerelease versions are not
> required. See the [changelog](CHANGELOG.md) and [upgrade guide](docs/setup-and-troubleshooting.md#upgrading).

[Quick start](#quick-start) · [Compatibility](#compatibility) ·
[Automations](#custom-automation-workflow) · [Documentation](#documentation)

## Features

- Power on/off, input selection, confirmed power status and signal format.
- Supported picture controls, including picture mode, video mute and numeric settings.
- Automatic discovery, model/serial identification and password-authentication detection.
- Asynchronous local communication, reconnect handling and DHCP address updates.
- Firmware information and operation/light-source hour sensors where supported.
- Custom ADCP sensors and structured query/write actions.
- UI configuration, refresh options, reauthentication and redacted diagnostics.
- No cloud service or extra Python runtime dependencies.

## Quick start

### 1. Prepare the projector

In its network menu or web interface, enable **ADCP**, **Advertisement / SDAP**,
and a standby/network-management mode that keeps networking active while off.
Use a trusted local network: ADCP traffic is not encrypted.

Discovery needs UDP broadcasts to reach Home Assistant. If your network blocks
them, use manual setup; automatic discovery and address updates need those
announcements. [Network details and troubleshooting](docs/setup-and-troubleshooting.md).

### 2. Install

#### HACS

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tokyotexture&repository=home-assistant-sony-adcp&category=integration)

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/tokyotexture/home-assistant-sony-adcp`, category **Integration**.
3. Install **Sony ADCP Projector** and restart Home Assistant.

Version **2.4.0** includes custom sensors/actions without enabling prereleases.
If upgrading from a beta, select **v2.4.0** through **Redownload** if needed.

#### Manual installation

Copy `custom_components/sony_adcp` from the desired release into your Home
Assistant configuration so this file exists:

```text
/config/custom_components/sony_adcp/manifest.json
```

Restart Home Assistant after installation or updates.

### 3. Add the integration

1. Open **Settings → Devices & services → Add integration**.
2. Search for **Sony ADCP Projector**.
3. Allow up to 35 seconds for discovery, then select your projector.

Choose **Enter address manually** if needed. If authentication is required,
Home Assistant asks for the projector's web administrator password.

## Compatibility

Requires **Home Assistant 2026.3 or newer** and a Sony projector or professional
display with network ADCP support. Not every Sony display supports these protocols.

| Model | Firmware | Report |
| --- | --- | --- |
| VPL-VW535 | 5.003 | Development model; maintainer confirmed 2.4 query/write actions and custom sensors working |
| VPL-XW5000ES (reports as VPL-XW5000) | 1.101 | Previously reported working; optional capabilities vary |

Commands, accepted values and available controls vary by model, input and power
state. A working power connection does not imply support for every picture or
custom command. Compatibility reports are welcome.

## Controls and sensors

| Group | What you get |
| --- | --- |
| Projector media player | Power, current input and input selection |
| Status | Detailed power state and signal format |
| Picture settings | Picture mode, video mute, brightness, contrast, sharpness, light output and Reality Creation controls, where supported |
| Device diagnostics | Main firmware, optional operation/light-source hours, and setup-only error/warning snapshots |
| Custom sensors | Named read-only ADCP values, including optional JSON fields and numeric units |

The media player represents a **display**, so it does not offer playback or
streaming controls. Optional entities depend on model support; some may be
disabled by default. See [every entity and when it updates](docs/state-updates.md#entity-and-value-reference).

## Custom automation workflow

1. **Discover:** Use **Query ADCP command** to read a known command, inspect its
   allowed values/range, or obtain command information.
2. **Control:** Use a built-in entity or **Send ADCP command** to change a
   supported setting. Use the exact choices reported by your projector.
3. **Monitor:** Add a sensor under **Configure → Custom sensors**, then use its
   state in normal Home Assistant triggers, conditions and dashboards.

Start with [Discover, control and monitor your projector](docs/automation-examples.md)
for complete examples using `aspect`, safe startup waits and sensor automations.
Querying does not enumerate all commands or update sensor entities. Writes are
structured and validated—not an unrestricted raw/network/calibration terminal.

## State updates

Power and other values use different update paths:

- **Power:** SDAP announcements plus an independent ADCP check about every
  60 seconds. HA power commands temporarily check about once per second, bounded
  to 60 seconds for startup or 5 minutes for shutdown; they do not resend power.
- **Input, signal and custom sensors:** configurable refresh while fully on,
  paused during fast power monitoring. **Include picture settings** adds enabled,
  supported picture controls to that schedule.
- **Firmware and diagnostics:** firmware/errors/warnings are setup snapshots,
  not continuous monitoring. Hour counters refresh at setup and after confirmed
  shutdown, with retries when appropriate.

Open **Configure → Refresh settings**. The interval defaults to **10 seconds**;
choose 5, 10, 30 seconds or Disabled. Include picture settings defaults to on.
**Disabled does not stop all communication:** power checks and event/control
readbacks remain. One-off custom queries also work independently of that interval.

Acknowledgement is not physical completion. For automations, use confirmed Sony
power status; the media player's general `on` state can include startup/cooling.
Custom sensors are unavailable off or during transitions. Refresh budgets and
error backoff mean the chosen interval is not a guaranteed freshness deadline.
Read the [full update and timeout reference](docs/state-updates.md) for exact rules.

## Documentation

| Guide | Covers |
| --- | --- |
| [Automation examples](docs/automation-examples.md) | Query → supported write → monitored sensor, with copyable YAML |
| [Custom sensors](docs/custom-sensors.md) | Add/edit/remove, JSON fields, refresh behavior and beta 1 migration |
| [Query and Send actions](docs/custom-commands.md) | Sony command examples, response variables, validation and failure handling |
| [How values update](docs/state-updates.md) | Every entity/attribute, power transitions, counters and freshness limits |
| [Setup and troubleshooting](docs/setup-and-troubleshooting.md) | Ports, discovery, DHCP, authentication, upgrades and common problems |
| [Development](docs/development.md) | Local tests, CI and official Sony protocol references |

## Troubleshooting

- **Integration not listed?** Check the installation path above and restart HA.
- **Discovery finds nothing?** Wait 35 seconds, check SDAP/UDP `53862` and network
  broadcast routing, or enter the address manually.
- **Unavailable in standby?** Enable networking in standby on the projector.
- **A setting or custom sensor does not work?** Check model support, exact-case
  choices, confirmed power state, refresh options and the sensor's `last_error`.

See the [troubleshooting guide](docs/setup-and-troubleshooting.md#common-problems).
For bug reports, include model, firmware, installed version and redacted
diagnostics. Never include passwords or sensitive custom-query replies.

## Contributing

Issues, compatibility reports and pull requests are welcome. See the
[development guide](docs/development.md) for validation and test commands, and
the [changelog](CHANGELOG.md) for previous releases. Historical migration steps
are in the [upgrade guide](docs/setup-and-troubleshooting.md#upgrading).

## License

Licensed under the [Apache License 2.0](LICENSE).

Sony and the Sony logo are trademarks of Sony Group Corporation. This
community project is not affiliated with or endorsed by Sony.
