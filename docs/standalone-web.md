# Standalone web operator

Bibleit supports three independent entry points:

1. `bibleit` opens the keyboard-first Textual application.
2. `bibleit --web` runs the optional browser operator and audience viewer.
3. `create_operator_router` embeds only the operator API in a host FastAPI app.

Install and start the standalone path with:

```sh
pip install 'bibleit[web]'
bibleit --web 0.0.0.0 8000
```

The command prints the loopback operator URL and the audience addresses. By
default, `/operator` and `/api/v1/bibleit` accept requests only from loopback;
the audience viewer at `/` remains reachable on the LAN. This access policy is
part of the standalone composition, not the reusable aiohttp adapter.

The standalone app composes one `OperatorService` with the local audience hub,
the native translation catalogue, optional configured relay publishing, local
configuration, and explicitly enabled install/remove/configuration
capabilities. Its HTML and JavaScript contain no operator business logic: all
state changes use the same versioned API and typed event stream as FastAPI.

Static UI assets use `Cache-Control: no-cache` so an HTML/API deployment cannot
silently retain an incompatible script. The first-run screen directs the user
to the translation library, and the share panel generates a QR code for the
actual LAN audience address discovered by the standalone process.
