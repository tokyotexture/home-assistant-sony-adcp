# Changelog

All notable changes to Sony ADCP Projector are documented here.

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
