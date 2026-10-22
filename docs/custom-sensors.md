# Custom ADCP sensors (2.4 beta)

Custom sensors expose additional read-only ADCP values as named Home Assistant
sensor entities. They belong to your existing projector and reuse its host,
credentials, connection and refresh loop. No YAML, extra TCP sessions, fixed
custom1/custom2 slots, or per-sensor polling tasks are needed.

This is experimental functionality in **v2.4.0b1**, on
`beta/2.4-custom-sensors`. Stable v2.3.0 is unchanged. Model-specific commands
and their response formats still need hardware testing.

## Install the beta

In HACS, open Sony ADCP Projector, choose **Redownload**, enable prerelease/beta
versions if necessary, select **v2.4.0b1**, and restart Home Assistant. Back up
your configuration first. Home Assistant 2026.3 or newer is required.

## Add, edit or remove a sensor

1. Open **Settings → Devices & services → Sony ADCP Projector**.
2. On your existing projector entry, choose **Add custom sensor**. These are
   Home Assistant configuration subentries, not new projector connections.
3. Enter the fields below and save. Adding, editing or deleting a custom sensor
   reloads the projector integration; you do not need to restart Home Assistant.
4. Turn the projector fully on and wait for the next configured refresh cycle.
   Saving validates the configuration, but deliberately does not query a
   potentially sleeping projector or guarantee model-specific support.

Use the custom sensor subentry's menu to edit or delete it. Editing preserves
its unique identity and entity history, including when changing its command.
If you also want to change an entity name that you previously customized in
Home Assistant, rename that entity in its settings. Disabling the entity stops
its query once Home Assistant removes it from the platform; deleting the
subentry removes its entity registration. At most **32 custom sensors** may be
configured per projector.

| Field | Meaning |
| --- | --- |
| Sensor name | A meaningful name, such as Aspect ratio; 1–100 characters. |
| ADCP command | A lowercase command name such as `aspect`. The integration sends `aspect ?`. Arguments, spaces, `?`, newlines, command sequences and non-ASCII command names are rejected. Maximum 64 characters; start with a letter, then use letters, digits or underscores. |
| Value type | `text` or `number`. Numeric output must be finite; booleans, null, NaN, infinity and nonnumeric replies are not converted to zero. |
| JSON field path | Optional. Empty means use the whole normalized ADCP response. For JSON, dot-separated keys and zero-based array indexes select a scalar, for example `0.main` or `status.level`. Keys containing dots are not supported. No templates or executable expressions are evaluated. |
| Unit | Optional display unit for numeric sensors, such as `%`; maximum 30 characters. Clear it when changing to text. No device class, statistics type, scaling or unit conversion is inferred. |

For example, if your model supports `aspect ?` and returns `normal`, choose
command `aspect`, type `text`, and leave JSON field/unit empty. Command support
varies by model; this is not a promise that `aspect` works on every projector.

For a **hypothetical** query returning `[{"level":42}]`, selecting JSON field
`0.level` with type `number` yields 42. Select a field whose units you know;
adding a unit only labels the value. A JSON object/array selected as the final
value is invalid, rather than being rendered as a fake measurement. With no
JSON field, text mode can show the whole response if it fits Home Assistant's
255-character state limit; longer responses need a field selector.

## Exactly when readings update

- Custom queries run in the existing **Refresh interval** loop (10 seconds by
  default; 5, 10, 30, or Disabled). The projector must be available and confirmed
  fully `on`. The first read is at the next eligible cycle, not when saving.
- Each cycle publishes input/signal first, then optional picture settings, then
  custom sensors. **Include picture settings** does not disable custom sensors.
  With Refresh interval Disabled, no scheduled custom reads occur, even though
  the separate power watchdog still runs.
- Only enabled, added custom entities register a query. Two sensors selecting
  different fields from the same command share one response per cycle. If
  input/signal or an eligible picture control already read that exact command
  in the cycle, the custom sensor reuses that response too, including failures.
- Custom reads have their own **two-second total budget** per cycle, including
  connection/lock waits. This is in addition to the existing two-second picture
  budget. Commands rotate after an interrupted batch so later queries get a
  chance next cycle. Large/slow configurations may therefore update less often
  than the chosen interval. The loop waits the chosen interval **after** the
  previous cycle finishes; it is not a guaranteed wall-clock deadline.
- A failed or timed-out custom query marks only that command's custom sensors
  unavailable and backs that query off for **60 seconds**, until a later eligible
  cycle. Other custom queries continue. Authentication failures request Home
  Assistant reauthentication and stop the custom batch. Response-conversion
  failures affect only the sensor selecting that field; the shared query can
  still supply other valid fields and is retried at the normal interval.
- Custom sensors are unavailable off, during startup/cooling, during a fast
  Home Assistant power-transition monitor, and until their first valid read.
  Power-state changes invalidate custom caches and failure backoff. Normal
  reads resume after confirmed `on` and the end of any fast monitor. The power
  monitor itself still reads **only power**, with the existing 60-second startup
  and 300-second shutdown limits.
- Subentry changes reload the integration and reset the custom cache. Unload
  cancels the shared refresh task; a late reply after a power change or removal
  does not republish a removed/stale value. Unchanged replies do not generate
  redundant entity updates.

There is no manual custom-query service in this beta. SDAP announcements and
the power watchdog do not directly refresh custom values. A custom query of a
built-in value follows the rules above; it does not change that built-in entity's
own refresh behavior. See [all state-update rules](state-updates.md).

## Troubleshooting and beta test checklist

Inspect the sensor in **Developer tools → States**. Its attributes show
`adcp_command`, `json_field` and `last_error`:

- `not_yet_refreshed`: no result yet; check power, Refresh interval and enabled state.
- `query_failed`: rejected/unsupported command or connection failure; retries after backoff.
- `timeout`: custom batch budget expired during this read; retries after backoff.
- `authentication`: check the integration's reauthentication prompt.
- `invalid_response`: wrong field path/type, nonfinite number, or text over 255 characters.
- null: last query and conversion succeeded. Availability still depends on power/connection.

Raw responses and exception details are not exposed in these diagnostic
attributes, to avoid leaking arbitrary custom response data. The existing
downloadable diagnostics do not include custom response caches.

Please test a command supported by your model, duplicate fields from a single
JSON response, edit/remove/disable/re-enable, changes made with the remote,
Refresh interval Disabled, Include picture settings off, and a full power
on/off cycle. Report model, firmware, command, selected path/type, and observed
behavior; do not include passwords or sensitive raw replies.

To roll back, delete custom sensor subentries **while still on the beta**, then
redownload stable v2.3.0 in HACS and restart. Older versions do not implement
custom subentries, so remove them before downgrading rather than leaving
unsupported configuration behind.
