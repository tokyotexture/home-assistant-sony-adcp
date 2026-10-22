<p align="center">
  <img
    src="https://raw.githubusercontent.com/tokyotexture/home-assistant-sony-adcp/master/custom_components/sony_adcp/brand/icon@2x.png"
    alt="Sony ADCP Projector"
    width="160"
  >
</p>

<h1 align="center">Sony ADCP Projector</h1>

<p align="center">
  A modern, local-first Home Assistant integration for Sony projectors and
  displays that support ADCP and SDAP.
</p>

<p align="center">
  <a href="https://github.com/tokyotexture/home-assistant-sony-adcp/releases">
    <img
      src="https://img.shields.io/github/v/release/tokyotexture/home-assistant-sony-adcp?style=flat-square"
      alt="Latest release"
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

Sony ADCP Projector represents a projector as a native Home Assistant
`media_player`: power it on or off, select an input, see its signal format, and
build automations around real device state.

Power state follows Sony's local SDAP announcements and is independently
reconciled through ADCP every 60 seconds in case announcements are missed or
stale. After a Home Assistant power command, a short-lived ADCP monitor checks
power approximately every second until the requested state is reached, for at
most 60 seconds during startup or 5 minutes during shutdown. The active input
and signal, along with optional picture settings, are refreshed while the
projector is fully on, at a configurable interval.

## Features

- Native projector-class `media_player`
- Automatic discovery through Sony SDAP advertisements
- Model and serial-number identification
- Main firmware in device info and optional operation/light-source hour sensors
- Automatic detection of password authentication
- Fully asynchronous ADCP client with reconnect handling
- Push-driven power with fast, bounded monitoring of Home Assistant power
  commands and periodic ADCP reconciliation
- Input selection and current-source reporting
- Signal-format sensor suitable for automations
- Video mute, picture mode, and supported numeric image controls
- Automatic IP-address migration when DHCP changes the projector address
- Home Assistant reauthentication, reconfiguration, diagnostics, and options
- Bundled light/dark-compatible integration branding
- No cloud service or external Python dependency

## Requirements

- Home Assistant 2026.3 or newer
- A Sony projector or professional display with network ADCP support
- ADCP enabled in the projector's network settings
- Advertisement/SDAP enabled for discovery and push power updates
- Home Assistant and the projector on a network where UDP broadcasts can reach
  Home Assistant

The integration was developed and tested with a Sony VPL-VW535. Sony models
vary: numeric controls and hour sensors are created from supported ranges and
valid counters. Picture mode and video mute may be unavailable on models that
do not support them.

### Tested models

| Model | Firmware | Notes |
| --- | --- | --- |
| VPL-VW535 | | Development model |
| VPL-XW5000ES (reports as VPL-XW5000) | 1.101 | Previously reported working; optional capabilities vary by model |

## Installation

### HACS

[![Open your Home Assistant instance and open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tokyotexture&repository=home-assistant-sony-adcp&category=integration)

Until this repository is part of the default HACS catalog:

1. Open HACS.
2. Select the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/tokyotexture/home-assistant-sony-adcp`.
4. Select **Integration** as the category.
5. Install **Sony ADCP Projector** and restart Home Assistant.

### Manual

Copy `custom_components/sony_adcp` into your Home Assistant configuration:

```text
/config/
└── custom_components/
    └── sony_adcp/
        ├── __init__.py
        ├── manifest.json
        └── ...
```

Restart Home Assistant after copying the files.

## Projector setup

In the projector's web interface or network menu, enable:

1. **ADCP**
2. **Advertisement / SDAP**
3. A standby or network-management mode that keeps networking active in standby

Sony's factory ports are:

| Protocol | Transport | Default port | Purpose |
| --- | --- | ---: | --- |
| ADCP | TCP | `53595` | Commands and detailed status |
| SDAP | UDP | `53862` | Discovery and push power status |

The factory advertisement interval is normally 30 seconds. The setup flow
listens for 35 seconds so it spans a full default interval.

## Add the integration

After installation and restart:

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **Sony ADCP Projector**.
4. Wait for discovery, then select the projector.

Choose **Enter address manually** if broadcasts do not cross your network.
When the projector requires authentication, Home Assistant asks for its web
administrator password automatically.

## Entities

Entity availability depends on the commands supported by the projector. The
[value-by-value refresh reference](docs/state-updates.md#entity-and-value-reference)
explains exactly when each entity is read and when it can become stale.

| Entity | Purpose |
| --- | --- |
| Projector media player | Power, current input, and input selection |
| Power status sensor | Standby, startup, on, cooling, or saving state |
| Signal sensor | Current input signal or format |
| Errors sensor | Error snapshot, read at setup only if fully on; not continuously monitored |
| Warnings sensor | Warning snapshot, read at setup only if fully on; not continuously monitored |
| Operation hours sensor | Projector-reported operation counter, in hours (when supported) |
| Light-source hours sensor | Projector-reported light-source counter, in hours (when supported) |
| Video mute switch | Blank or restore the projected image |
| Picture mode select | Select a supported picture mode |
| Brightness number | Reported brightness value and range |
| Contrast number | Reported contrast value and range |
| Sharpness number | Reported sharpness value and range |
| Light output number | Reported light-output value and range |
| Reality Creation resolution number | Reported resolution-enhancement value and range |
| Reality Creation noise filtering number | Reported noise-filtering value and range |

## State updates

The configurable interval refreshes a **subset of values**, not every entity.
Power status is handled separately. See the [complete refresh reference](docs/state-updates.md)
for every entity, attribute, query, option, and known freshness limitation.

| Values | When they update |
| --- | --- |
| Power status and media-player on/off state | SDAP announcements; independent ADCP check about every 60 seconds; fast temporary checks after Home Assistant power commands |
| Current input and signal | While fully on: configurable refresh, plus setup, power-watchdog checks, and refreshes after changed power/address announcements or Home Assistant input selection |
| Picture mode, video mute, brightness, contrast, sharpness, light output, Reality Creation resolution and noise filtering | Initial read when each enabled control is added; readback after its own Home Assistant command; configurable refresh when Include picture settings is on |
| Errors and warnings | Setup/reload only, and only if the projector is fully on then |
| Operation and light-source hours | Setup and after confirmed shutdown to standby; retry on transitions to on while no counters are known, unless unsupported |
| Firmware and identity | Setup/reload; not periodically polled |

In **Configure**, **Refresh interval** defaults to **10 seconds**, with choices
Disabled, 5, 10, or 30 seconds. **Include picture settings** defaults to on,
including existing installations. Both changes apply without reloading. The
configurable loop runs only while the projector is available and fully `on`,
and pauses during fast power monitoring.

**Disabled stops this configurable loop, not all polling.** The independent
power watchdog still reads input and signal when it finds the projector on.
Setup, changed power/address announcements, and direct Home Assistant controls
can also trigger reads. Turning only Include picture settings off leaves the
configured input/signal refresh running.

Only supported picture controls with enabled entities take part in periodic
picture refresh. Their reads share a two-second budget per cycle and failed
settings back off for at least 60 seconds, so the selected interval is not a
guaranteed update deadline. See [refresh timing and failures](docs/state-updates.md#refresh-timing-and-failures).
Custom-command sensors are not implemented.

### Power transitions

A successful Home Assistant turn-on or turn-off command starts one temporary
async monitor, reusing the existing ADCP connection. It reads only
`power_status ?`: immediately, then one second after each reply. It stops when
turn-on reaches `on`, turn-off reaches `standby` or `saving_standby`, or the
deadline expires: 60 seconds for startup or 5 minutes for shutdown. Network
delays count toward that deadline. These are maximums, not minimum monitoring
periods: standby immediately ends shutdown monitoring. A new successful power
command replaces the previous monitor; the monitor queries status rather than
repeatedly sending power commands.

During this window, confirmed ADCP readings take priority over potentially
stale SDAP power announcements. Normal input/signal and picture polling pauses, but DHCP
address changes are still handled. Normal SDAP updates and periodic refreshes
resume afterward. Power changes made with a remote control do not start fast
polling.

The media player's `sony_power_status` attribute and power-status sensor show
confirmed projector state, including startup and cooling. Its `power_transition`
attribute is `on` or `off` while monitoring that requested endpoint, and null
otherwise. A cleared transition attribute alone does not prove success: a
timeout or authentication failure also clears it. Use confirmed power state
for completion automations. Responses are not optimistic, and startup/cooling
continue to appear as an on media player until standby is confirmed.

A timeout stops only fast monitoring, not the projector's startup/cooling.
The last confirmed power is retained and ordinary SDAP/watchdog updates can
still discover completion later. The initial control action returns after
acknowledgement; it does not wait up to 60 seconds or 5 minutes. These deadlines
are independent of Configure's value-refresh options.

See [aggressive polling and timeout behavior](docs/state-updates.md#aggressive-polling-the-sequence)
for the full sequence, retry/error handling, replacement commands, and what
happens after monitoring ends.

### Firmware and usage hours

When supported, `version ?` supplies the `main` firmware version for the device
page. The separate laser-module firmware is not used. Firmware is not polled;
reload the integration or restart Home Assistant after updating projector firmware
to refresh this field.

One `timer ?` query reads the `operation` and `light_src` hour counters together.
The integration reads them at setup and again **after power actually reaches
standby or saving standby**, following any startup/cooling states. Sending an off
command alone does not update the counters. This works for Home Assistant power
commands and remote-control shutdowns observed through SDAP or the existing
power watchdog. Repeated standby announcements do not cause repeated timer reads.

The resulting **Operation hours** and **Light-source hours** diagnostic sensors
are added only for counters that return valid values, including a genuine zero.
They use hours, support long-term total-increasing statistics and maintenance
automations, and retain their last known value during the session. They are
snapshots, not live running-hour estimates: an on projector can accumulate hours
until the next successful shutdown refresh. A read failure keeps existing values
instead of inventing zero or marking the whole projector unavailable.

Unsupported commands are optional and do not prevent setup. A projector that
returns `err_cmd` for `timer ?` is not queried again until the integration reloads.
If the initial read is temporarily inactive or unavailable and no counters are
known, the integration also retries on transitions to on until counters are known
or the command is confirmed unsupported. Shutdown reads
run in the background so a slow counter reply does not delay the standby state.
The counters are reported by the projector, not calculated by Home Assistant;
the integration never resets them. Other niche commands from issue #12 are not
included in this release.

For the full entity list, media-player attributes, diagnostic limitations, and
exact read triggers, see [How values update](docs/state-updates.md).

### Updating to 2.3

**v2.3.0 is the stable release**, incorporating the functionality tested in the
2.3 betas. Update through HACS and restart Home Assistant. If needed, use
**Redownload** to select `v2.3.0`. Prerelease versions are not required, and no
integration reconfiguration is needed when upgrading from 2.2.4 or a 2.3 beta.

Include picture settings is enabled by default, including existing installations.
Use **Configure** to change this or the value-refresh interval. Firmware and hour
sensors appear only where supported; short sessions may not change integer-hour
counters. Respect the projector's cooldown and avoid rapid power cycling.

To roll back, use HACS Redownload to select `v2.2.4` and restart Home Assistant.
The historical beta releases remain available, but are superseded by v2.3.0.

## DHCP address changes

The integration identifies a discovered projector by serial number rather than
by IP address alone. When the same serial number announces from a new address,
Home Assistant:

1. closes the old ADCP connection;
2. moves communication to the announced address;
3. saves the new host in the config entry; and
4. keeps the existing device, entities, history, and automations.

For safety, automatic migration is disabled when the projector does not
advertise a serial number. Use **Reconfigure** for those devices.

## Authentication and privacy

The integration reads the projector's first ADCP greeting:

- `NOKEY` continues without requesting a password.
- A challenge response opens the password step and authenticates using Sony's
  SHA-256 flow.

Credentials are stored by Home Assistant and redacted from diagnostics. ADCP
traffic is local but not encrypted, so use it only on a trusted network.

## Migrating from the legacy switch

This integration replaces the original YAML `SONY_ADCP` switch component.

1. Install and configure the new integration.
2. Update automations to use the new entities.
3. Remove the old `switch:` YAML configuration.
4. Restart Home Assistant.

The original implementation remains available on the `legacy-switch-v1`
branch for reference.

## Troubleshooting

### The integration is not listed

Confirm this exact path exists, then restart Home Assistant:

```text
/config/custom_components/sony_adcp/manifest.json
```

### Discovery finds nothing

- Wait at least 35 seconds.
- Confirm Advertisement/SDAP is enabled.
- Confirm UDP port `53862` is not blocked.
- Check whether a VLAN or router is preventing broadcast traffic.
- Use manual setup if broadcasts cannot reach Home Assistant.

### The device becomes unavailable in standby

Enable the projector setting that keeps networking active in standby. Sony
usually calls it **Standby mode: Standard** or **Network management: On**.

### The icon does not update

Home Assistant and the browser cache brand assets. Restart Home Assistant and
perform a hard browser refresh after upgrading.

## Development

The protocol and SDAP layers have dependency-free offline tests:

```bash
python -m unittest discover -s tests -v
```

Lint the integration with Ruff:

```bash
ruff check .
```

Pull requests and projector compatibility reports are welcome. For bugs,
download diagnostics from the integration page and attach the redacted file to
the issue.

## Protocol references

- [Sony Protocol Manual — Common](https://pro.sony/s3/2018/07/05125823/Sony_Protocol-Manual_1st-Edition.pdf)
- [Sony Supported Command List — Revised 1](https://pro.sony/s3/2018/07/19110602/Sony_Protocol-Manual_Supported-Command-List_1st-Edition-Revised-1.pdf)

## License

Licensed under the [Apache License 2.0](LICENSE).

Sony and the Sony logo are trademarks of Sony Group Corporation. This
community project is not affiliated with or endorsed by Sony.
