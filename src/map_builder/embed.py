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
"""

import base64
import zlib

# Level 9: a payload is compressed once at build time and inflated once in the
# browser, so the slowest, smallest setting is the right trade.
_COMPRESSION_LEVEL = 9


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
