# Discover, control and monitor your projector

For **2.4.0 or newer**. Update through HACS and restart Home Assistant first;
prerelease versions are not required. Older stable v2.3.0 does not include these
custom-command features.

Build automations around additional projector settings without waiting for a
dedicated built-in entity: query a supported command, discover allowed values,
send a supported write, and monitor its value with a custom sensor. This is
broad, model-dependent control, **not an unrestricted ADCP terminal**.

## Choose the right tool

| You want to… | Use | What happens |
| --- | --- | --- |
| Read a value now, such as aspect ratio | **Query ADCP command → Current value** | Fresh data returns to Developer Tools or the calling script. No entity state changes. |
| Find choices, bounds or command type | **Query → Allowed values / range** or **Command information** | Returns what this projector reports; preserve exact spelling/case. |
| Change a setting or press a remote key | **Send ADCP command** | A structured write is validated and sent once; acknowledgement is not completion. |
| Keep a value in HA and react to changes | **Configure → Custom sensors** | A read-only entity refreshes on the shared schedule while fully on. |
| Control power, input or an existing picture setting | Its built-in media-player/select/number/switch entity | Prefer existing entities when available; custom commands complement them. |

Querying does not create a sensor, start a monitor, or list every command the
projector supports. Obtain command names from Sony's documentation for your model.
The [action reference](custom-commands.md#official-sony-examples) links the official
PDF and its printed-page references. `aspect` is a documented menu selection;
choices and availability still depend on model and input.

## Before copying an example

- For a **script**, create a script, open **Edit in YAML**, and paste the entire
  script block. For the **automation**, use a new automation's YAML editor.
  These are not complete `configuration.yaml`, `scripts.yaml`, or
  `automations.yaml` files; those formats need their normal outer mapping/list.
- Replace `YOUR_PROJECTOR_DEVICE_ID` with the internal **device ID**, not a model,
  IP address or entity ID. Select your projector in an ADCP action's visual
  editor, then switch that action to YAML to find it. For the two custom ADCP
  actions, keep `device_id` under `data`, not `target`.
- Replace `media_player.projector` and `sensor.projector_aspect_ratio` with actual
  entity IDs from **Developer Tools → States**. A display name does not guarantee
  a particular entity ID.
- Enter command names only: `aspect`, not `aspect ?` or a raw protocol line.
  Use **Query**, not **Send → Execute**, to read a value. Every Query step in a
  script/automation needs a `response_variable`.
- Run settings examples while fully on, outside fast power monitoring. Inspect
  traces for stopped conditions or action errors. Examples do not bypass model
  support, authentication or validation.

## 1. Read the current aspect ratio

For a quick check, open **Developer Tools → Actions → Sony ADCP Projector:
Query ADCP command**, select your projector, enter `aspect`, and choose
**Current value**. Perform the action to see the response.

This script captures the result and displays a Home Assistant notification:

```yaml
alias: Projector - read aspect ratio
mode: single
sequence:
  - action: sony_adcp.query_command
    data:
      device_id: YOUR_PROJECTOR_DEVICE_ID
      command: aspect
      query_type: value
    response_variable: aspect_result
  - action: persistent_notification.create
    data:
      title: Projector aspect ratio
      message: "Current projector value: {{ aspect_result.data }}"
```

If the projector returns `"normal"`, `aspect_result.data` is the string `normal`.
`response` contains the normalized ADCP reply; `data` additionally parses JSON
objects/arrays. Scalar replies remain strings, even when they look numeric. Use
an explicit numeric conversion for arithmetic; do not treat an error or an
unavailable sensor as zero. See the [response contract](custom-commands.md#query-current-values).

To inspect choices without writing, choose **Allowed values / range**
(`query_type: range`) or **Command information** (`query_type: info`). For example,
query `color_temp` before writing: the maintainer's VW535 accepts `d65`, whereas
the official professional-model PDF includes choices such as `6500K`.
Do not generalize one model's spelling to another.

## 2. Check support, then set an aspect ratio only if needed

This script checks metadata, reads the current value, and writes only if the
reported choice is supported and differs from the current value. `normal` is a
real Sony choice, but **use a choice your own projector reports**. A failed
condition stops the script without proceeding. Rejected actions raise errors.

```yaml
alias: Projector - set supported aspect ratio
mode: single
variables:
  desired_aspect: "normal"
sequence:
  - action: sony_adcp.query_command
    data:
      device_id: YOUR_PROJECTOR_DEVICE_ID
      command: aspect
      query_type: info
    response_variable: aspect_info
  - condition: template
    value_template: >-
      {{ aspect_info.data is mapping
         and aspect_info.data.get('type') == 'menu_sel'
         and aspect_info.data.get('range') is sequence
         and aspect_info.data.get('range') is not string
         and aspect_info.data.get('range') is not mapping
         and desired_aspect in aspect_info.data.get('range') }}
  - action: sony_adcp.query_command
    data:
      device_id: YOUR_PROJECTOR_DEVICE_ID
      command: aspect
    response_variable: aspect_before
  - condition: template
    value_template: "{{ aspect_before.data != desired_aspect }}"
  - action: sony_adcp.send_command
    data:
      device_id: YOUR_PROJECTOR_DEVICE_ID
      command: aspect
      operation: set
      value: "{{ desired_aspect }}"
  - action: sony_adcp.query_command
    data:
      device_id: YOUR_PROJECTOR_DEVICE_ID
      command: aspect
    response_variable: aspect_after
  - condition: template
    value_template: "{{ aspect_after.data == desired_aspect }}"
  - action: persistent_notification.create
    data:
      title: Projector aspect ratio confirmed
      message: "The projector now reports {{ aspect_after.data }}."
```

Send still performs its own metadata validation. The sequence is not atomic:
input, power or settings can change between requests. The final query confirms
one observed value, not lasting state or completion of every physical operation.
If a setting applies later, the final condition can stop the notification; use a
custom sensor to observe subsequent changes instead of blindly repeating writes.

The final Query does **not** update entity caches. Separately, an acknowledged
readable write reads back a matching enabled sensor/control while fully on,
even with periodic refresh Disabled. Without a matching entity, Send adds no
setting readback. See [acknowledgements and readback](custom-commands.md#acknowledgements-readback-and-failures).

## 3. Monitor changes and trigger an automation

Open **Settings → Devices & services → Sony ADCP Projector → Configure → Custom
sensors → Add custom sensor**, and enter:

| Field | Example |
| --- | --- |
| Sensor name | Aspect ratio |
| ADCP command | `aspect` |
| Value type | Text |
| JSON field path / Unit | Leave both empty |

Keep **Configure → Refresh settings → Refresh interval** enabled (10 seconds by
default). **Include picture settings** can be off; custom sensors are independent
of that option. Find the new sensor's real entity ID in States.

This automation notifies on changes between known aspect values, including
remote-control changes detected on a later read:

```yaml
alias: Projector - notify when aspect ratio changes
mode: single
triggers:
  - trigger: state
    entity_id: sensor.projector_aspect_ratio
    not_from:
      - "unknown"
      - "unavailable"
    not_to:
      - "unknown"
      - "unavailable"
conditions:
  - condition: template
    value_template: >-
      {{ trigger.from_state is not none
         and trigger.to_state is not none
         and trigger.from_state.state != trigger.to_state.state }}
actions:
  - action: persistent_notification.create
    data:
      title: Projector aspect ratio changed
      message: >-
        {{ trigger.from_state.state }} → {{ trigger.to_state.state }}
```

Replace the notification with appropriate lighting, screen or receiver actions.
For a specific choice, add `to: "normal"` and remove `not_to`; HA does not allow
both on one trigger. Use the actual Sony value, not a translated label. For a
numeric custom sensor, consider a numeric-state threshold trigger instead.

These **custom sensor entities** are the custom monitors: not independent tasks
or push subscriptions. Their values work in normal HA triggers, conditions,
dashboards and recorded history if included in Recorder. Important limits:

- Available, enabled sensors refresh while fully on, outside fast power
  monitoring. A matching successful write can also publish immediate readback.
- The interval is a schedule, not a hard freshness guarantee. The custom batch
  has a two-second budget and rotating commands; query failures back off for
  60 seconds. Brief changes between reads can be missed.
- Sensors are unavailable off, during startup/cooling and fast monitoring, and
  before their first valid read. This example deliberately ignores initial
  readings and recovery from unknown/unavailable. It will not report changes
  that happened while the sensor was unavailable.
- Unchanged values do not retrigger a state-change automation. A one-off Query
  does not refresh the sensor or trigger this automation.
- Refresh interval Disabled stops periodic custom reads; remote changes are not
  detected then. Enable the shared interval for monitoring instead of adding a
  tight repeated-query automation.

See [custom-sensor timing, JSON fields, limits and troubleshooting](custom-sensors.md#exactly-when-readings-update)
and [the value-by-value refresh reference](state-updates.md).

## 4. Wait for startup before querying settings

The media player's general `on` state can include startup/cooling. Send one
power-on action, then wait for confirmed Sony `on` **and** the end of fast
monitoring before reading settings:

```yaml
alias: Projector - turn on and read aspect ratio
mode: single
variables:
  projector: media_player.projector
sequence:
  - action: media_player.turn_on
    target:
      entity_id: "{{ projector }}"
  - wait_template: >-
      {{ has_value(projector)
         and state_attr(projector, 'sony_power_status') == 'on'
         and state_attr(projector, 'power_transition') is none }}
    timeout: "00:01:15"
    continue_on_timeout: false
  - action: sony_adcp.query_command
    data:
      device_id: YOUR_PROJECTOR_DEVICE_ID
      command: aspect
    response_variable: aspect_result
  - action: persistent_notification.create
    data:
      title: Projector ready
      message: "Current aspect ratio: {{ aspect_result.data }}"
```

The script's 75-second wait does not change the integration's 60-second startup /
300-second shutdown monitor deadlines. On wait timeout it stops without querying.
The later query has its own 30-second deadline. Do not repeat power writes to
accelerate startup or rapidly cycle power. After shutdown, wait for confirmed
standby rather than assuming `ok` means cooling is complete. See [power updates](state-updates.md#power-updates).

## Scope and safety

Queries accept command names without arguments/suffixes. Not every command has
a readable value or supports range/info. Writes support ordinary metadata-described
`menu_sel`, `menu_num`/`menu_val` and `menu_exec` operations, plus explicit power
and remote keys. Network/system configuration, advanced calibration arrays,
suffix/channel arguments and raw protocol lines are not supported. **Execute**
is an operation, not a query; reset/execution commands can discard settings.

Both actions require administrator access for direct user calls; internal
automations/scripts follow HA's admin-action context rules. Treat scripts exposing
writes to other users as privileged controls. Queries share authenticated async
communication and locks, are rejected during fast power monitoring, and have
bounded deadlines. Writes are never automatically replayed after lost replies:
check actual state before retrying, especially relative adjustments or keys.
These are automation building blocks, not a guarantee that every Sony function
is supported or safe to automate.

HA references: [action response variables](https://www.home-assistant.io/docs/automation/action/#action-response-data),
[state triggers](https://www.home-assistant.io/docs/automation/trigger/), and
[script building blocks](https://www.home-assistant.io/docs/scripts/).
