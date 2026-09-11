"""Screen capture via mss.

Captures the primary monitor to PNG bytes, downscaled so the vision
prefill stays cheap. Import of ``mss`` is lazy so this module never
breaks the app import on systems without it.
"""

from __future__ import annotations

import io

MAX_CAPTURE_WIDTH = 1568


def capture_primary_monitor_png() -> bytes:
    """Capture the primary monitor; return PNG bytes.

    Raises:
        RuntimeError: with a user-friendly message if capture fails.
    """
    try:
        import mss
    except ImportError:
        raise RuntimeError(
            "Screen capture needs the 'mss' package. Install it with:\n"
            "`pip install mss`"
        ) from None

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "Screen capture needs Pillow. Install it with:\n`pip install Pillow`"
        ) from None

    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            # monitors[0] spans all displays; monitors[1] is the primary.
            target = monitors[1] if len(monitors) > 1 else monitors[0]
            shot = sct.grab(target)
    except Exception as exc:
        raise RuntimeError(
            f"Couldn't capture the screen: {exc}\n"
            "On Linux this needs an active display session; on macOS, "
            "grant Screen Recording permission to your terminal/Python."
        ) from None

    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if img.width > MAX_CAPTURE_WIDTH:
        ratio = MAX_CAPTURE_WIDTH / img.width
        img = img.resize(
            (MAX_CAPTURE_WIDTH, int(img.height * ratio)), Image.LANCZOS
        )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
