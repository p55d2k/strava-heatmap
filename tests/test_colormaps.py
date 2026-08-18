"""
Unit tests for src/colormaps.py - colormap creation and layer URI generation.
"""

import base64
from io import BytesIO

import numpy as np
from PIL import Image

from src.colormaps import (
    _count_uri,
    _rgba_uri,
    _to_uri,
    _white_uri,
    build_cmap,
    create_colormaps,
    generate_layer_uris,
)


class TestBuildCmap:
    """Tests for build_cmap function."""

    def test_creates_colormap_with_correct_name(self):
        """Should create colormap with specified name."""
        nodes = [
            (0.0, (1.0, 0.0, 0.0, 1.0)),
            (1.0, (0.0, 1.0, 0.0, 1.0)),
        ]
        cmap = build_cmap("test_cmap", nodes)
        assert cmap.name == "test_cmap"

    def test_creates_colormap_with_correct_colors(self):
        """Should interpolate colors correctly."""
        nodes = [
            (0.0, (1.0, 0.0, 0.0, 1.0)),  # Red
            (1.0, (0.0, 1.0, 0.0, 1.0)),  # Green
        ]
        cmap = build_cmap("test", nodes)

        # At 0.0 should be red
        r, g, b, a = cmap(0.0)
        assert abs(r - 1.0) < 0.01
        assert abs(g - 0.0) < 0.01
        assert abs(b - 0.0) < 0.01

        # At 1.0 should be green
        r, g, b, a = cmap(1.0)
        assert abs(r - 0.0) < 0.01
        assert abs(g - 1.0) < 0.01
        assert abs(b - 0.0) < 0.01

        # At 0.5 should be yellow (mix)
        r, g, b, a = cmap(0.5)
        assert r > 0.4 and r < 0.6
        assert g > 0.4 and g < 0.6

    def test_handles_alpha_channel(self):
        """Should handle alpha channel in nodes."""
        nodes = [
            (0.0, (1.0, 0.0, 0.0, 0.5)),
            (1.0, (0.0, 1.0, 0.0, 1.0)),
        ]
        cmap = build_cmap("test", nodes)

        r, g, b, a = cmap(0.0)
        assert abs(a - 0.5) < 0.01

        r, g, b, a = cmap(1.0)
        assert abs(a - 1.0) < 0.01


class TestCreateColormaps:
    """Tests for create_colormaps function."""

    def test_returns_four_colormaps(self):
        """Should return dict with four colormaps."""
        colormaps = create_colormaps()

        assert "cmap_count" in colormaps
        assert "cmap_speed_rgb" in colormaps
        assert "cmap_hr_rgb" in colormaps
        assert "cmap_elev_rgb" in colormaps
        assert len(colormaps) == 4

    def test_colormaps_are_callable(self):
        """All colormaps should be callable."""
        colormaps = create_colormaps()

        for _, cmap in colormaps.items():
            assert callable(cmap)
            # Test calling with a value
            r, g, b, a = cmap(0.5)
            assert 0 <= r <= 1
            assert 0 <= g <= 1
            assert 0 <= b <= 1
            assert 0 <= a <= 1


class TestToUri:
    """Tests for _to_uri function."""

    def test_converts_rgba_array_to_base64_uri(self):
        """Should convert RGBA array to base64 data URI."""
        # Create a small test image
        arr = np.zeros((10, 10, 4), dtype=np.uint8)
        arr[:, :, 0] = 255  # Red
        arr[:, :, 3] = 255  # Full opacity

        uri = _to_uri(arr)

        assert uri.startswith("data:image/png;base64,")
        # Verify it's valid base64
        b64_data = uri.split(",")[1]
        decoded = base64.b64decode(b64_data)
        assert len(decoded) > 0

        # Verify it's a valid PNG
        img = Image.open(BytesIO(decoded))
        assert img.format == "PNG"
        assert img.size == (10, 10)

    def test_handles_different_array_sizes(self):
        """Should handle arrays of different sizes."""
        for h, w in [(1, 1), (10, 20), (100, 50)]:
            arr = np.zeros((h, w, 4), dtype=np.uint8)
            arr[:, :, 3] = 255
            uri = _to_uri(arr)
            assert uri.startswith("data:image/png;base64,")


class TestCountUri:
    """Tests for _count_uri function."""

    def test_generates_uri_from_norm_and_cmap(self):
        """Should generate URI from normalized array and colormap."""
        norm = np.zeros((10, 10), dtype=np.float32)
        norm[5, 5] = 1.0

        colormaps = create_colormaps()
        cmap = colormaps["cmap_count"]

        uri = _count_uri(norm, cmap)

        assert uri.startswith("data:image/png;base64,")


class TestRgbaUri:
    """Tests for _rgba_uri function."""

    def test_combines_rgb_norm_with_alpha(self):
        """Should combine RGB normalized values with alpha mask."""
        rgb_norm = np.zeros((10, 10), dtype=np.float32)
        rgb_norm[5, 5] = 1.0

        alpha_norm = np.zeros((10, 10), dtype=np.float32)
        alpha_norm[5, 5] = 0.5

        colormaps = create_colormaps()
        cmap = colormaps["cmap_speed_rgb"]

        uri = _rgba_uri(rgb_norm, alpha_norm, cmap)

        assert uri.startswith("data:image/png;base64,")

    def test_alpha_zero_produces_transparent(self):
        """Pixels with alpha=0 should be transparent."""
        rgb_norm = np.ones((10, 10), dtype=np.float32)
        alpha_norm = np.zeros((10, 10), dtype=np.float32)

        colormaps = create_colormaps()
        cmap = colormaps["cmap_speed_rgb"]

        uri = _rgba_uri(rgb_norm, alpha_norm, cmap)

        # Decode and check alpha channel
        b64_data = uri.split(",")[1]
        decoded = base64.b64decode(b64_data)
        img = Image.open(BytesIO(decoded))
        arr = np.array(img)
        assert np.all(arr[:, :, 3] == 0)  # All transparent


class TestWhiteUri:
    """Tests for _white_uri function."""

    def test_creates_white_image_with_alpha(self):
        """Should create white image with given alpha mask."""
        alpha_norm = np.zeros((10, 10), dtype=np.float32)
        alpha_norm[5, 5] = 1.0

        uri = _white_uri(alpha_norm)

        assert uri.startswith("data:image/png;base64,")

        # Decode and verify
        b64_data = uri.split(",")[1]
        decoded = base64.b64decode(b64_data)
        img = Image.open(BytesIO(decoded))
        arr = np.array(img)

        # RGB should be white (255)
        assert np.all(arr[:, :, :3] == 255)
        # Alpha should match input
        assert arr[5, 5, 3] == 255
        assert arr[0, 0, 3] == 0


class TestGenerateLayerUris:
    """Tests for generate_layer_uris function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalized = {
            "count_norm": np.zeros((10, 10), dtype=np.float32),
            "count_log_norm": np.zeros((10, 10), dtype=np.float32),
            "speed_norm": np.zeros((10, 10), dtype=np.float32),
            "hr_norm": np.zeros((10, 10), dtype=np.float32),
            "grad_norm": np.zeros((10, 10), dtype=np.float32),
            "elev_norm": np.zeros((10, 10), dtype=np.float32),
            "alpha_speed": np.zeros((10, 10), dtype=np.float32),
            "alpha_hr": np.zeros((10, 10), dtype=np.float32),
            "alpha_grad": np.zeros((10, 10), dtype=np.float32),
            "alpha_elev": np.zeros((10, 10), dtype=np.float32),
        }
        self.colormaps = create_colormaps()

    def test_returns_six_layers(self):
        """Should return list of 6 layer tuples."""
        layers = generate_layer_uris(self.normalized, self.colormaps)

        assert len(layers) == 6
        for layer in layers:
            assert len(layer) == 3  # (name, uri, visible)
            name, uri, visible = layer
            assert isinstance(name, str)
            assert uri.startswith("data:image/png;base64,")
            assert isinstance(visible, bool)

    def test_first_layer_is_visible(self):
        """First layer (Frequency linear) should be visible by default."""
        layers = generate_layer_uris(self.normalized, self.colormaps)

        assert layers[0][2] is True  # visible
        for layer in layers[1:]:
            assert layer[2] is False  # not visible

    def test_layer_names_match_expected(self):
        """Layer names should match expected values."""
        layers = generate_layer_uris(self.normalized, self.colormaps)

        expected_names = [
            "Frequency (linear)",
            "Frequency (log)",
            "Pace (average)",
            "Heart rate (average)",
            "Gradient (absolute)",
            "Gradient (change)",
        ]

        for i, expected in enumerate(expected_names):
            assert layers[i][0] == expected
