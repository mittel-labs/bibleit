from __future__ import annotations

import io

import segno

# Fixed rather than themed: scanners want dark modules on a light field, so the
# card behind the code stays light in both themes.
DARK = "#171411"
LIGHT = "#ffffff"
SCALE = 8
BORDER = 2
MAX_LENGTH = 512


def svg(url: str) -> bytes:
    """A scannable QR code for `url`, sized by whatever displays it."""
    out = io.BytesIO()
    segno.make(url[:MAX_LENGTH], error="m").save(
        out,
        kind="svg",
        scale=SCALE,
        border=BORDER,
        dark=DARK,
        light=LIGHT,
        omitsize=True,
    )
    return out.getvalue()
