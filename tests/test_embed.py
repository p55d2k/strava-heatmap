"""
Tests for src/map_builder/embed.py - documents embedded in the generated page.

The payload is written by Python (``zlib.compress``) and read back by the
browser (``DecompressionStream("deflate")``), so the contract that matters is
that the two agree on the bytes: these tests pin the Python half, and the panel
JS test (tests/test_control_panel_legend_js.py) inflates a real payload with the
browser API and checks it comes back byte for byte.
"""

import base64
import zlib

import pytest

from src.map_builder.embed import build_embed_demo_html, decode_embedded, encode_for_embedding


class TestEncodeForEmbedding:
    """Tests for encode_for_embedding."""

    def test_round_trips_through_base64_and_zlib(self):
        """Decoding and inflating recovers the original text exactly."""
        text = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<gpx><trk><name>Rückweg</name></trk></gpx>\n'
        )

        payload = encode_for_embedding(text)

        assert decode_embedded(payload) == text

    def test_payload_is_plain_base64(self):
        """The payload is ASCII base64, so it cannot break the script block.

        A document containing markup characters (every GPX and GeoJSON does)
        would need escaping if it were embedded verbatim; base64 has no ``<``,
        ``&``, quote or newline to worry about.
        """
        payload = encode_for_embedding('<?xml version="1.0"?><gpx attr="&"/>')

        assert payload.isascii()
        assert all(c.isalnum() or c in "+/=" for c in payload)
        assert "<" not in payload
        assert "&" not in payload

    def test_matches_zlib_level_9(self):
        """The payload is exactly what zlib.compress(..., 9) produces.

        The browser's ``DecompressionStream("deflate")`` reads the RFC 1950
        wrapper that zlib.compress writes, so the level is the only free
        variable - pinning it keeps the payload size predictable.
        """
        text = "<gpx>" + '<trkpt lat="1.0" lon="2.0"/>' * 200 + "</gpx>"

        payload = encode_for_embedding(text)

        assert base64.b64decode(payload) == zlib.compress(text.encode("utf-8"), 9)

    def test_compresses_a_repetitive_document_far_smaller(self):
        """A real-shaped GPX payload is an order of magnitude smaller.

        This is the whole reason the document is embedded compressed rather
        than verbatim.
        """
        text = "".join(
            f'<trkpt lat="1.4006{i % 10}0" lon="103.8064{i % 10}0"><ele>31.4</ele></trkpt>\n'
            for i in range(4000)
        )

        payload = encode_for_embedding(text)

        assert len(payload) < len(text) / 5
        assert decode_embedded(payload) == text

    @pytest.mark.parametrize("text", ["", "x", "  \n\t  "], ids=["empty", "one-char", "whitespace"])
    def test_handles_degenerate_documents(self, text):
        """Empty and tiny documents survive the round trip too."""
        assert decode_embedded(encode_for_embedding(text)) == text


class TestBuildEmbedDemoHtml:
    """Tests for the demo page that hosts the embeddable widget in an iframe."""

    def test_returns_a_complete_html_document(self):
        """The demo is a standalone page, not a fragment."""
        html = build_embed_demo_html("heatmap_embed.html")

        assert html.lstrip().lower().startswith("<!doctype html>")
        assert "</html>" in html
        assert "<title>" in html

    def test_points_the_iframe_at_the_widget(self):
        """The iframe (and the copy-paste snippet) name the widget file.

        The demo is written beside the widget, so a bare relative filename is
        all the ``src`` needs — it works from a ``file://`` URL with no server.
        """
        html = build_embed_demo_html("widget.html")

        assert '<iframe src="widget.html"' in html
        # The live iframe plus the snippet shown for copying.
        assert html.count("widget.html") >= 3

    def test_frame_sizes_the_iframe_responsively(self):
        """The frame is fluid: fixed aspect ratio with the iframe filling it.

        A fixed aspect ratio is what keeps the map from collapsing to a sliver,
        and the min/max clamps stop it collapsing on a short viewport or
        outgrowing a landscape one, so the page needs all three (plus a fallback
        for browsers without ``aspect-ratio``).
        """
        html = build_embed_demo_html("heatmap_embed.html")

        assert "aspect-ratio" in html
        assert "min-height" in html
        assert "max-height" in html
        assert "@supports not (aspect-ratio" in html  # fallback for older browsers
        assert "@media (max-width: 640px)" in html  # taller frame on phones
        assert "position: absolute" in html
        assert "width: 100%" in html
        assert "height: 100%" in html

    def test_frame_never_collapses_or_outgrows_the_viewport(self):
        """The frame clamps to a sensible height range, in viewport units.

        Without the clamps the frame either shrinks to nothing on a short
        window or grows past the screen on a landscape one, which is why the
        page must express both as ``vh`` limits.
        """
        html = build_embed_demo_html("heatmap_embed.html")

        assert "min-height: 240px" in html
        assert "max-height: 78vh" in html

    def test_has_no_unsubstituted_placeholders(self):
        """Every placeholder is filled in, so the page never shows a raw ``$``."""
        html = build_embed_demo_html("heatmap_embed.html")

        assert "$widget_filename" not in html
