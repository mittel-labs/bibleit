# Operator core contract

`bibleit.operator` is the framework-neutral application interface for an
operator host. It imports neither FastAPI nor aiohttp, stores no web socket
objects, and does not write configuration unless the host supplies a store and
grants that capability.

```python
from bibleit.operator import NativeTranslationCatalog, OperatorService, OperatorSession

service = OperatorService(
    session=OperatorSession(targets=[my_publish_target]),
    catalog=NativeTranslationCatalog(),
)
await service.open_translation("KJV")
await service.command("goto", {"value": "John 3:16"})  # compatibility boundary
```

Adapters should validate transport data with `parse_command` and pass the
result to `service.execute`. The string/dictionary `command` method remains a
compatibility boundary only. State is always represented by `OperatorState`;
subscribers receive `StateEvent` and `InstallEvent` values through an async
`EventSubscription`. Call `subscription.close()` when a consumer disconnects.

`OperatorState` is the single state contract. It contains the opened
translation summaries, active slug, current `Reference`, live/Strong's flags,
aggregate and per-target viewer counts, connectivity, publish-target names,
and the committed publish sequence. `StateEvent` contains that exact model.
`InstallEvent` contains a translation slug, an `installing`, `installed`,
`failed`, `cancelled`, or `removed` state, and an optional error message.

The typed command union covers reference navigation, verse/chapter stepping,
opening/closing/selecting translations, live mode, and Strong's visibility.
The compatibility parser rejects unknown commands, unknown fields, coercion of
strings to booleans or integers, missing values, and non-positive references.

Installation, removal, and configuration writes are denied by default. A host
must both supply the corresponding port and opt in with
`OperatorCapabilities`. `service.close()` cancels installation jobs and closes
the session.
