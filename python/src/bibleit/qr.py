from __future__ import annotations

import io

try:
    import segno
except ModuleNotFoundError as error:  # pragma: no cover - exercised by packaging environments
    raise RuntimeError("QR support requires: pip install 'bibleit[web]'") from error


def svg(url: str) -> bytes:
    output = io.BytesIO()
    segno.make(url[:512], error="m").save(
        output,
        kind="svg",
        scale=8,
        border=2,
        dark="#173c34",
        light="#ffffff",
        omitsize=True,
    )
    return output.getvalue()
