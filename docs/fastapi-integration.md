# FastAPI integration

Install the optional adapter with `pip install 'bibleit[fastapi]'`, construct an
`OperatorService`, and include its router in the host application:

```python
from fastapi import Depends, FastAPI
from bibleit.integrations.fastapi import create_operator_router

app = FastAPI()
app.include_router(
    create_operator_router(
        service=operator_service,
        prefix="/api/v1/bibleit",
        dependencies=[Depends(require_staff)],
        write_dependencies=[Depends(require_csrf)],
    )
)
```

Bibleit does not choose an authentication scheme. `dependencies` apply host
policy to the whole router, `write_dependencies` add policy to mutations, and
`websocket_dependencies` add any handshake-specific checks. A host-managed
service can instead be supplied with `service_dependency`. Set `close_service`
only when the router owns the service lifetime.

## Version 1 routes

| Method | Route | Result |
| --- | --- | --- |
| GET | `/state` | `OperatorState` |
| GET | `/translations` | Installed slugs and language catalogue |
| POST/DELETE | `/translations/{slug}` | Open or close a translation |
| POST/DELETE | `/translations/{slug}/install` | Install or remove when host-enabled |
| POST | `/commands` | Validate and execute a typed operator command |
| GET | `/verses` | Multi-translation verse window |
| GET | `/books` | Books for an open translation |
| GET | `/resolve?q=` | Reference completion and resolution |
| GET | `/find?q=` | Text search results |
| GET | `/strongs/{code}` | Strong's entry |
| WS | `/events` | Typed state/install events and optional incoming commands |

Command validation failures use HTTP 422, unavailable host capabilities use
403, publish failures use 502, and other reportable operator errors use 400.
All schemas appear in the host OpenAPI document. The router mounts no static
files and does not access configuration or host secrets.
