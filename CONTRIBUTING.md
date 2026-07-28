# Contributing

Bug reports, projector compatibility reports, documentation improvements, and
pull requests are welcome.

## Reporting a problem

Please include:

- Home Assistant version
- Sony ADCP Projector version
- Projector model and firmware version
- Whether ADCP authentication is enabled
- Whether SDAP advertisements reach Home Assistant
- Relevant debug logs
- Redacted diagnostics downloaded from the integration page

Never post a projector password or unredacted Home Assistant configuration.

## Development

Use Python 3.13 or newer.

```bash
python -m unittest discover -s tests -v
ruff check .
```

Keep network communication asynchronous, avoid blocking Home Assistant's event
loop, and add focused tests for protocol behavior.
