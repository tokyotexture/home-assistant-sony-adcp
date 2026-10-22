# Changelog

All notable changes to Sony ADCP Projector are documented here.

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
