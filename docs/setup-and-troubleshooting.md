# Setup, upgrades and troubleshooting

Start with the [README quick start](../README.md#quick-start) for installation
and adding your projector. This guide keeps network details, migration steps
and less common problems out of the main setup path.

## Projector and network settings

Enable these in the projector's web interface or network menu:

1. **ADCP** for commands and detailed status.
2. **Advertisement / SDAP** for discovery and pushed power announcements.
3. A standby/network-management mode that keeps networking active in standby.
   Sony commonly calls it **Standby mode: Standard** or **Network management: On**;
   wording and availability vary by model.

| Protocol | Transport | Factory port | Purpose |
| --- | --- | ---: | --- |
| ADCP | TCP | `53595` | Authenticated commands and detailed status |
| SDAP | UDP | `53862` | Discovery and power announcements |

The projector's factory advertisement interval is normally 30 seconds. Setup
listens for 35 seconds to span a default interval. UDP broadcasts must reach
Home Assistant; VLANs, routers, host/container networking and firewalls may
prevent that. Manual setup can use a reachable address when broadcasts do not
cross your network, but it does not restore missing SDAP announcements.

Power also has independent ADCP reconciliation and bounded fast monitoring
after HA power commands. See [power updates](state-updates.md#power-updates)
rather than reducing the general refresh interval to compensate for discovery.

## DHCP address changes

A discovered projector is identified by its advertised serial number, not only
its IP address. When the same serial announces from a new address, the integration:

1. Closes the old ADCP connection.
2. Moves communication to the announced address.
3. Saves the new host in its configuration entry.
4. Retains the existing device, entities, history and automations.

Automatic migration requires matching SDAP announcements with a serial number.
Without an advertised serial, or when those announcements cannot reach HA, use
**Reconfigure** to update the address. A manual initial setup is not by itself
a promise that a later address change can be discovered.

## Authentication and privacy

The first ADCP greeting determines whether authentication is required:

- `NOKEY` continues without a password prompt.
- A challenge prompts for the projector's web administrator password and uses
  Sony's SHA-256 authentication flow.

Use the integration's reauthentication prompt after a password change. Credentials
are stored by Home Assistant and redacted from downloadable diagnostics. ADCP
traffic is local but **not encrypted**; use it only on a trusted network. Custom
query responses may contain model-specific or sensitive information: review them
before sharing, and never post passwords.

## Upgrading

Restart Home Assistant after updating integration files through HACS or manually.
The stable release is **v2.4.1**, including the 2.4 custom sensors/Query/Send actions
and fixes for resilient picture updates and startup recovery. Prerelease versions
are not required. If upgrading from a beta, use **Redownload** to select v2.4.1
if needed; keep the integration and existing
sensors in place. See the [changelog](../CHANGELOG.md) for history.

### Picture-control fixes in 2.4.1

From 2.4.0 or older, turn the projector fully on once after upgrading. This learns
and saves the supported controls/ranges; earlier versions did not persist them.
An off-only first upgrade cannot restore ranges that have never been saved.
Existing 2.4.1 beta users keep their capability cache. No entity recreation or
configuration changes are required, and names, IDs and history are preserved.

Picture controls are now **unavailable** while off or until a fresh read succeeds,
instead of displaying stale values. This is expected, including orange unavailable
indicators on dashboards; it does not mean the integration stopped providing them.
Temporary startup inactivity retries on the configured interval during the first
minute after confirmed `on`. See [all timing and recovery rules](state-updates.md).

### From 2.4 beta 1

Beta 1 could assign the shared projector device to a custom-sensor subentry,
making the media-player power control disappear on affected HA versions.
Stable 2.4 (and beta 2 or later) keeps all entities under the parent projector and
automatically migrates remaining beta 1 sensor settings/IDs on restart. **Do not delete/re-add
the integration or manually remove beta 1 sensors before upgrading.** Registry
customizations already deleted by beta 1 cannot be reconstructed; check recreated
entity IDs and automations. See [full migration details](custom-sensors.md#upgrading-from-beta-1).

Add/edit/remove sensors through **Configure → Custom sensors**, not the top-right
plus button or **Add device**. Configure also contains **Refresh settings**.

### Rolling back to 2.3

First remove custom sensors through **Configure → Custom sensors** while still
on 2.4. Then redownload v2.3.0 and restart HA. Automations calling
the new ADCP actions will not work on stable 2.3; disable or adapt them before
downgrading. Do not downgrade to beta 1, which contains the ownership regression.

### From 2.2.4 or a 2.3 beta to stable 2.3

No integration reconfiguration is needed. Update through HACS and restart HA.
Include picture settings defaults to on, including existing installations; use
**Configure → Refresh settings** to change it or the value-refresh interval.
The historical 2.3 betas are superseded by stable v2.3.0.

### From the original YAML switch

This integration replaces the original `SONY_ADCP` switch component:

1. Install and configure the new integration.
2. Update automations to use the new entities.
3. Remove the old `switch:` YAML configuration.
4. Restart Home Assistant.

The old implementation remains on the repository's `legacy-switch-v1` branch.

## Common problems

### The integration is not listed

Confirm the file is exactly `/config/custom_components/sony_adcp/manifest.json`,
not inside another nested repository/component folder. Restart Home Assistant
after copying files or installing an update. An installation through HACS does
not automatically add the projector: use **Settings → Devices & services →
Add integration → Sony ADCP Projector** afterward.

### Discovery finds nothing

- Wait at least 35 seconds with the default advertisement interval.
- Confirm Advertisement/SDAP is enabled on the projector.
- Check UDP `53862`, broadcast routing, VLANs and host/container network access.
- Use **Enter address manually** if broadcasts cannot reach Home Assistant.
- For manual command communication, verify the configured ADCP TCP port is reachable.

### Unavailable in standby

Picture controls and custom sensors becoming unavailable in standby is expected;
they recover after power-on and successful reads. If the **power control/status**
also becomes unavailable, enable the projector setting that keeps networking active in standby. An
energy-saving standby mode may disable the network even though normal control
works while the projector is on. Respect cooldown; do not rapidly cycle power.

### A value is stale, missing or unavailable

Not every model supports every command, choice or counter. Numeric controls
depend on reported ranges, and hour sensors require valid counter responses.
Firmware is read at setup/reload; reload or restart after a firmware update.
Hour counters are snapshots, not live estimates: a short session may not change
an integer-hour value, and shutdown must actually reach standby before its refresh.

Check confirmed Sony power state, **Configure → Refresh settings**, enabled
entities and custom-sensor `last_error`. Custom sensors pause while off or during
transitions. Error/warning entities are setup snapshots, not continuous health
monitoring. See [exact update rules](state-updates.md), [custom-sensor diagnostics](custom-sensors.md#troubleshooting-and-testing)
and [action validation/readback](custom-commands.md#validation-and-scope).

### The icon does not update

Home Assistant and browsers cache brand assets. Restart HA and perform a hard
browser refresh after upgrading.

## Reporting a problem

Include projector model, firmware, installed integration/HA versions and the
steps that reproduce the issue. For actions/sensors, include command name,
query type/operation, configured refresh interval and observed behavior.
Download diagnostics from the integration page and attach the redacted file.
Do not post credentials or sensitive raw custom-query responses.

[Back to the README](../README.md)
