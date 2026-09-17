"""
Compressed payloads embedded in the generated heatmap page.

The control panel's download buttons hand whole documents to the browser (the
GPX track export, the GeoJSON grid export). Those documents are plain text and
compress roughly tenfold, so the page carries them zlib-compressed and
base64-encoded inside an inert ``<script>`` block rather than verbatim, and
``assets/panel.js`` inflates them in the browser when the button is clicked.
The payload is inert data: the browser never parses or executes it at load time.

base64 keeps the payload safe to drop straight into markup — its alphabet has no
``<``, ``&`` or newline, so the block cannot be broken by, or confused with, the
surrounding HTML — and ``DecompressionStream("deflate")`` reads exactly what
``zlib.compress`` writes (RFC 1950), so neither end needs a library.

The module goes the other way too: an embeddable widget is meant to be shown
*inside* someone else's page, so :func:`build_embed_demo_html` renders the small
demo page written next to it, which hosts the widget in a responsive iframe.
"""

import base64
import zlib
from pathlib import Path
from string import Template

# Level 9: a payload is compressed once at build time and inflated once in the
# browser, so the slowest, smallest setting is the right trade.
_COMPRESSION_LEVEL = 9

_ASSETS_DIR = Path(__file__).parent / "assets"
_DEMO_TEMPLATE = Template((_ASSETS_DIR / "embed_demo.html").read_text(encoding="utf-8"))


def encode_for_embedding(text: str) -> str:
    """Return ``text`` as base64(zlib(text)), ready to embed in a ``<script>`` block.

    Args:
        text: The document to embed (GPX, GeoJSON, ...), exactly as it should
            come back out of the browser.

    Returns:
        An ASCII-only base64 string. Decoding it and inflating the bytes
        (``DecompressionStream("deflate")``) recovers ``text`` byte for byte.
    """
    compressed = zlib.compress(text.encode("utf-8"), _COMPRESSION_LEVEL)
    return base64.b64encode(compressed).decode("ascii")


def decode_embedded(payload: str) -> str:
    """Recover the text :func:`encode_for_embedding` was given.

    The browser decodes its own copy; this exists for tests and for anything
    that wants to read a payload back out of a generated page.
    """
    return zlib.decompress(base64.b64decode(payload)).decode("utf-8")


def build_embed_demo_html(widget_filename: str) -> str:
    """Return a standalone page demonstrating the embeddable widget.

    The demo is written next to the widget itself, so ``widget_filename`` is the
    widget's bare filename and the iframe's relative ``src`` resolves from there
    — no server and no absolute paths needed. The widget is hosted in a fluid
    frame (fixed aspect ratio, iframe filling it edge to edge), which is the
    point of the page: a working, responsive example of how the widget is meant
    to be embedded, plus the snippet to copy.

    Args:
        widget_filename: The widget's filename, relative to the demo page.

    Returns:
        The complete HTML document for the demo page.
    """
    return _DEMO_TEMPLATE.substitute(widget_filename=widget_filename)
