# Changelog

All notable changes to Sony ADCP Projector are documented here.

## 2.4.1b2 — 2026-10-23 (prerelease)

- Retry picture-setting `err_inactive` replies at the configured 5/10/30-second
  interval during the first 60 seconds after confirmed `on`. Do not turn a brief
  startup rejection into a mandatory 60-second per-setting backoff. Repeated
  `on` announcements do not extend the window. Persistent inactivity after the
  window, unsupported commands, connection failures and timeouts retain the
  existing 60-second backoff and two-second picture batch budget.
- Finish pending initial picture reads on the existing configured loop even
  with Include picture settings off; stop reading each control after its first
  success in that mode. Disabled polling stays disabled: pending initial reads
  retry on eligible core refreshes, without creating another polling task.
- Log failed built-in picture reads and their retry eligibility at debug level
  without logging successful setting values. Add six startup-recovery regressions
  and document timing and physical-projector checks. Custom-sensor retry rules,
  fast power monitoring and stable v2.4.0 remain unchanged.
- Maintainer beta 1 hardware feedback on VPL-VW535, firmware 5.003 confirmed
  shutdown unavailability, standby-restart entity persistence, automatic recovery
  and a successful Brightness write. Beta 2 needs a new startup timing test;
  the exact cause of the observed one-minute beta 1 delay is not yet proven.

## 2.4.1b1 — 2026-10-23 (prerelease)

- Preserve positively discovered built-in command metadata in the projector's
  config entry. Numeric controls keep their existing entity IDs after a reload
  or HA restart in standby, rather than appearing as "no longer provided".
  Cache only capabilities, never operational values; reject corrupt ranges and
  metadata from a known different model/serial/MAC identity.
- Picture controls are unavailable while off, starting/cooling, undergoing a
  commanded transition, or awaiting a successful read. Clear stale readings on
  power changes and failed reads without removing the entity. Perform an initial
  read after confirmed startup even with periodic picture refresh disabled.
- Probe capabilities only while fully on. Preserve successful partial results,
  retry inactive/transport/malformed replies on the existing 60-second watchdog,
  and distinguish explicit unsupported commands from temporary failures. Bound
  each discovery pass to 15 seconds and rotate pending commands after timeouts.
- Add offline and real Home Assistant lifecycle/registry regressions. Keep stable
  v2.4.0 unchanged. After upgrading, turn the projector on once to seed the new
  metadata cache; 2.4.0 did not persist capabilities and cannot supply that cache.

## 2.4.0 — 2026-10-22

- Stable release of the tested 2.4 betas. The maintainer confirmed Query/Send
  ADCP actions and custom sensors on Sony VPL-VW535, firmware 5.003. Support for
  individual commands and choices still varies by model and input.
- Add named, read-only custom sensors through Configure → Custom sensors,
  with optional JSON fields and numeric units. Reuse the shared async client
  and configured refresh interval while fully on, with deduplication, bounded
  batches, error backoff and unavailable-state handling.
- Add administrator-only `sony_adcp.query_command` for current values, allowed
  values/ranges and command information, returning responses to Developer Tools
  and scripts. Add `sony_adcp.send_command` for structured Set, Relative, Reset,
  Execute and remote-key operations with metadata/type/range/case validation.
- Preserve explicit power monitoring, never automatically replay writes after
  lost replies, and immediately read back matching enabled sensors/controls
  after acknowledged readable writes. Bound custom actions to 30 seconds and
  cancel them on unload; reject non-power actions during fast power monitoring.
- Include the beta 2 device-ownership fix and automatic migration of remaining
  beta 1 sensors; preserve projector power controls and existing registrations.
- Promote the beta 4 runtime unchanged apart from the version identifier;
  retain all 2.3 power-transition, picture-refresh and usage-hour behavior.

- Shorten the README into a quick start, compatibility overview and guide index.
  Keep detailed update rules in their reference, and move network/authentication,
  upgrade/troubleshooting and development material into linked guides. Record
  maintainer-confirmed 2.4 functionality on VPL-VW535 and document stable upgrades.
- Add an end-to-end discover → control → monitor guide with complete HA scripts
  and a custom-sensor automation: read aspect ratio, check reported choices before
  setting it, react to known-value changes, and wait for confirmed startup.
- Clarify action response versus entity state, device/entity ID placeholders,
  exact-case/model-specific support, polling/freshness limits, unavailable-state
  guards and unsupported raw/network/calibration commands. Historical beta tags
  remain unchanged.
- Validate the guide's copyable YAML, action payloads and choice/startup/state
  guards against real Home Assistant schemas and template rendering in CI.

## 2.4.0b4 (prerelease)

- Add the admin-only, response-returning `sony_adcp.query_command` action for
  current values (for example `aspect`), allowed values/ranges and command info.
  Keep queries separate from write-only Execute operations; accept command names
  only and generate every read-only protocol suffix internally.
- Return the normalized projector reply plus structured JSON objects/arrays,
  preserving scalar strings and exact-case choices. Current-value reads require
  no metadata or custom sensor. Every call is fresh, with no entity-cache updates,
  new entities, polling tasks or refresh-option changes.
- Share authenticated async communication and locks. Bound the entire action to
  30 seconds, pause access during fast power monitoring, discard replies after
  power changes and cancel pending queries on unload. Try alternate Sony metadata
  syntax only on command/option rejection, not inactive/authentication/IO failures.
- Document official Sony aspect queries, script response variables and discovering
  model-specific color-temperature choices. Add query encoding/lifecycle and real
  HA service registration, permissions, response and deadline regressions.
- Retain beta 2's ownership fix and beta 3's structured writes/readback. Stable
  v2.3.0 remains unchanged; new query behavior needs real-projector beta testing.

## 2.4.0b3 (prerelease)

- Add the admin-only `sony_adcp.send_command` action for existing projector
  devices. Support structured Set, Relative, Reset and Execute operations plus
  single remote keys, with an optional acknowledgement/readback response.
- Require recognized menu-command metadata, validate exact-case choices,
  numeric ranges and steps, and reject raw command lines and advanced/network
  writes. Cache successful metadata only. Explicit power and power keys retain
  the existing fast monitor; reject ambiguous power toggles and non-power writes
  during monitored transitions. Cancel active custom actions on unload.
- Read back matching enabled custom sensors and picture controls immediately
  after acknowledged readable writes, even with periodic refresh disabled.
  Keep acknowledgements distinct from completion and readback errors.
- Never automatically replay writes after connection failures, including
  built-in controls; reads retain reconnect/retry behavior. Close cancelled or
  uncertain streams and surface authentication failures through reauth.
- Document actual Sony command names, exact messages, model-specific choices,
  setting reset versus execution, and non-destructive test suggestions in
  `docs/custom-commands.md`, citing the official Sony manual and printed pages.
- Add offline action/transport regressions and real HA service registration,
  permission, routing, response and deadline tests. Retain the beta 2 ownership
  fix, automatic beta 1 migration and stable v2.3.0 release unchanged.

## 2.4.0b2 (prerelease)

- Fix custom sensors making the projector's media-player/power control disappear.
  Keep all sensors and controls owned by the existing projector configuration;
  stop assigning the shared physical device to individual sensor subentries.
- Move add/edit/remove into **Configure → Custom sensors** with a removal
  confirmation. Move refresh options into **Configure → Refresh settings**.
  Remove the separate subentry action (which could appear as an unlabeled +).
- Automatically migrate remaining beta 1 sensor settings and IDs on restart.
  Reparent entity registrations before devices, then remove obsolete subentries;
  preserve existing registrations, names and options where still present. Support
  both legacy shared-device and newer single-owner registry APIs. Already-deleted
  beta 1 registry customizations cannot be reconstructed.
- Remove only intentionally deleted custom sensor registrations on reload,
  never the projector media player or other built-in controls.
- Add real Home Assistant device/entity registry tests on the minimum supported
  and current versions, including reproduction of the beta 1 ownership bug,
  add/edit/remove preservation and safe, idempotent migration.
- Fall back to the TV media-player class on older supported Home Assistant
  versions that do not yet expose a projector class, preventing a platform import
  failure. Newer versions retain the projector class.
- Power polling, refresh budgets, query backoff and all other beta 1 functionality
  are unchanged. Stable v2.3.0 remains the latest stable release.

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
