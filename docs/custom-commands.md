# Send and query custom ADCP commands

Available in **v2.4.0b4**, an opt-in 2.4 prerelease. Stable v2.3.0 is unchanged.
Custom sensors remain read-only. The separate **Sony ADCP Projector: Send ADCP
command** action changes settings or performs an operation on an existing projector.
Beta 4 adds **Query ADCP command** for one-off reads and metadata discovery.

Start with [Discover, control and monitor your projector](automation-examples.md)
for copyable scripts that query `aspect`, check choices before writing, wait for
startup, and use a custom sensor to trigger an automation. This page is the
detailed action reference. Support is model-specific; this is not a raw terminal.

## Query current values

After installing v2.4.0b4 through HACS and restarting Home Assistant:

1. Open **Developer Tools → Actions** and select **Sony ADCP Projector: Query
   ADCP command** (`sony_adcp.query_command`).
2. Select the existing projector, enter `aspect` as **Command**, and leave
   **Query type** at **Current value**.
3. Click **Perform action**. The response shows the projector's current value.

Do **not** use Send → Execute for a query: Execute performs a no-value operation
such as resetting picture-mode adjustments. Query never sends a bare command,
value, reset option or relative adjustment. Enter just `aspect`, not `aspect ?`.

| Query type | YAML value | Primary message | Purpose |
| --- | --- | --- | --- |
| Current value | `value` (default) | `aspect ?` | Current aspect-ratio setting |
| Allowed values / range | `range` | `aspect --range` | Discover the choices accepted by this projector |
| Command information | `info` | `aspect --info` | Command type/version and any reported range |

Sony documents `aspect` on printed p. 13 and these menu-query formats on p. 9 of
the [official command-list PDF](https://pro.sony/s3/2018/07/19110602/Sony_Protocol-Manual_Supported-Command-List_1st-Edition-Revised-1.pdf).
Only after `err_cmd` or `err_option`, range/info queries try Sony's alternate
`aspect ? --range` / `aspect ? --info` form (see the system-command formats on
pp. 3 and 5). There is no alternate bare-command execution or metadata probe
before a current-value query. Support still depends on model, input and power state.

In an automation/script, capture the response with `response_variable`:

```yaml
- action: sony_adcp.query_command
  data:
    device_id: YOUR_PROJECTOR_DEVICE_ID
    command: aspect
    query_type: value
  response_variable: aspect_result
- variables:
    current_aspect: "{{ aspect_result.data }}"
```

The action requires a response. Developer Tools displays it; scripts and
automations must specify `response_variable`. An illustrative response, **not a
claim about your model's current setting**, is:

```yaml
command: aspect
query_type: value
response: normal
data: normal
```

`response` is the normalized ADCP reply: line ending, optional command prefix
and surrounding scalar quotes removed by the existing client, not raw bytes.
`data` parses valid JSON objects/arrays; all other replies remain strings,
including numeric-looking scalar values. For numerical comparisons, explicitly
convert with `| float` or `| int`. Choices retain their exact case and spelling;
no friendly-label conversion occurs. Use `command: color_temp` with
`query_type: range` or `info` to discover values such as `d65` if your model
reports them; do not assume the PDF's `6500K` or uppercase `D65` works everywhere.

Each call makes a fresh read using the existing authenticated async connection,
even if periodic refresh is Disabled. It creates no sensor or polling task and
does not update entity caches, power state, refresh options or capability caches.
For ongoing state/history and automations triggered by changes, use a
[custom sensor](custom-sensors.md) instead.

Queries have the same administrator/device-routing rules as writes, share the
serialized connection and refresh locks, and are rejected during the integration's
fast power monitor. Queue waits, connection/reconnect attempts, reply waits and
metadata-syntax fallback all count toward one **30-second deadline**. Reads may
reconnect/retry through the existing client; writes are still never replayed.
Unload cancels pending queries. A power change during a query discards its reply.
Unsupported/inactive queries, authentication failures, connection errors and
timeouts raise action errors, not successful response data. Unsupported commands
are not remembered by this action: a later call attempts a fresh query again.

## Use the Home Assistant UI

1. Install v2.4.0b4 through HACS with prerelease versions enabled, then restart HA.
2. Open **Developer Tools → Actions**, or add an action in an automation/script.
3. Find **Sony ADCP Projector: Send ADCP command** (`sony_adcp.send_command`).
4. Select the **Projector** device, enter a **Command** name, and choose an
   **Operation**. Supply **Value** for Set or Relative; omit it for Reset/Execute.

Administrator access is required for direct user calls. As with other HA admin
actions, internal automations/scripts without a user context can invoke it. Treat
scripts exposing these commands to other people as privileged controls. No new
device, sensor, text entity or integration configuration is needed. For a reusable
dashboard button, save an ordinary HA script that calls this action.

The Value field is text in the UI. Projector metadata determines whether it is
encoded as a quoted choice or an unquoted number. In YAML, numeric values may also
be numbers. Keep selected text values as strings, especially `"on"` and `"off"`.
Do not include ADCP quote characters, `?`, protocol options or line terminators in
the fields. The integration builds the message, authenticates and sends it over
the existing serialized async connection.

## Official Sony examples

Source: Sony's [Protocol Manual: Supported Command List, 1st Edition (Revised 1)](
https://pro.sony/s3/2018/07/19110602/Sony_Protocol-Manual_Supported-Command-List_1st-Edition-Revised-1.pdf).
Page references below use Sony's **printed English page numbers**, not the PDF
viewer page count. The common manual explains ASCII/CRLF framing and communication.

These are real documented command names and choices, **not a guarantee of support
on every projector**. The PDF's model columns matter; its professional-model list
does not establish support on VPL-VW/XW home-cinema models. Check your model's
manual and returned metadata. The maintainer has tested a `color_temp` custom
sensor and a lowercase `d65` write on VPL-VW535. Other operations and the new
query action still need hardware testing.

| Intent | Command | Operation | Value | ADCP message (CRLF appended automatically) | Sony reference |
| --- | --- | --- | --- | --- | --- |
| Select color temperature | `color_temp` | `set` | `6500K` | `color_temp "6500K"` | p. 11: this choice is listed for FHZ120/FHZ90/F1200/F900; other models list different choices |
| Set contrast | `contrast` | `set` | `50` | `contrast 50` | p. 11 command; p. 9 direct numeric syntax. 50 is an illustrative value, validated against your projector's range |
| Reduce contrast by one step unit | `contrast` | `relative` | `-1` | `contrast --rel -1` | p. 11 command; p. 9 relative numeric syntax. Delta must match a reported step when present |
| Restore the contrast setting's default | `contrast` | `reset` | Omit | `contrast --reset` | p. 11 command; p. 9 numeric-setting reset syntax |
| Reset the current picture mode's adjustments | `picture_mode_reset` | `execute` | Omit | `picture_mode_reset` | p. 11: `menu_exec`. **Destructive to those adjustments: use deliberately** |
| Press Menu | `key` | `set` | `menu` | `key "menu"` | p. 21 actual command example; p. 22 key list |
| Turn off | `power` | `set` | `off` | `power "off"` | p. 4. Uses the existing HA power handler and fast transition monitor |

### Color temperature

```yaml
action: sony_adcp.send_command
data:
  device_id: YOUR_PROJECTOR_DEVICE_ID
  command: color_temp
  operation: set
  value: "6500K"
```

Use the exact case and a choice actually reported by your projector. Sony lists
`6500K` for specific professional models; do not assume that your home-cinema
model uses that spelling. If an enabled custom sensor queries `color_temp`, the
action reads it back once after acknowledgement while fully on. You do not need
to wait for the configured interval, and this read works with periodic refresh
disabled. Without a matching enabled sensor/control, it does not add a query.

### Relative adjustment

```yaml
action: sony_adcp.send_command
data:
  device_id: YOUR_PROJECTOR_DEVICE_ID
  command: contrast
  operation: relative
  value: -1
```

### Reset one setting versus execute a reset operation

These are different ADCP operations. Both can discard adjustments.

```yaml
# Restore only the contrast setting's default.
action: sony_adcp.send_command
data:
  device_id: YOUR_PROJECTOR_DEVICE_ID
  command: contrast
  operation: reset
```

```yaml
# Discard adjustments of the currently selected picture mode (Sony p. 11).
action: sony_adcp.send_command
data:
  device_id: YOUR_PROJECTOR_DEVICE_ID
  command: picture_mode_reset
  operation: execute
```

Leave Value out entirely, rather than setting it to an empty string or zero.

### Remote keys

```yaml
action: sony_adcp.send_command
data:
  device_id: YOUR_PROJECTOR_DEVICE_ID
  command: key
  value: menu
```

`set` is the default operation. This sends one key press, with no hold/repeat.
Sony also documents `up`, `down`, `left`, `right`, `enter` and `return` (p. 22).
Supported keys vary by model. No `key ?` readback is attempted. Keys can change
other settings; those values follow their normal refresh rules rather than an
invented mapping from a key to a specific setting.

Use `power` with `"on"`/`"off"` or the normal media-player actions for power.
The explicit `key` values `power_on` and `power_off` are normalized to that same
power path, so transition monitoring is retained. The ambiguous `power` toggle
key is rejected instead of guessing a target or risking an accidental repeat.

## Validation and scope

The metadata/write restrictions below apply to **Send**, not read-only Query.
A current-value Query requires no metadata. Query supports the three generated
read formats above, not arbitrary options or suffix arguments.

- One device and one structured operation per call. Use HA script sequences for
  multiple operations; this is not an atomic transaction or a raw terminal.
- Command names are lowercase ASCII letters, digits and underscores, starting
  with a letter. Text values use simple printable tokens (letters, digits,
  spaces, `_`, `+`, `.`, `/`, `:`, `-`); quotes, backslashes, control characters,
  command sequences, lists and templates embedded in protocol strings are rejected.
  HA itself can template the individual action fields normally.
- The action obtains command metadata using `--info`, with the existing
  `? --info` fallback. Successful metadata is cached for this loaded integration,
  bounded to 128 commands; failures are not cached. Ordinary settings require
  recognized `menu_sel`, `menu_num`/`menu_val`, or `menu_exec` metadata. If none
  is returned, no write is sent. Try while fully on and check model support.
- Choice values preserve exact case. Numeric values must be finite decimal
  numbers, within reported absolute bounds and aligned to a reported positive
  step. Relative deltas use step alignment, not absolute min/max limits; the
  projector decides whether the resulting value is currently allowed.
- Reported metadata is not proof that a value is currently applicable. Changes
  of input/mode can alter availability; Sony can still reject it with `err_val`
  or `err_inactive`. Reset support can also vary by command/model.
- Power and remote keys have explicit protocol handling and do not require
  menu-command metadata. Other system/network writes (`sys_var`/`sys_sel`),
  suffix/channel arguments and advanced calibration arrays/options are excluded.
- Payloads remain limited to 510 ASCII bytes plus CRLF (512 bytes total).
- Non-power commands are rejected during fast power monitoring. Custom actions
  are serialized with each other, power-command handling and operational
  refreshes. Reload/unload cancels active custom actions.

## Acknowledgements, readback and failures

The action waits for acknowledgement, not completion of a physical operation.
`ok` does not mean startup, cooling or lens movement has finished. Power uses the
existing 60-second startup / 5-minute shutdown monitor and confirmed power sensor.

After a successful readable write, enabled matching custom sensors and existing
picture controls get one shared immediate readback while fully on. This does not
enable disabled entities or change the periodic refresh setting. Input commands
also request the existing input/signal/power refresh. The power revision guard
discards a readback made stale by a newer power observation. No optimistic value
is published. Execute commands and remote keys have no automatic value query;
other settings they affect wait for ordinary refresh or an explicit control read.

The 30-second action deadline includes queue waits, connection/authentication,
metadata, the write and readback. Metadata/status reads can reconnect and retry;
**writes are never automatically resent**, including built-in power/input/picture
writes. If acknowledgement is lost, the command may already have executed.
Check the projector before deciding to retry, especially Relative/Execute/keys.
Cancellation closes the stream to prevent a late reply contaminating the next
command. A readback error or timeout after `ok` does not turn that acknowledged
write into a failed action; previous confirmed built-in values are retained, and
invalidated custom values recover on a subsequent successful read.

An optional response variable can inspect acknowledgement and readback:

```yaml
action: sony_adcp.send_command
data:
  device_id: YOUR_PROJECTOR_DEVICE_ID
  command: contrast
  value: 50
response_variable: adcp_result
```

Response keys: `response: ok`, `readback`, and `value` only after a successful
matching read. `readback` is `updated`, `failed`, `skipped` (not fully on/stale),
`not_configured` (no matching enabled entity), `not_supported` (key/execute),
`input_signal_refresh` (the normal refresh was requested, not a guarantee that
each optional read succeeded), or `power_monitor` (monitor started, not completed).
Responses are normalized ADCP strings, not parsed sensor values. Without a response
variable the same action works normally. Rejection, authentication, connection and
uncertain-outcome failures are HA action exceptions, not successful error responses.

## Beta testing

Start with a benign, supported setting and an existing custom sensor; verify that
its value updates immediately and the power control remains visible. Test the
normal automation UI and a script, text/numeric values, relative steps, malformed
input, an unsupported command and a disconnected projector. Reset/Execute
examples are reference examples, **not a required destructive test checklist**.
Confirm ordinary HA power on/off still reaches its endpoint without repeated
power writes. Never rapidly power-cycle a projector; respect its cooldown.
