# Changelog

All notable changes to Sony ADCP Projector are documented here.

## 2.4.0b1 (prerelease)

- Added named, read-only custom ADCP sensors as Home Assistant configuration
  subentries: add/edit/remove under an existing projector, with stable entity
  identity, text/numeric output, optional JSON field path and numeric unit.
- Validate command names and always append a query marker. Reject arguments,
  command sequences and templates. Up to 32 sensors per projector.
- Share the operational refresh interval, enabled-entity filtering and existing
  serialized ADCP client. Duplicate commands share a response per cycle,
  including eligible built-in reads. Custom sensors are independent of the
  Include picture settings checkbox.
- Bound custom queries to two seconds per cycle, rotate after interrupted
  batches, and back off failed queries for 60 seconds. Isolate query/conversion
  failures, handle reauthentication and discard stale/removed in-flight values.
- Pause custom reads during power transitions; invalidate caches on confirmed
  power changes and expose custom sensors only while fully on with valid data.
- Document configuration, exact refresh/failure behavior, testing and rollback.
  No stable release or existing power-monitoring defaults are changed.
- Expand the offline regression suite to 132 tests, including real UI schemas,
  subentry-only reloads, disabled entities, duplicate queries, cancellation,
  response parsing, failure isolation and backoff.

## 2.3.0

- Promoted the tested 2.3 beta functionality to a stable release after maintainer
  hardware testing. No additional projector-control behavior changes from beta 4.
- Added fast, bounded power monitoring after Home Assistant power commands:
  immediate status read, then a one-second pause between attempts, with maximum
  windows of 60 seconds for startup and 5 minutes for shutdown. Publish confirmed
  startup/cooling states promptly; return to normal SDAP/watchdog monitoring when
  the target is reached or the monitor stops
  ([#16](https://github.com/tokyotexture/home-assistant-sony-adcp/issues/16)).
- Added **Include picture settings**, enabled by default, for supported, enabled
  picture mode, video mute, brightness, contrast, sharpness, light output, and
  Reality Creation resolution/noise controls at the configured input/signal
  interval. Bound optional reads and retain cached values on failures.
- Added optional main firmware in device info, plus Operation hours and
  Light-source hours sensors. Read counters at setup and after confirmed shutdown
  to standby; no periodic hour polling is added
  ([#12](https://github.com/tokyotexture/home-assistant-sony-adcp/issues/12)).
- Added a complete per-entity refresh reference, including power deadlines,
  command readbacks, disabled-refresh behavior, and stale diagnostic limitations.
- Fixed the large README image inside HACS by using an absolute image URL.
  The separate HACS listing-icon limitation is not fixed by this release.
- Includes 92 regression tests covering protocol cancellation, power transitions,
  picture refresh, firmware/counters, authentication, DHCP changes, and lifecycle.

## 2.3.0b4 (prerelease)

- Added optional main firmware from `version ?` to device info, read once at
  setup/reload. Skip laser-module firmware and gracefully omit unsupported data
  ([#12](https://github.com/tokyotexture/home-assistant-sony-adcp/issues/12)).
- Added diagnostic **Operation hours** and **Light-source hours** sensors for
  valid `operation` and `light_src` counters from one `timer ?` reply. Sensors
  use hours, duration device class, stable IDs, and total-increasing statistics.
- Read counters at setup and when power actually reaches standby/saving standby,
  including remote-control shutdowns observed by SDAP or the existing watchdog.
  No 10-second or other periodic timer polling is added. If the first read was
  inactive/unavailable, retry once at on while no counters are known.
- Background shutdown reads do not delay standby publication. Deduplicate
  repeated standby announcements, retain counters on optional read failures,
  handle partial/invalid replies without inventing zero, and skip known
  unsupported timer commands until reload. Preserve real counter resets to zero.
- Preserve firmware during SDAP identity fallback, wait for DHCP migration
  before background timer reads, and cancel pending reads on unload.
- Added 31 parser, lifecycle, entity metadata, and real-TCP regression tests;
  the suite now contains 92 tests. Hardware validation is pending.

## 2.3.0b3 (prerelease)

- Added **Include picture settings**, enabled by default, to the integration's
  Configure screen. Supported, enabled controls now share the configurable
  input/signal refresh interval: picture mode, brightness, contrast, sharpness,
  light output, Reality Creation resolution/noise, and video mute.
- Update the existing entities when values change through the projector's own
  remote or menus. Disabled entities are not periodically queried, and commands
  are deduplicated on the existing serialized ADCP connection.
- Publish input/signal before picture reads; query picture mode before dependent
  controls. Limit picture reads to a two-second budget per cycle and back off
  failed/timed-out settings for 60 seconds, preserving last known values.
- Stop optional reads during power commands/transitions, discard stale replies
  after power/option changes, and avoid overlapping refresh cycles. Existing
  60-second startup and 5-minute shutdown monitoring limits are unchanged.
- Added 18 picture-refresh tests, bringing the suite to 61. Custom-command
  sensors remain a separate feature; hardware testing is needed for this beta.
- Corrected outdated options-screen text that claimed power was never polled.

## 2.3.0b2 (prerelease)

- Keep startup monitoring bounded to 60 seconds, but extend shutdown monitoring
  to 5 minutes. Initial VPL-VW535 testing showed approximately 2 minutes
  14 seconds between the first reported cooling state and standby.
- Both limits include network waits, and monitoring still stops immediately
  when the requested endpoint is confirmed. The one-second interval, normal
  SDAP/watchdog behavior, and no-command-resend policy are unchanged.
- Added regression coverage for both default deadlines and cooldown continuing
  beyond the startup deadline; the suite now contains 43 tests.

## 2.3.0b1 (prerelease)

- Added bounded, asynchronous power-transition monitoring after a successful
  Home Assistant turn-on or turn-off command
  ([#16](https://github.com/tokyotexture/home-assistant-sony-adcp/issues/16)).
- Query `power_status ?` immediately and approximately every second, reusing
  the serialized ADCP connection. Stop at the requested endpoint (`on` or
  `standby`/`saving_standby`) or after 60 seconds, including network waits.
- Publish confirmed startup and cooling states without waiting for input or
  signal reads. Never resend the power command or guess a successful outcome.
- Ignore potentially stale SDAP power reports during this short window, while
  continuing to accept discovery and DHCP address changes. Resume normal SDAP,
  the existing 60-second watchdog, and configured input/signal refresh afterward.
- A successful new power command replaces the previous monitoring window;
  authentication failure and integration unload stop monitoring cleanly.
- Added the media player's `power_transition` attribute (`on`, `off`, or null)
  to indicate an active requested transition, independent of confirmed power.
- Added 19 lifecycle and state-race tests, bringing the suite to 40 tests.
  Projector hardware validation is pending for this beta.

## 2.2.4

- Fixed ADCP reply desynchronization after task cancellation, which could expose
  an input, signal, or command acknowledgement as the projector's power state
  ([#14](https://github.com/tokyotexture/home-assistant-sony-adcp/issues/14)).
- Interrupted exchanges now close the connection before another command can
  acquire it, including cancellation during greeting and authentication.
- Added TCP regression tests for interrupted replies and the SDAP-triggered
  cancellation path. Cancellation while waiting for the command lock continues
  to leave the active exchange alone.
- Confirmed by the reporter on a VPL-XW5000ES (firmware 1.101) using the
  2.2.4b1 prerelease. Power-cycle testing no longer produced other commands'
  replies or a false on state during cooling.
- Known issue: a delayed standby-to-startup update can still occur after
  turn-on. This separate status-latency issue is not fixed in this release.

## 2.2.3

- Prevented long-running operational polling from blocking Home Assistant
  bootstrap.
- Added 60-second power-state reconciliation so missed or stale SDAP
  announcements self-correct.

## 2.2.2

- Added bundled Home Assistant integration branding.
- Added 256 px and 512 px icon assets.

## 2.2.0

- Added configurable input and signal refresh while the projector is on.
- Kept power fully push-driven through SDAP.
- Added Disabled, 5-second, 10-second, and 30-second refresh options.
- Clear input and signal state when standby or cooling is announced.

## 2.1.1

- Extended discovery to 35 seconds to cover Sony's default 30-second
  advertisement interval.
- Added a cancellable native Home Assistant discovery progress screen.

## 2.1.0

- Added serial-number-based tracking across DHCP address changes.
- Preserve the Home Assistant device, entities, history, and automations when
  the projector obtains a new address.

## 2.0.0

- Replaced the legacy YAML switch with a config-entry integration.
- Added a native projector-class media player.
- Added async ADCP communication and Sony SHA-256 authentication.
- Added SDAP discovery and push power state.
- Added input, signal, diagnostics, video mute, picture mode, and supported
  numeric image controls.
- Added reauthentication, reconfiguration, diagnostics, and clean unload.
