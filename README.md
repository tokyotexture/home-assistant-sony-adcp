<p align="center">
  <img
    src="custom_components/sony_adcp/brand/icon@2x.png"
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
vary, so optional entities are created only when the projector reports support
for the corresponding command.

### Tested models

| Model | Firmware | Notes |
| --- | --- | --- |
| VPL-VW535 | | Development model |
| VPL-XW5000ES (reports as VPL-XW5000) | 1.101 | All entities work |

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

Entity availability depends on the commands supported by the projector.

| Entity | Purpose |
| --- | --- |
| Projector media player | Power, current input, and input selection |
| Power status sensor | Standby, startup, on, cooling, or saving state |
| Signal sensor | Current input signal or format |
| Errors sensor | Projector-reported errors |
| Warnings sensor | Projector-reported warnings |
| Operation hours sensor | Projector-reported operation counter, in hours (when supported) |
| Light-source hours sensor | Projector-reported light-source counter, in hours (when supported) |
| Video mute switch | Blank or restore the projected image |
| Picture mode select | Select a supported picture mode |
| Numeric controls | Brightness, contrast, sharpness, and other reported ranges |

## State updates

| State | Update method |
| --- | --- |
| Power | SDAP announcements plus 60-second ADCP reconciliation |
| Home Assistant power commands | Immediate ADCP check, then approximately every second; up to 60 seconds for startup or 5 minutes for shutdown |
| Input and signal | ADCP refresh while the projector is fully on |
| Other commands sent by Home Assistant | Refreshed immediately after completion |
| Picture mode, video mute, and image controls | Same periodic interval when Include picture settings is on; also setup and Home Assistant commands |
| Operation and light-source hours | One shared query at setup and when power reaches standby; no periodic refresh |
| Firmware | Read once at integration setup/reload for the device's firmware field |

Operational state defaults to a 10-second refresh interval while the projector
is fully on. To change it, open the integration and select **Configure**.
Available choices are Disabled, 5, 10, or 30 seconds. No operational refresh
runs during startup, cooling, standby, or fast power-transition monitoring.

**Include picture settings** is on by default (including existing installations)
and applies immediately without reloading. It refreshes picture mode, brightness,
contrast, sharpness, light output, Reality Creation resolution/noise filtering,
and video mute, but only for supported controls whose entities are enabled.
Changes made with the projector's remote or menus update the existing entities;
no duplicate sensors are created. Turning the option off restores input/signal-only
periodic refresh. Selecting Disabled stops periodic picture checks too, without
disabling SDAP or power monitoring. Direct Home Assistant controls still read
their own value after a command.

Input and signal are published first, followed by picture mode and the other
controls. Picture reads share the existing serialized connection and have a
two-second budget per cycle, including network/lock waits. A failed or timed-out
setting retains its last known value and is retried no sooner than 60 seconds
later; it does not make the entire projector unavailable. Successful settings
still update, and only changed values are published. If a power change or option
change happens during a picture read, that stale result is discarded. This
bounded refresh may take more than one cycle to cover every setting on a slow
projector. Custom-command sensors are not included in this beta.

### Power transitions (2.3 beta)

A successful Home Assistant turn-on or turn-off command starts one temporary
async monitor, reusing the existing ADCP connection. It reads only
`power_status ?`: immediately, then one second after each reply. It stops when
turn-on reaches `on`, turn-off reaches `standby` or `saving_standby`, or the
deadline expires: 60 seconds for startup or 5 minutes for shutdown. Network
delays count toward that deadline. These are maximums, not minimum monitoring
periods: standby immediately ends shutdown monitoring. A new successful power
command replaces the previous monitor; power commands are
never automatically resent.

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

### Firmware and usage hours (2.3 beta)

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
known, the integration also tries once when power next reaches on. Shutdown reads
run in the background so a slow counter reply does not delay the standby state.
The counters are reported by the projector, not calculated by Home Assistant;
the integration never resets them. Other niche commands from issue #12 are not
added by this beta.

### Testing prereleases

The 2.3 beta is developed on `beta/2.3-power-transitions`; stable releases remain
on `master`. In HACS, enable prerelease versions for this repository if needed,
then use **Redownload** to select `v2.3.0b4` and restart Home Assistant. No
integration reconfiguration is required. To roll back, redownload `v2.2.4` and
restart again.

Please test normal startup and shutdown, check that startup/cooling appear
promptly, and verify the final on/standby state. Respect the projector's normal
cooldown and avoid rapid power cycling. This beta has automated regression
coverage but still needs real-projector validation.

For beta 4, also check firmware on the device page and both usage-hour sensors
where supported. Compare counters with the projector's own menu, then verify
they refresh after a normal shutdown reaches standby. Short sessions may not
change integer-hour counters. See [issue #12](https://github.com/tokyotexture/home-assistant-sony-adcp/issues/12).

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
