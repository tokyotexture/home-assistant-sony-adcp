# How values update

This reference describes **2.3 beta, starting with v2.3.0b4**. It includes the
picture-setting refresh introduced in beta 3 and firmware/usage hours introduced
in beta 4. It does not describe the older stable v2.2.4 behavior.

The integration uses one shared asynchronous ADCP client. Entities display its
cached values; they do not each run their own polling loop. SDAP announcements
carry power/discovery information, **not** input, signal, picture settings, or
hour counters. Those values require ADCP queries.

- [Refresh options](#refresh-options)
- [Entity and value reference](#entity-and-value-reference)
- [Media-player attributes](#media-player-attributes)
- [Power updates](#power-updates)
- [Refresh timing and failures](#refresh-timing-and-failures)
- [Errors and warnings: snapshot only](#errors-and-warnings-snapshot-only)
- [Usage-hour counters](#usage-hour-counters)
- [Device information and capabilities](#device-information-and-capabilities)
- [Examples and automation guidance](#examples-and-automation-guidance)

## Refresh options

Open **Settings → Devices & services → Sony ADCP Projector → Configure**.

| Option | Default / choices | Exactly what it controls |
| --- | --- | --- |
| Refresh interval (`operational_refresh_interval`) | 10 seconds; Disabled (`0`), 5, 10, or 30 seconds | The dedicated loop for input, signal, and optionally the eight picture controls listed below. Runs only while the projector is available and fully `on`. Pauses during fast power-transition monitoring. |
| Include picture settings (`refresh_picture_settings`) | On, including existing installations | Adds supported, enabled picture controls to that same loop. Off leaves only input and signal in the loop. Has no effect if the interval is Disabled. |

Changes apply without reloading. These options do **not** change the SDAP
advertisement interval, the independent power watchdog, fast power-monitoring
deadlines, setup reads, command readbacks, error/warning snapshots, or usage-hour
triggers. Those timings are not configurable in this UI.

**Disabled does not mean no ADCP queries.** It stops the dedicated configurable
loop, including all periodic picture reads. The independent power watchdog
still checks power about every 60 seconds and reads input/signal if fully on.
Event-triggered input/signal reads and direct control readbacks also remain.
Disabling the Signal entity alone does not suppress the shared input/signal
queries; enabled-entity filtering applies to the optional picture controls.

## Entity and value reference

These are all currently implemented entity types. Names below are the English
entity labels, not fixed entity IDs: Home Assistant adds your device name and
allows renaming.

For the table:

- **Core refresh** means `power_status ?`, followed by `input ?` and `signal ?`
  only if the confirmed power is `on`. It runs at setup, on the independent
  power watchdog, after a changed SDAP power/address announcement, after Home
  Assistant input selection, and after the fast turn-on monitor reaches `on`.
  It is skipped while fast power monitoring is active. Repeated unchanged SDAP
  announcements do not themselves trigger new ADCP queries.
- **Configured refresh** means the loop controlled by Refresh interval, subject
  to the power/availability conditions above. It reads input/signal first, then
  eligible picture controls if Include picture settings is on.
- **Initial control read** means a query when an enabled control entity is added
  to Home Assistant, including after integration setup/reload. It is attempted
  even if the projector is not on, but the projector may reject it then.
- **Own-command readback** means a query immediately after Home Assistant
  successfully sends a change to that same control. It is independent of both
  refresh options; a failed read retains the previous value rather than
  assuming the requested change succeeded.

| Entity / displayed value | ADCP read | How and when the value updates |
| --- | --- | --- |
| Projector media player: on/off | `power_status ?`, plus SDAP | Shares confirmed power with Power status below. `standby` and `saving_standby` mean off; startup, on, and cooling appear as on. This represents a display, not playback. |
| Projector media player: current input (`source`) | `input ?` | Core refresh while on, plus configured refresh. Home Assistant input selection requests a core refresh after the command. Cleared whenever power is not `on`; there is no separate input sensor. |
| Power status sensor | `power_status ?`, plus SDAP | Setup, SDAP, independent power watchdog, core refreshes, and temporary fast power monitoring. Detailed states can include `standby`, `startup`, `on`, `cooling1`, `cooling2`, and `saving_standby`, depending on model. Not part of configured refresh. |
| Signal sensor | `signal ?` | Same read triggers as current input. Reports the projector's signal/format string; cleared whenever power is not `on`. A successful input change need not produce a new signal immediately: later refreshes pick up signal lock. |
| Picture mode select | `picture_mode ?` | Initial control read, own-command readback, and configured picture refresh. |
| Brightness number | `brightness ?` | Initial control read, own-command readback, and configured picture refresh. |
| Contrast number | `contrast ?` | Initial control read, own-command readback, and configured picture refresh. |
| Sharpness number | `sharpness ?` | Initial control read, own-command readback, and configured picture refresh. |
| Light output number | `light_output_val ?` | Initial control read, own-command readback, and configured picture refresh. |
| Reality Creation resolution number | `real_cre_reso ?` | Initial control read, own-command readback, and configured picture refresh. |
| Reality Creation noise filtering number | `real_cre_noise ?` | Initial control read, own-command readback, and configured picture refresh. |
| Video mute switch | `blank ?` | Initial control read, own-command readback, and configured picture refresh. `on` means the picture is blanked; it does not mean the projector is off. |
| Errors diagnostic sensor | `error ?` | Setup/reload only, and only if the setup power read returns `on`. Not part of either periodic loop or shutdown refresh. See the snapshot limitation below. |
| Warnings diagnostic sensor | `warning ?` | Same setup-only behavior as Errors. Not part of either periodic loop or shutdown refresh. |
| Operation hours diagnostic sensor | `timer ?` → `operation` | One shared counter read at setup and on a transition from a known non-standby state into `standby`/`saving_standby`. Also retry on transitions to `on` while no counters are known, unless the command is known unsupported. No periodic refresh. |
| Light-source hours diagnostic sensor | `timer ?` → `light_src` | Same shared read and triggers as Operation hours. Only returned counters get sensors. |

Numeric entities are created only when the projector reports a minimum and
maximum for that command. Picture mode and Video mute are offered but may be
unavailable until command support or a successful value read is known. Hour
sensors appear only after a valid counter is received, including a genuine zero.
None of these optional values is synthesized for unsupported commands.

## Media-player attributes

An attribute is extra information attached to an entity, not another entity.
You can inspect these on the media player in **Developer tools → States**.

| Attribute | Meaning and update trigger |
| --- | --- |
| `sony_power_status` | Same cached confirmed value as the Power status sensor. No extra query. |
| `power_transition` | `on` or `off` after a Home Assistant power command is acknowledged, while the corresponding fast monitor is active. Becomes null when the monitor stops, including success, timeout, authentication failure, replacement, or unload. It is the requested endpoint, not confirmed power. |
| `signal` | Same cached value as the Signal sensor, with exactly the same refresh triggers. No extra query. |

The standard media-player `source` uses the input read described above, with a
friendly label such as HDMI 1. Its `source_list` comes from capability discovery,
not repeated value queries; HDMI 1 and HDMI 2 are the fallback choices.

## Power updates

Power has its own update paths, independent of the configurable value interval:

| Path | Timing and scope |
| --- | --- |
| Setup/reload | Reads `power_status ?` before optional status values. |
| SDAP push | Applies a recognized power announcement when it arrives. The projector controls its advertisement interval, normally 30 seconds; this is not instantaneous push on every state change. A changed power/address announcement also schedules a core ADCP refresh. |
| Independent watchdog | Waits 60 seconds between core refresh attempts, regardless of the last believed power state. Corrects missed/stale announcements. Skips reads while fast monitoring is active. Also reads input/signal if on, but not picture settings, errors, warnings, or hours. |
| Home Assistant turn-on | After acknowledgement, queries `power_status ?` immediately, then waits one second after each reply before the next query. Stops at confirmed `on`, or after at most 60 seconds. |
| Home Assistant turn-off | Same fast checks, stopping at confirmed `standby` or `saving_standby`, or after at most 300 seconds (5 minutes). Cooling is not treated as completed shutdown. |

Fast monitoring reuses the shared asynchronous connection; it does not create a
thread or resend the power command. Its deadline includes network and lock
waits. A new successful power command replaces the previous monitor.

During fast monitoring, ADCP power readings take priority over SDAP power and
normal configurable refresh pauses. DHCP address changes still work. At the end,
ordinary SDAP/watchdog behavior resumes; a successful turn-on also schedules a
core refresh for input/signal. A remote-control power command does **not** start
the fast monitor: it is detected through normal SDAP or the watchdog instead.

No power state is assumed from a successful command acknowledgement. Use Power
status or `sony_power_status` for completion, not just a null `power_transition`.
A timeout means monitoring ended, not that the projector reached its target.

## Refresh timing and failures

The configured loop waits the chosen interval **between completed cycles**.
Query time is additional, and all ADCP requests share a serialized connection.
The setting is therefore a polling interval, not a guaranteed detection latency.
Setup/control-triggered reads can occur outside that cadence.

Each cycle reads input and signal first and publishes them before optional
picture reads. Picture controls are attempted in this order: Picture mode,
Brightness, Contrast, Sharpness, Light output, Reality Creation resolution,
Reality Creation noise filtering, then Video mute.

Only supported picture commands with enabled entities are included. All picture
reads together have a **two-second budget**, including connection/lock waits;
this budget does not cover the preceding input/signal queries. With all eight
picture controls eligible, a cycle attempts up to ten value queries, not ten new
connections. A slow projector may not reach every control in each cycle.

A failed picture read keeps its last known value and backs that command off for
at least **60 seconds**. Other controls can still be read within the remaining
budget. A budget timeout ends the picture phase and backs off the command that
was in progress. Stale in-flight picture results are discarded after relevant
power/option changes. Periodic picture updates are published when values change.

Input/signal read failures also keep their previous values. When power leaves
`on`, however, input and signal are explicitly cleared. Picture controls retain
their last read values in standby/startup/cooling; those are **not** proof of the
current menu settings. Changing Picture mode through Home Assistant immediately
reads back Picture mode only: dependent numeric settings catch up on later
configured picture refreshes, if enabled.

Optional setting/counter failures do not by themselves mark the whole projector
unavailable. Power/connection failures can do so, and rejected credentials start
reauthentication. After an SDAP announcement, a 95-second silence timer can also
mark the device unavailable; successful ADCP reads can restore availability.
Cached data and availability are distinct: a cached value is not proof it was
recently read. All entities share the manager's availability, with additional
support checks for Picture mode/Video mute.

## Errors and warnings: snapshot only

`error ?` and `warning ?` are queried only during integration setup/reload, and
only when the projector is fully `on` at that point. Turning on later, changing
an input, regular SDAP announcements, the power watchdog, configured refresh,
and shutdown counter reads do **not** update these diagnostic snapshots.

The current implementation starts with empty error/warning lists and displays
`no_err` / `no_warn` when the respective list is empty. If setup happened in
standby or the optional read failed, those labels are **not confirmation** that
the projector was checked and found healthy. Old errors/warnings can likewise
remain after the real condition changes. Reload while fully on to attempt a
new read. Do not use these sensors as continuously monitored safety/health
signals in automations.

## Usage-hour counters

`timer ?` reads `operation` and `light_src` together. It runs at setup, then in
the background after actual shutdown into standby/saving standby from a known
active state. This applies to Home Assistant and remote shutdowns once detected;
sending an off command alone does not refresh hours. Repeated standby reports,
including a change between the two standby states, do not trigger extra reads.

If no counters have been obtained, a transition to `on` also requests a retry.
A confirmed unsupported command (`err_cmd`) stops further timer attempts until
reload. Other failures preserve known counters; partial responses update only
the returned valid fields. The shutdown read waits for any pending SDAP address
migration and does not hold up publishing standby.

These are integer-hour snapshots reported by the projector, not live estimates.
They can stay unchanged through a short session or become stale during a long
on session until shutdown. Genuine zero values and device counter resets are
accepted; Home Assistant never resets the projector counters. Both sensors use
hours and total-increasing statistics. Cached readings are retained during the
current integration session, not restored by this integration across reloads.

## Device information and capabilities

These values are metadata, not additional periodically refreshed sensors.

| Value | Where it comes from / when it updates |
| --- | --- |
| Model | `modelname ?` at setup/reload; discovery announcements can supply missing identity information. |
| Serial number | `serialnum ?` at setup/reload; serial in discovery announcements identifies the same projector after DHCP changes. |
| MAC address | `mac_address ?` at setup/reload. Used for device identity information. |
| Firmware | `version ?` at setup/reload; only the `main` version is used in the device's firmware field. Laser-module firmware is ignored. Reload/restart after a firmware update to reread it. |
| Manufacturer | Fixed to Sony; no device query. |
| Device name | Your configured name, not a periodically queried projector value. |
| Host / configuration URL | Configured address, automatically migrated and saved after a matching serial-number SDAP announcement from a new address. Without an advertised serial, use Reconfigure. |
| Input choices | Command-info probe for `input`, with HDMI 1/HDMI 2 fallback. |
| Picture-mode choices | Command-info probe for `picture_mode`, with built-in fallback modes if choices are not reported. |
| Numeric ranges | Command-info probes for `brightness`, `contrast`, `sharpness`, `light_output_val`, `real_cre_reso`, and `real_cre_noise`. Determines which number entities can be created. |
| Video-mute support | Command-info probe for `blank`, or a successful value read. |

Capability discovery uses command-info queries, with Sony's alternate syntax as
a fallback. It is attempted at setup if power is not unknown or standby; when
deferred, it can run after an active-state SDAP refresh or successful monitored
turn-on. It is not repeated on every configured refresh. Reload to reprobe
capabilities. Reconnecting the TCP client alone does not reread stable identity
or firmware.

Downloading integration diagnostics exports the current cached identity, power,
input, signal, errors, warnings, hours, availability, and capability information.
It does **not** query the projector or make stale values fresh.

## Examples and automation guidance

- **Remote changes HDMI input:** while fully on, the next successful configured
  refresh updates media-player source and Signal. With the configurable loop
  Disabled, the independent watchdog can still pick these up about every
  60 seconds, or an intervening core refresh may find them earlier.
- **Remote changes Sharpness:** the next eligible configured picture refresh
  updates the existing Sharpness number. If Include picture settings is off or
  the interval is Disabled, it remains cached until a later initial control
  read, a successful Home Assistant Sharpness command/readback, or reenabled
  picture refresh. There is no SDAP push for this setting.
- **Home Assistant changes Picture mode:** its own readback is immediate after
  the command; other affected picture values wait for their eligible refresh.
- **Wait for startup:** trigger on Power status becoming `on`. The media player
  already appears on during startup, so its on/off state is less specific.
- **Wait for shutdown:** use Power status `standby` or `saving_standby`, not
  `power_transition` becoming null. Usage hours update afterward in the
  background and can remain unchanged for short sessions.
- **React to signal changes:** use the Signal sensor and allow for detection
  delay, empty/unknown values outside `on`, failed reads, and network availability.
  No selected interval guarantees a precise timestamp for physical signal lock.

Arbitrary custom-command sensors (`custom1`, `custom2`, and similar) are not
implemented in this beta. Only the values and controls listed here are managed.

[Back to the README](../README.md#state-updates)
