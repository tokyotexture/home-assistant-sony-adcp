# Custom ADCP sensors (2.4 beta)

Custom sensors expose additional read-only ADCP values as named Home Assistant
sensor entities. They belong to your existing projector and reuse its host,
credentials, connection and refresh loop. No YAML, extra TCP sessions, fixed
custom1/custom2 slots, or per-sensor polling tasks are needed.

This is experimental functionality in **v2.4.0b2**, on
`beta/2.4-custom-sensors`. Stable v2.3.0 is unchanged. Model-specific commands
and their response formats still need hardware testing.

## Install the beta

In HACS, open Sony ADCP Projector, choose **Redownload**, enable prerelease/beta
versions if necessary, select **v2.4.0b2**, and restart Home Assistant. Back up
your configuration first. Home Assistant 2026.3 or newer is required.

## Add, edit or remove a sensor

1. Open **Settings → Devices & services → Integrations → Sony ADCP Projector**.
2. Open **Configure** for your existing projector (the gear icon on its entry).
3. Choose **Custom sensors → Add custom sensor**.
4. Enter the fields below and save. Adding, editing or deleting a sensor reloads
   the integration; it does not remove the projector's power or picture controls.
5. Turn the projector fully on and wait for the next configured refresh cycle.
   Saving validates configuration, not model-specific command support.

To edit, use **Configure → Custom sensors → Edit custom sensor**, select a sensor,
then save its settings. Its ID stays unchanged, including if you change the name
or command. Home Assistant entity names that you manually customized are preserved.

To remove, use **Configure → Custom sensors → Remove custom sensor**, select it,
then confirm. Only the selected sensor registration is removed. Disabling its
entity instead stops its query once Home Assistant removes it from the platform.

To change refresh settings, use **Configure → Refresh settings**. Custom-sensor
configuration changes reload the integration; refresh options still apply
immediately without a reload. At most **32 custom sensors** are supported.

There is no separate **+ Add custom sensor** action in beta 2. **Add device**
still means another projector, not another value.

### Upgrading from beta 1

Beta 1 incorrectly assigned the same physical projector device to multiple
sensor subentries. On affected Home Assistant versions this could remove the
media-player entity and its power control when adding a custom sensor.

Beta 2 migrates remaining beta 1 sensors automatically during the first restart:
it saves the settings in the projector's options, reparents existing entity and
device registrations, then removes the obsolete subentries. Existing sensor IDs,
entity IDs and user customizations are kept where those registrations still
exist. Migration is idempotent and supports both the older shared-device and
newer single-owner registry APIs.

You do **not** need to delete/re-add the integration, or manually remove beta 1
sensors before upgrading. Controls already removed by beta 1 can be registered
again on setup. Names or registry customizations already deleted by beta 1 cannot
be reconstructed automatically; check any affected entity IDs and automations.
If you previously removed your beta 1 sensor, add it again through Configure.

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
- Custom-sensor configuration changes reload the integration and reset the custom cache. Unload
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

To roll back cleanly, first remove custom sensors through **Configure → Custom
sensors** while still on beta 2, then redownload stable v2.3.0 in HACS and restart.
Do not downgrade to beta 1: it contains the device-ownership regression.
