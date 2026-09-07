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

Power state is delivered immediately by Sony's local SDAP announcements and
independently reconciled through ADCP every 60 seconds in case announcements
are missed or stale. The active input and signal are refreshed while the
projector is on, at a configurable interval.

## Features

- Native projector-class `media_player`
- Automatic discovery through Sony SDAP advertisements
- Model and serial-number identification
- Automatic detection of password authentication
- Fully asynchronous ADCP client with reconnect handling
- Push-driven power, startup, cooling, and standby state with periodic ADCP
  reconciliation
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
| Video mute switch | Blank or restore the projected image |
| Picture mode select | Select a supported picture mode |
| Numeric controls | Brightness, contrast, sharpness, and other reported ranges |

## State updates

| State | Update method |
| --- | --- |
| Power | Immediate local SDAP announcements plus 60-second ADCP reconciliation |
| Input and signal | ADCP refresh while the projector is on |
| Commands sent by Home Assistant | Refreshed immediately after completion |
| Picture mode, video mute, and image controls | Setup and Home Assistant commands only |

Input and signal default to a 10-second refresh interval while the projector is
on. To change it, open the integration and select **Configure**. Available
choices are Disabled, 5, 10, or 30 seconds. No operational refresh runs while
the projector is off.

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
