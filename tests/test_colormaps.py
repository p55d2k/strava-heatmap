"""
Unit tests for src/colormaps.py - colormap creation and layer URI generation.
"""

import base64
from io import BytesIO

import numpy as np
from PIL import Image

import src.colormaps as src_colormaps
from src.colormaps import (
    _count_uri,
    _rgba_uri,
    _to_uri,
    _white_uri,
    build_cmap,
    create_colormaps,
    generate_layer_uris,
)
from src.map_builder.constants import (
    DENSITY_LAYER_NAMES,
    DENSITY_MODE_LAYERS,
    METRIC_LAYER_NAMES,
    RASTER_MODES,
    TIME_SPENT_LAYER,
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

        # Give each raster mode its own distinct grid so the tests can verify
        # every mode layer is baked from ITS OWN grid (not one shared image).
        def grid(v):
            g = np.zeros((10, 10), dtype=np.float32)
            g[5, 5] = v
            return g

        self.grids = {
            "decay": grid(0.25),
            "raw-count": grid(0.5),
            "binary-per-activity": grid(0.75),
        }
        self.normalized = {
            "count_norm": self.grids["decay"],
            "count_log_norm": self.grids["decay"],
            "count_raw_norm": self.grids["raw-count"],
            "count_raw_log_norm": self.grids["raw-count"],
            "unique_norm": self.grids["binary-per-activity"],
            "unique_log_norm": self.grids["binary-per-activity"],
            "unique_pct_norm": np.zeros((10, 10), dtype=np.float32),
            "count_log_norms": self.grids,
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

    def test_returns_eight_layers(self):
        """Should return 8 layer tuples (3 density modes + Coverage + 4 metrics)."""
        layers = generate_layer_uris(self.normalized, self.colormaps)

        assert len(layers) == 8
        for layer in layers:
            assert len(layer) == 3  # (name, uri, visible)
            name, uri, visible = layer
            assert isinstance(name, str)
            assert uri.startswith("data:image/png;base64,")
            assert isinstance(visible, bool)

    def test_time_spent_default_visible(self):
        """Time Spent (default raster mode's density layer) is visible; the rest hidden."""
        layers = generate_layer_uris(self.normalized, self.colormaps)

        expected_names = DENSITY_LAYER_NAMES + METRIC_LAYER_NAMES
        for i, layer in enumerate(layers):
            # Only "GPS Density (Time Spent)" is on by default.
            assert layer[2] is (expected_names[i] == TIME_SPENT_LAYER), layer[0]

    def test_layer_names_match_expected(self):
        """Layer names should match expected values (3 density + Coverage + 4 metrics)."""
        layers = generate_layer_uris(self.normalized, self.colormaps)

        expected_names = DENSITY_LAYER_NAMES + METRIC_LAYER_NAMES
        assert [layer[0] for layer in layers] == expected_names

    def test_each_mode_layer_baked_from_its_own_grid(self):
        """Regression: each raster mode's GPS Density layer must be a genuinely
        distinct image baked from that mode's normalized grid — switching layers
        in the panel must change the map, not show the same pixels again."""
        captured = []

        def _spy_count_uri(norm, cmap):
            captured.append(norm)
            return "data:image/png;base64,stub"

        orig = src_colormaps._count_uri
        src_colormaps._count_uri = _spy_count_uri
        try:
            layers = generate_layer_uris(self.normalized, self.colormaps)
        finally:
            src_colormaps._count_uri = orig

        by_name = {layer[0]: layer for layer in layers}
        for mode in RASTER_MODES:
            layer_name = DENSITY_MODE_LAYERS[mode]
            assert layer_name in by_name, f"missing density layer for mode {mode}"
        # The first three _count_uri calls are the three mode layers, in
        # RASTER_MODES order, each fed by its own grid object.
        assert captured[0] is self.grids["decay"]
        assert captured[1] is self.grids["raw-count"]
        assert captured[2] is self.grids["binary-per-activity"]

    def test_coverage_layer_selects_normalization_grid(self, monkeypatch):
        """The coverage layer URI should be produced from the grid selected by
        ``coverage_normalization`` (``"pct"`` → ``unique_pct_norm``,
        ``"max"`` → ``unique_norm``)."""
        from src.map_builder.constants import COVERAGE_LAYER

        captured = []

        def _spy_count_uri(norm, cmap):
            captured.append(norm)
            return "data:image/png;base64,stub"

        monkeypatch.setattr("src.colormaps._count_uri", _spy_count_uri)

        pct_sentinel = object()
        max_sentinel = object()
        self.normalized["unique_norm"] = max_sentinel
        self.normalized["unique_pct_norm"] = pct_sentinel

        # coverage_normalization="pct" → coverage layer uses pct grid
        layers = generate_layer_uris(self.normalized, self.colormaps, coverage_normalization="pct")
        # Calls 0-2 are the three raster-mode density layers; call 3 is Coverage.
        assert len(captured) >= 4
        assert captured[3] is pct_sentinel
        coverage_layer = [layer for layer in layers if layer[0] == COVERAGE_LAYER][0]
        assert coverage_layer[0] == COVERAGE_LAYER

        captured.clear()
        # coverage_normalization="max" → coverage layer uses max grid
        layers = generate_layer_uris(self.normalized, self.colormaps, coverage_normalization="max")
        assert captured[3] is max_sentinel
