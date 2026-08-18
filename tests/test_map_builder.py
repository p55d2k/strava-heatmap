"""
Unit tests for src/map_builder.py - map building and HTML output functions.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.map_builder import (
    EXCLUSIVE_JS,
    LAYER_CONTROL_CSS,
    build_legend_html,
    build_map,
    cmap_to_css,
    legend_row,
    pace_str,
)


class TestCmapToCss:
    """Tests for cmap_to_css function."""

    def test_converts_colormap_to_css_gradient(self):
        """Should convert colormap to CSS linear-gradient string."""
        # Create a simple mock colormap
        cmap = MagicMock()
        cmap.side_effect = lambda t: (t, 1 - t, 0.5, 1.0)  # Red to blue gradient

        css = cmap_to_css(cmap, n=5)

        assert css.startswith("linear-gradient(to right,")
        assert "rgba(" in css
        assert css.endswith(")")

    def test_generates_correct_number_of_stops(self):
        """Should generate correct number of color stops."""
        cmap = MagicMock()
        cmap.side_effect = lambda t: (1.0, 0.0, 0.0, 1.0)

        css = cmap_to_css(cmap, n=10)

        # Should have 10 rgba() calls
        assert css.count("rgba(") == 10

    def test_handles_different_n_values(self):
        """Should work with different n values."""
        cmap = MagicMock()
        cmap.side_effect = lambda t: (1.0, 0.0, 0.0, 1.0)

        for n in [2, 5, 10, 20]:
            css = cmap_to_css(cmap, n=n)
            assert css.count("rgba(") == n


class TestPaceStr:
    """Tests for pace_str function."""

    def test_converts_ms_to_pace_string(self):
        """Should convert m/s to min:sec/km format."""
        # 5 m/s = 3:20/km
        assert pace_str(5.0) == "3:20/km"

        # 4 m/s = 4:10/km
        assert pace_str(4.0) == "4:10/km"

        # 3 m/s = 5:33/km
        assert pace_str(3.0) == "5:33/km"

    def test_handles_fast_paces(self):
        """Should handle fast paces (high m/s)."""
        # 6 m/s = 2:46/km
        assert pace_str(6.0) == "2:46/km"

    def test_handles_slow_paces(self):
        """Should handle slow paces (low m/s)."""
        # 2 m/s = 8:20/km
        assert pace_str(2.0) == "8:20/km"


class TestLegendRow:
    """Tests for legend_row function."""

    def test_generates_html_with_correct_structure(self):
        """Should generate HTML with correct structure."""
        html = legend_row(
            "test-id",
            "Test Title",
            "linear-gradient(to right, red, blue)",
            "Low",
            "High",
            visible=True,
        )

        assert 'id="test-id"' in html
        assert "Test Title" in html
        assert "linear-gradient(to right, red, blue)" in html
        assert "Low" in html
        assert "High" in html
        assert "display:block" in html

    def test_hidden_when_not_visible(self):
        """Should have display:none when not visible."""
        html = legend_row("test-id", "Test", "gradient", "Lo", "Hi", visible=False)
        assert "display:none" in html

    def test_visible_when_true(self):
        """Should have display:block when visible."""
        html = legend_row("test-id", "Test", "gradient", "Lo", "Hi", visible=True)
        assert "display:block" in html


class TestBuildLegendHtml:
    """Tests for build_legend_html function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalized = {
            "s_lo": 3.0,
            "s_hi": 6.0,
            "hr_lo": 120,
            "hr_hi": 180,
            "g_lo": 0.02,
            "g_hi": 0.10,
            "max_passes": 50,
        }
        self.colormaps = {
            "cmap_count": MagicMock(),
            "cmap_speed_rgb": MagicMock(),
            "cmap_hr_rgb": MagicMock(),
            "cmap_elev_rgb": MagicMock(),
        }
        # Mock cmap_to_css to return predictable values
        for cmap in self.colormaps.values():
            cmap.side_effect = lambda t: (t, 1 - t, 0.5, 1.0)

    def test_generates_complete_legend_html(self):
        """Should generate complete legend HTML with all sections."""
        html = build_legend_html(self.normalized, self.colormaps, self.normalized["max_passes"])

        # Check container
        assert 'id="heatmap-legend"' in html
        assert "position:fixed" in html
        assert "z-index:9999" in html

        # Check all legend rows present
        assert "Frequency (linear)" in html
        assert "Frequency (log)" in html
        assert "Pace (average)" in html
        assert "Heart rate (average)" in html
        assert "Gradient (absolute)" in html
        assert "Gradient (change)" in html

        # Check values are included
        assert "1 pass" in html
        assert "50 passes" in html
        assert "2:46/km" in html  # pace_str(6.0)
        assert "5:33/km" in html  # pace_str(3.0)
        assert "120 bpm" in html
        assert "180 bpm" in html
        assert "2.0%" in html  # g_lo * 100
        assert "10.0%" in html  # g_hi * 100
        assert "descending" in html
        assert "ascending" in html

    def test_first_row_visible_others_hidden(self):
        """First legend row should be visible, others hidden."""
        html = build_legend_html(self.normalized, self.colormaps, self.normalized["max_passes"])

        # First row (frequency linear) should be visible
        assert 'id="legend-frequency"' in html
        assert "display:block" in html

        # Other rows should be hidden
        assert 'id="legend-frequency-log"' in html
        assert "display:none" in html


class TestBuildMap:
    """Tests for build_map function."""

    def setup_method(self):
        """Set up test fixtures."""
        self.tracks = [
            ("Track 1", [[45.0, -122.0], [45.001, -122.001]]),
            ("Track 2", [[45.002, -122.002], [45.003, -122.003]]),
        ]
        self.layers = [
            ("Layer 1", "data:image/png;base64,test1", True),
            ("Layer 2", "data:image/png;base64,test2", False),
        ]
        self.bounds = [[44.9, -122.1], [45.1, -121.9]]
        self.centre = [45.0, -122.0]
        self.legend_html = "<div>Legend</div>"
        self.output_path = Path("/tmp/test_map.html")
        self.map_opacity = 0.7

    @patch("src.map_builder.folium.Map")
    @patch("src.map_builder.folium.TileLayer")
    @patch("src.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.folium.PolyLine")
    @patch("src.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.folium.LayerControl")
    def test_creates_map_with_correct_structure(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """Should create map with all expected components."""
        # Set up mocks
        mock_map_instance = MagicMock()
        mock_map.return_value = mock_map_instance

        mock_tile_layer_instance = MagicMock()
        mock_tile_layer.return_value = mock_tile_layer_instance

        mock_track_group = MagicMock()
        mock_feature_group.return_value = mock_track_group

        mock_polyline_instance = MagicMock()
        mock_polyline.return_value = mock_polyline_instance

        mock_layer_group = MagicMock()
        mock_feature_group.return_value = mock_layer_group

        mock_image_overlay_instance = MagicMock()
        mock_image_overlay.return_value = mock_image_overlay_instance

        mock_layer_control_instance = MagicMock()
        mock_layer_control.return_value = mock_layer_control_instance

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
        )

        # Verify map creation
        mock_map.assert_called_once()
        call_kwargs = mock_map.call_args[1]
        assert call_kwargs["location"] == self.centre
        assert call_kwargs["zoom_start"] == 14
        assert call_kwargs["tiles"] is None
        assert call_kwargs["control_scale"] is True

        # Verify basemap
        mock_tile_layer.assert_called_once()
        tile_kwargs = mock_tile_layer.call_args[1]
        assert tile_kwargs["name"] == "Basemap"
        assert tile_kwargs["control"] is False
        assert tile_kwargs["show"] is True

        # Verify track group
        assert mock_feature_group.call_count >= 2  # track group + layer groups
        track_group_call = mock_feature_group.call_args_list[0]
        assert track_group_call[1]["name"] == "Raw GPS tracks"
        assert track_group_call[1]["show"] is False

        # Verify polylines for tracks
        assert mock_polyline.call_count == 2  # Two tracks

        # Verify image overlays for layers
        assert mock_image_overlay.call_count == 2  # Two layers

        # Verify layer control
        mock_layer_control.assert_called_once()
        lc_kwargs = mock_layer_control.call_args[1]
        assert lc_kwargs["collapsed"] is False

        # Verify HTML elements added
        assert mock_map_instance.get_root().html.add_child.call_count >= 3  # CSS, legend, JS

        # Verify save
        mock_map_instance.save.assert_called_once_with(self.output_path)

    @patch("src.map_builder.folium.Map")
    @patch("src.map_builder.folium.TileLayer")
    @patch("src.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.folium.PolyLine")
    @patch("src.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.folium.LayerControl")
    def test_layer_visibility_matches_input(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """Layer visibility should match input."""
        mock_map_instance = MagicMock()
        mock_map.return_value = mock_map_instance
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
        )

        # Check FeatureGroup calls for layers - should have show=visible
        fg_calls = mock_feature_group.call_args_list
        layer_fg_calls = fg_calls[1:]  # Skip track group
        for i, call in enumerate(layer_fg_calls):
            expected_visible = self.layers[i][2]
            assert call[1]["show"] == expected_visible

    @patch("src.map_builder.folium.Map")
    @patch("src.map_builder.folium.TileLayer")
    @patch("src.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.folium.PolyLine")
    @patch("src.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.folium.LayerControl")
    def test_image_overlay_opacity(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """ImageOverlay should use provided opacity."""
        mock_map_instance = MagicMock()
        mock_map.return_value = mock_map_instance
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
        )

        # Check ImageOverlay opacity
        io_calls = mock_image_overlay.call_args_list
        for call in io_calls:
            assert call[1]["opacity"] == self.map_opacity


class TestConstants:
    """Tests for module constants."""

    def test_layer_control_css_not_empty(self):
        """LAYER_CONTROL_CSS should not be empty."""
        assert len(LAYER_CONTROL_CSS) > 0
        assert "leaflet-control-layers" in LAYER_CONTROL_CSS

    def test_exclusive_js_not_empty(self):
        """EXCLUSIVE_JS should not be empty."""
        assert len(EXCLUSIVE_JS) > 0
        assert "exclusiveNames" in EXCLUSIVE_JS
        assert "overlayadd" in EXCLUSIVE_JS
