"""
Unit tests for src/map_builder.py - map building and HTML output functions.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import folium
import pytest

from src.map_builder import (
    CARTO_STYLES,
    DEFAULT_CARTO_STYLE,
    DENSITY_MODE_LAYERS,
    INDEPENDENT_LAYER_NAMES,
    METRIC_LAYER_NAMES,
    RASTER_MODES,
    ControlPanel,
    ExclusiveLayerControl,
    LegendBuilder,
    LegendContext,
    LegendRow,
    ScalableHomeMarker,
    build_control_panel_html,
    build_layer_group_config,
    build_legend_html,
    build_map,
    build_tile_url,
    carto_basemap_choices,
    cmap_to_css,
    control_panel_script,
    controls_css,
    get_carto_api_key,
    home_marker_radius,
    legend_row,
    pace_str,
)
from src.map_builder.constants import (
    DEFAULT_RASTER_MODE,
    DENSITY_LAYER_NAMES,
    LEGEND_IDS,
    TRACK_OPACITY,
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
            "coverage_normalization": "pct",
            "n_activities": 100,
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

        # Check container uses shared CSS class
        assert 'id="heatmap-legend"' in html
        assert 'class="hcp-legend"' in html

        # Check all legend rows present
        assert "GPS Density" in html
        assert "Coverage %" in html
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

    def test_density_rows_hidden_by_default(self):
        """GPS Density (Time Spent) is visible on first paint (its layer is on
        by default); Coverage is hidden until toggled on. The JS layer control
        re-syncs all rows on DOMContentLoaded."""
        html = build_legend_html(self.normalized, self.colormaps, self.normalized["max_passes"])

        # Time Spent layer is on by default → legend row must be visible.
        assert 'id="legend-density-decay" class="hcp-legend-row" style="display:block"' in html, (
            "legend-density-decay should be visible on first load"
        )

        # Coverage and metrics are hidden until toggled.
        for hidden_id in (
            "legend-coverage",
            "legend-pace-avg",
        ):
            assert f'id="{hidden_id}" class="hcp-legend-row" style="display:none"' in html, (
                f"legend row {hidden_id} should be hidden on first load"
            )
        # Only the default-on layer (Time Spent) has a visible row on first paint.
        assert html.count('style="display:block"') == 1


class TestLegendBuilder:
    """Tests for configurable legend rows and dynamic visibility wiring."""

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
            "coverage_normalization": "pct",
            "n_activities": 100,
        }
        self.colormaps = {
            key: MagicMock(side_effect=lambda t: (t, 1 - t, 0.5, 1.0))
            for key in ["cmap_count", "cmap_speed_rgb", "cmap_hr_rgb", "cmap_elev_rgb"]
        }

    def test_default_rows_use_legend_ids_and_exclusive_names(self):
        """Default builder should expose one layer->legend id entry per raster-mode
        density layer plus Coverage and the metrics."""
        builder = LegendBuilder()
        assert builder.exclusive_layer_names == [
            "GPS Density (Time Spent)",
            "GPS Density (Raw Passes)",
            "GPS Density (Unique Visits)",
            "Coverage (Places Visited)",
            "Pace (average)",
            "Heart rate (average)",
            "Gradient (absolute)",
            "Gradient (change)",
        ]
        assert builder.legend_ids == {
            "GPS Density (Time Spent)": "legend-density-decay",
            "GPS Density (Raw Passes)": "legend-density-raw-count",
            "GPS Density (Unique Visits)": "legend-density-binary-per-activity",
            "Coverage (Places Visited)": "legend-coverage",
            "Pace (average)": "legend-pace-avg",
            "Heart rate (average)": "legend-heart-rate-avg",
            "Gradient (absolute)": "legend-gradient",
            "Gradient (change)": "legend-elev-change",
        }

    def test_default_rows_renders_same_html(self):
        """Default-builder output should include both density concepts and metrics."""
        builder = LegendBuilder()
        html = builder.build(self.normalized, self.colormaps, self.normalized["max_passes"])
        assert "GPS Density" in html
        assert "Coverage %" in html
        assert "Heart rate (average)" in html
        assert "120 bpm" in html
        assert "180 bpm" in html
        assert "2.0%" in html
        assert "10.0%" in html
        # The Time Spent layer shows the max-passes figure on a log scale.
        assert "50 passes" in html

    def test_custom_rows_produce_only_configured_rows(self):
        """Custom rows should render exactly what is configured."""
        rows = [
            LegendRow(
                row_id="custom-a",
                title="Custom A",
                gradient="linear-gradient(to right, red, blue)",
                label_lo=lambda ctx: f"lo-{ctx.max_passes}",
                label_hi="hi",
                layer_name="Custom A layer",
            ),
            LegendRow(
                row_id="custom-b",
                title="Custom B",
                gradient="linear-gradient(to right, green, yellow)",
                label_lo="x",
                label_hi="y",
                visible=True,
            ),
        ]
        builder = LegendBuilder(rows=rows)
        html = builder.build(self.normalized, self.colormaps, self.normalized["max_passes"])

        assert "Custom A" in html
        assert "Custom B" in html
        assert "lo-50" in html
        assert "linear-gradient(to right, red, blue)" in html
        # Only configured rows are included
        assert "GPS Density" not in html
        assert "Pace (average)" not in html

        # Dynamic visibility config derives from the configured rows.
        # custom-b has no layer_name so it is excluded from exclusive behavior.
        assert builder.exclusive_layer_names == ["Custom A layer"]
        assert builder.legend_ids == {"Custom A layer": "custom-a"}

    def test_callable_fields_resolved_with_context(self):
        """Callable gradient/labels should be resolved using the build context."""
        rows = [
            LegendRow(
                row_id="ctx-row",
                title="Ctx",
                gradient=lambda ctx: f"grad-{ctx.colormaps['cmap_count'].t}",
                label_lo=lambda ctx: f"{ctx.normalized['s_lo']:.1f}",
                label_hi=lambda ctx: f"passes={ctx.max_passes}",
            )
        ]
        html = LegendBuilder(rows=rows).build(self.normalized, self.colormaps, 7)
        assert "grad-" in html
        assert "3.0" in html
        assert "passes=7" in html


class TestHomeMarkerRadius:
    """Tests for the home_marker_radius helper."""

    def test_returns_base_radius_at_base_zoom_14(self):
        """At the default zoom 14 the radius should be 6 px."""
        assert home_marker_radius(14) == 6

    def test_grows_with_zoom(self):
        """Radius should increase as zoom increases."""
        assert home_marker_radius(16) > home_marker_radius(14)

    def test_shrinks_at_low_zoom(self):
        """Radius should not grow as zoom decreases below base."""
        assert home_marker_radius(10) <= home_marker_radius(14)

    def test_minimum_clamp(self):
        """At very low zoom the radius should not go below the minimum."""
        r = home_marker_radius(5)
        assert r >= 4

    def test_maximum_clamp(self):
        """At very high zoom the radius should not exceed the maximum."""
        r = home_marker_radius(25)
        assert r <= 18


class TestScalableHomeMarker:
    """Tests for the ScalableHomeMarker MacroElement."""

    def test_renders_home_marker_option_for_panel_lookup(self):
        """The rendered script must tag the marker with options.homeMarker —
        assets/panel.js locates the marker by that option to power the toggle."""
        m = folium.Map(location=[45.0, -122.0], zoom_start=14, tiles=None)
        marker = ScalableHomeMarker(location=[45.0, -122.0])
        marker.add_to(m)

        script = marker._template.module.script(marker, {})

        assert "homeMarker: true" in script
        assert 'bindTooltip("Home")' in script
        # The marker is positioned at the home coordinates.
        assert "45.0" in script


@pytest.mark.usefixtures("carto_api_key")
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
        self.home = [45.01, -122.01]
        self.legend_html = "<div>Legend</div>"
        self.output_path = Path("/tmp/test_map.html")
        self.map_opacity = 0.7

    @patch("src.map_builder.map_builder.ScalableHomeMarker")
    def test_home_marker_added_when_home_provided(self, mock_home_marker):
        """Should add a zoom-scalable marker at the home location when home is provided."""
        mock_map = MagicMock()
        with (
            patch("src.map_builder.map_builder.folium.Map", return_value=mock_map),
            patch("src.map_builder.map_builder.folium.TileLayer", return_value=MagicMock()),
            patch("src.map_builder.map_builder.folium.FeatureGroup", return_value=MagicMock()),
            patch("src.map_builder.map_builder.folium.PolyLine", return_value=MagicMock()),
            patch(
                "src.map_builder.map_builder.folium.raster_layers.ImageOverlay",
                return_value=MagicMock(),
            ),
            patch("src.map_builder.map_builder.folium.LayerControl", return_value=MagicMock()),
        ):
            build_map(
                self.tracks,
                self.layers,
                self.bounds,
                self.centre,
                self.legend_html,
                self.output_path,
                self.map_opacity,
                home=self.home,
            )

        mock_home_marker.assert_called_once()
        call = mock_home_marker.call_args[1]
        assert call["location"] == self.home
        # The marker should be added to the map instance once.
        mock_home_marker.return_value.add_to.assert_called_once()

    @patch("src.map_builder.map_builder.ScalableHomeMarker")
    def test_no_home_marker_when_home_is_none(self, mock_home_marker):
        """Should NOT add a marker when home is omitted (None)."""
        mock_map = MagicMock()
        with (
            patch("src.map_builder.map_builder.folium.Map", return_value=mock_map),
            patch("src.map_builder.map_builder.folium.TileLayer", return_value=MagicMock()),
            patch("src.map_builder.map_builder.folium.FeatureGroup", return_value=MagicMock()),
            patch("src.map_builder.map_builder.folium.PolyLine", return_value=MagicMock()),
            patch(
                "src.map_builder.map_builder.folium.raster_layers.ImageOverlay",
                return_value=MagicMock(),
            ),
            patch("src.map_builder.map_builder.folium.LayerControl", return_value=MagicMock()),
        ):
            build_map(
                self.tracks,
                self.layers,
                self.bounds,
                self.centre,
                self.legend_html,
                self.output_path,
                self.map_opacity,
            )

        mock_home_marker.assert_not_called()

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
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
        # Every track polyline should be seeded with the shared TRACK_OPACITY so
        # it stays consistent with the control-panel slider's initial value.
        for call in mock_polyline.call_args_list:
            assert call[1]["opacity"] == TRACK_OPACITY

        # Verify image overlays for layers
        assert mock_image_overlay.call_count == 2  # Two layers

        # Verify layer control is hidden (collapsed=True) — kept only for
        # Folium's overlay registry used by the panel + ExclusiveLayerControl.
        mock_layer_control.assert_called_once()
        lc_kwargs = mock_layer_control.call_args[1]
        assert lc_kwargs["collapsed"] is True

        # Verify HTML elements added (CSS, legend)
        # ExclusiveLayerControl is added via add_to(), not add_child()
        assert mock_map_instance.get_root().html.add_child.call_count >= 2  # CSS, legend

        # Verify save
        mock_map_instance.save.assert_called_once_with(self.output_path)

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    def test_map_uses_home_for_initial_location(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """Map should centre on home (not bounding-box centre) when provided."""
        mock_map.return_value = MagicMock()
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
            home=self.home,
        )

        call_kwargs = mock_map.call_args[1]
        assert call_kwargs["location"] == self.home
        assert call_kwargs["location"] != self.centre

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    def test_map_falls_back_to_centre_without_home(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """Map should fall back to the bounding-box centre when home is omitted."""
        mock_map.return_value = MagicMock()
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

        call_kwargs = mock_map.call_args[1]
        assert call_kwargs["location"] == self.centre

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
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

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
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

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    def test_basemap_uses_carto_api_key_tile_url(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """Basemap TileLayer should use the API-keyed CARTO tile URL."""
        mock_map.return_value = MagicMock()
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

        tile_kwargs = mock_tile_layer.call_args[1]
        url = tile_kwargs["tiles"]
        assert url.startswith("https://basemaps.cartocdn.com/rastertiles/dark_all/")
        assert "?key=default_public_testkey" in url
        assert "{z}/{x}/{y}" in url
        assert tile_kwargs["max_zoom"] == 20
        assert "carto.com/attributions" in tile_kwargs["attr"]

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    def test_basemap_uses_configured_carto_style(
        self,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """Basemap TileLayer should use the carto_style passed to build_map."""
        mock_map.return_value = MagicMock()
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
            carto_style="voyager",
        )

        tile_kwargs = mock_tile_layer.call_args[1]
        url = tile_kwargs["tiles"]
        assert url.startswith("https://basemaps.cartocdn.com/rastertiles/voyager/")
        assert "?key=default_public_testkey" in url

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    @patch("src.map_builder.map_builder.ExclusiveLayerControl")
    def test_forwards_dynamic_visibility_config(
        self,
        mock_exclusive_control,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """ExclusiveLayerControl should receive the legend dynamic-visibility config."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_exclusive_control.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
            exclusive_layer_names=["Alpha"],
            legend_ids={"Alpha": "legend-alpha"},
        )

        mock_exclusive_control.assert_called_once()
        kwargs = mock_exclusive_control.call_args[1]
        assert kwargs["exclusive_names"] == ["Alpha"]
        assert kwargs["legend_ids"] == {"Alpha": "legend-alpha"}


class TestControlPanel:
    """Tests for the in-HTML control panel macro."""

    def test_default_instantiates_with_dark_style(self):
        """ControlPanel should default to dark_all."""
        panel = ControlPanel()
        assert panel is not None
        assert panel._name == "ControlPanel"
        assert f'"activeBasemap": "{DEFAULT_CARTO_STYLE}"' in panel.config_json

    def test_home_forwards_to_config(self):
        """ControlPanel should expose ``home`` for the Reset button."""
        panel = ControlPanel(centre=[1.0, 2.0], home=[3.0, 4.0])
        cfg = json.loads(panel.config_json)
        assert cfg["home"] == [3.0, 4.0]
        assert cfg["centre"] == [1.0, 2.0]
        # A home position implies a home marker, so the toggle must be offered.
        assert cfg["hasHomeMarker"] is True

    def test_home_defaults_to_centre(self):
        """ControlPanel should fall back to centre when home is omitted."""
        panel = ControlPanel(centre=[1.0, 2.0])
        cfg = json.loads(panel.config_json)
        assert cfg["home"] == [1.0, 2.0]
        # No home position => no home marker, so the toggle is suppressed.
        assert cfg["hasHomeMarker"] is False

    def test_has_home_marker_false_without_home(self):
        """ControlPanel should not advertise a home marker when home is absent."""
        panel = ControlPanel(centre=[1.0, 2.0])
        cfg = json.loads(panel.config_json)
        assert cfg["hasHomeMarker"] is False

    def test_html_contains_panel_markup(self):
        """build_control_panel_html should contain the key controls."""
        html = build_control_panel_html()
        assert "heatmap-control-panel" in html
        assert "hcp-basemap" in html
        assert "hcp-density-section" not in html
        assert "hcp-density-mode" not in html
        assert "hcp-layers" in html
        assert "hcp-opacity-toggle" in html
        assert "hcp-fit" in html
        assert "hcp-reset" in html
        assert "hcp-legend" in html
        # The home-marker toggle is in the static markup (checked by default; the
        # section is shown/hidden client-side based on the presence of a marker).
        assert "hcp-home-marker" in html
        # The sidebar always stays open; no collapse/re-open controls exist.
        assert "hcp-toggle" not in html
        assert "hcp-reopen" not in html
        assert "hcp-sidebar-collapsed" not in html
        assert "hcp-apply" not in html
        # The old single global opacity slider is gone; per-layer sliders are
        # rendered client-side by panel.js, so the static markup has no slider.
        assert "hcp-opacity-value" not in html
        assert 'id="hcp-opacity"' not in html
        # Layer-opacity controls are collapsed by default (hidden until toggled).
        assert "heatmap-control-panel hcp-opacity-collapsed" in html
        assert 'aria-expanded="false"' in html

    def test_html_has_no_inline_opacity(self):
        """build_control_panel_html no longer hard-codes an opacity percentage."""
        html = build_control_panel_html()
        assert "opacity_pct" not in html
        assert 'value="85"' not in html
        assert 'value="0"' not in html

    def test_script_contains_init_function(self):
        """control_panel_script should expose initHeatmapControlPanel."""
        script = control_panel_script()
        assert "initHeatmapControlPanel" in script
        assert "findOverlays" in script
        assert "basemaps.cartocdn.com" in script
        assert "redrawVisibleOverlays" in script
        assert '"zoomend"' in script
        # The home marker toggle logic must be inlined in the panel script.
        assert "findHomeMarker" in script
        assert "hcp-home-marker" in script

    def test_script_has_no_density_mode_dropdown_logic(self):
        """control_panel_script must not reference the removed dropdown machinery."""
        script = control_panel_script()
        assert "hcp-density-mode" not in script
        assert "applyDensityMode" not in script
        assert '"densitymodechange"' not in script
        assert "densityLegendIds" not in script

    def test_carto_basemap_choices_default(self):
        """carto_basemap_choices should return default styles with labels."""
        choices = carto_basemap_choices()
        assert [c["key"] for c in choices] == CARTO_STYLES
        assert all("label" in c for c in choices)

    def test_carto_basemap_choices_custom(self):
        """carto_basemap_choices should honour an explicit style list."""
        assert carto_basemap_choices(["voyager"]) == [{"key": "voyager", "label": "Voyager"}]

    def test_macro_template_has_html_and_script(self):
        """ControlPanel should define both html and script macros for folium."""
        module = ControlPanel._template.module.__dict__
        assert module.get("html") is not None
        assert module.get("script") is not None


class TestLegendBuilderDefaultRows:
    """Tests for the default legend-row definitions produced by LegendBuilder."""

    def _ctx(self):
        cmap = MagicMock()
        cmap.side_effect = lambda t: (t, 1 - t, 0.5, 1.0)  # Red to blue gradient
        return LegendContext(
            normalized={},
            colormaps={"cmap_count": cmap},
            max_passes=10,
            max_passes_by_strategy={"decay": 10, "binary-per-activity": 3, "raw-count": 7},
        )

    def _density_rows(self):
        rows = {r.row_id: r for r in LegendBuilder().default_rows()}
        return rows, self._ctx()

    def test_time_spent_row_visible_on_first_paint(self):
        """GPS Density (Time Spent) is on by default, so its legend row must be
        shown on first paint (before the JS re-syncs to the map state)."""
        rows, ctx = self._density_rows()
        row = rows["legend-density-decay"]
        assert row.visible is True
        assert row.label_hi(ctx) == "10 passes (log scale)"

    def test_one_density_row_per_raster_mode_layer(self):
        """The default legend renders one GPS Density row per raster-mode layer,
        each statically bound to its own overlay; only the default mode's row is
        visible on first paint."""
        builder = LegendBuilder()
        rows = {r.row_id: r for r in builder.default_rows()}
        expected_ids = {f"legend-density-{m}" for m in RASTER_MODES}
        assert expected_ids <= set(rows)
        visible_rows = [r for r in builder.default_rows() if r.visible]
        assert len(visible_rows) == 1
        assert visible_rows[0].row_id == f"legend-density-{DEFAULT_RASTER_MODE}"
        # Each row is bound to its own mode's layer and reports that mode's max.
        assert rows["legend-density-raw-count"].layer_name == DENSITY_MODE_LAYERS["raw-count"]
        assert rows["legend-density-raw-count"].label_hi(self._ctx()) == "7 passes (log scale)"
        assert rows["legend-density-binary-per-activity"].label_hi(self._ctx()) == (
            "3 passes (log scale)"
        )
        assert rows["legend-density-raw-count"].title == "GPS Density — Raw Passes"

    def test_density_row_ids_match_legend_ids_constant(self):
        """LEGEND_IDS must agree with the rows the legend actually renders, or the
        layer control would toggle rows that do not exist in the DOM."""
        builder = LegendBuilder()
        rendered = {r.row_id for r in builder.default_rows()}
        assert set(builder.legend_ids.values()) <= rendered
        assert set(LEGEND_IDS.values()) <= rendered

    def test_density_rows_report_per_mode_max_passes(self):
        """Each per-mode GPS Density row statically reports its own mode's
        max-pass count (each row belongs to its own layer; labels never change)."""
        rows, ctx = self._density_rows()
        expected_by_mode = {
            "decay": "10 passes (log scale)",
            "raw-count": "7 passes (log scale)",
            "binary-per-activity": "3 passes (log scale)",
        }
        for mode, expected in expected_by_mode.items():
            row = rows[f"legend-density-{mode}"]
            assert row.label_hi(ctx) == expected

    def test_coverage_row_hidden_and_uses_binary_per_activity_max(self):
        """Coverage counts each cell once per activity, so its header uses the
        binary-per-activity max-pass count, and stays hidden by default (the
        Coverage layer is off by default)."""
        rows, ctx = self._density_rows()
        row = rows["legend-coverage"]
        assert row.visible is False
        assert row.label_hi(ctx) == "3 passes"

    def test_coverage_pct_mode_labels(self):
        """When coverage_normalization="pct", the coverage row should show
        activity-count labels instead of max-pass labels."""
        from src.map_builder.legend import LegendBuilder, LegendContext

        cmap = MagicMock()
        cmap.side_effect = lambda t: (t, 1 - t, 0.5, 1.0)
        rows = {r.row_id: r for r in LegendBuilder().default_rows()}
        ctx = LegendContext(
            normalized={"coverage_normalization": "pct", "n_activities": 42},
            colormaps={"cmap_count": cmap},
            max_passes=10,
            max_passes_by_strategy={"decay": 10, "binary-per-activity": 3, "raw-count": 7},
        )
        row = rows["legend-coverage"]
        assert row.label_lo(ctx) == "1 activity"
        assert row.label_hi(ctx) == "42 activities (100%)"


class TestBuildMapControlPanel:
    """Tests for the control_panel flag passed to build_map."""

    def setup_method(self):
        """Set up test fixtures for the control panel build tests."""
        self.tracks = [
            ("Track 1", [[45.0, -122.0], [45.001, -122.001]]),
        ]
        self.layers = [
            ("Layer 1", "data:image/png;base64,test1", True),
        ]
        self.bounds = [[44.9, -122.1], [45.1, -121.9]]
        self.centre = [45.0, -122.0]
        self.legend_html = "<div>Legend</div>"
        self.output_path = Path("/tmp/test_map_control_panel.html")
        self.map_opacity = 0.7

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    @patch("src.map_builder.map_builder.ExclusiveLayerControl")
    @patch("src.map_builder.map_builder.ControlPanel")
    def test_adds_control_panel_by_default(
        self,
        mock_panel,
        mock_exclusive_control,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """build_map should add a ControlPanel by default."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_exclusive_control.return_value = MagicMock()
        mock_panel.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
        )

        mock_panel.assert_called_once()
        mock_panel.return_value.add_to.assert_called_once()

        # The panel should receive the layer-group config derived from the
        # supplied overlay layers and tracks.
        layer_groups = mock_panel.call_args[1]["layer_groups"]
        assert isinstance(layer_groups, list)
        assert any(g["label"] == "Raw GPS tracks" for g in layer_groups)
        # "Layer 1" / "Layer 2" are not in EXCLUSIVE_LAYER_NAMES, so they form a
        # plain checkbox group rather than the exclusive radio group.
        assert any(
            g["mode"] == "check"
            and any(lay["name"] in ("Layer 1", "Layer 2") for lay in g["layers"])
            for g in layer_groups
        )

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    @patch("src.map_builder.map_builder.ExclusiveLayerControl")
    @patch("src.map_builder.map_builder.ControlPanel")
    def test_forwards_home_to_control_panel(
        self,
        mock_panel,
        mock_exclusive_control,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """build_map should pass home through so the panel can offer the toggle."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_exclusive_control.return_value = MagicMock()
        mock_panel.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
            home=[45.01, -122.01],
        )

        mock_panel.assert_called_once()
        assert mock_panel.call_args[1]["home"] == [45.01, -122.01]

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    @patch("src.map_builder.map_builder.ExclusiveLayerControl")
    @patch("src.map_builder.map_builder.ControlPanel")
    def test_skips_control_panel_when_disabled(
        self,
        mock_panel,
        mock_exclusive_control,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """build_map should not add a ControlPanel when control_panel=False."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_exclusive_control.return_value = MagicMock()
        mock_panel.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
            control_panel=False,
        )

        mock_panel.assert_not_called()


class TestLayerGroupConfig:
    """Tests for build_layer_group_config (the panel layerGroups config)."""

    def setup_method(self):
        self.layers = [
            ("GPS Density (Time Spent)", "data:image/png;base64,1", True),
            ("GPS Density (Raw Passes)", "data:image/png;base64,1a", False),
            ("GPS Density (Unique Visits)", "data:image/png;base64,1b", False),
            ("Coverage (Places Visited)", "data:image/png;base64,1c", False),
            ("Pace (average)", "data:image/png;base64,2", False),
            ("Custom overlay", "data:image/png;base64,3", True),
        ]

    def test_includes_tracks_group_when_present(self):
        """Should add a Raw GPS tracks checkbox group when tracks exist."""
        groups = build_layer_group_config(self.layers, has_tracks=True)
        labels = [g["label"] for g in groups]
        assert "Raw GPS tracks" in labels
        tracks_group = next(g for g in groups if g["label"] == "Raw GPS tracks")
        assert tracks_group["mode"] == "check"
        assert tracks_group["layers"][0]["visible"] is False

    def test_density_layers_in_radio_group(self):
        """All density concept layers (one GPS Density layer per raster mode plus
        Coverage) form a mutually-exclusive radio group."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        heatmap = next(g for g in groups if g["label"] == "Heatmap")
        assert heatmap["mode"] == "radio"
        names = [lay["name"] for lay in heatmap["layers"]]
        assert names == [
            "GPS Density (Time Spent)",
            "GPS Density (Raw Passes)",
            "GPS Density (Unique Visits)",
            "Coverage (Places Visited)",
        ]
        # Only the default mode's layer is marked visible.
        assert [lay["visible"] for lay in heatmap["layers"]] == [True, False, False, False]
        assert "Custom overlay" not in names
        assert "Pace (average)" not in names  # metric layers stay independent checkboxes

    def test_density_layers_match_raster_modes(self):
        """Every raster mode has exactly one density layer entry."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        heatmap = next(g for g in groups if g["label"] == "Heatmap")
        names = {lay["name"] for lay in heatmap["layers"]}
        assert names == set(DENSITY_LAYER_NAMES)

    def test_metric_layers_in_independent_check_group(self):
        """Distinct metrics should be independent checkboxes, not exclusive."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        metric_group = next(g for g in groups if g["label"] == "Metrics")
        assert metric_group["mode"] == "check"
        names = [lay["name"] for lay in metric_group["layers"]]
        assert "Pace (average)" in names

    def test_density_not_duplicated_when_metric_names_is_independent_list(self):
        """Regression: passing the all-inclusive INDEPENDENT_LAYER_NAMES as
        ``metric_layer_names`` (as the production ``build_map`` call does) must
        NOT bucket the density concept layers into both the Heatmap and Metrics
        groups. Each layer must appear exactly once across all groups so the
        panel renders one toggle and one opacity slider per layer."""
        overlay_layers = [
            (name, "data:image/png;base64,x", False) for name in INDEPENDENT_LAYER_NAMES
        ]
        groups = build_layer_group_config(
            overlay_layers,
            has_tracks=False,
            metric_layer_names=INDEPENDENT_LAYER_NAMES,
        )

        seen: list[str] = []
        for group in groups:
            for lay in group["layers"]:
                seen.append(lay["name"])
        assert len(seen) == len(set(seen)), f"unexpected duplicate layer(s): {sorted(set(seen))}"

        # Density layers live only under "Heatmap"; the four pure metrics under "Metrics".
        by_label = {g["label"]: [lay["name"] for lay in g["layers"]] for g in groups}
        heatmap_names = by_label.get("Heatmap", [])
        metric_names = by_label.get("Metrics", [])

        for density_name in DENSITY_LAYER_NAMES:
            assert density_name in heatmap_names
            assert density_name not in metric_names

        for metric_name in METRIC_LAYER_NAMES:
            assert metric_names.count(metric_name) == 1

    def test_non_exclusive_layers_in_check_group(self):
        """Non-exclusive layers should be in a checkbox (independent) group."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        checks = [g for g in groups if g["mode"] == "check"]
        assert checks
        names = [lay["name"] for g in checks for lay in g["layers"]]
        assert "Custom overlay" in names
        metric_names_group = next(g for g in groups if g["label"] == "Metrics")
        metric_names_list = [lay["name"] for lay in metric_names_group["layers"]]
        assert "Pace (average)" in metric_names_list  # metrics stay checkboxes

    def test_no_tracks_group_when_missing(self):
        """Should omit the tracks group when has_tracks is False."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        assert all(g["label"] != "Raw GPS tracks" for g in groups)

    def test_empty_layers(self):
        """With no overlay layers and no tracks, groups should be empty."""
        assert build_layer_group_config([], has_tracks=False) == []

    def test_layers_carry_per_layer_opacity(self):
        """Heatmap/metric layers seed per-layer opacity from map_opacity, while the
        raw GPS tracks keep their own vector stroke opacity (TRACK_OPACITY)."""
        groups = build_layer_group_config(self.layers, has_tracks=True)
        names = {g["label"]: g for g in groups}
        # Raw GPS tracks group uses the vector stroke default, not map_opacity.
        assert names["Raw GPS tracks"]["layers"][0]["opacity"] == TRACK_OPACITY
        # Every raster/heatmap layer across all other groups defaults to 0.85.
        for g in groups:
            for lay in g["layers"]:
                if g["label"] == "Raw GPS tracks":
                    assert lay["opacity"] == TRACK_OPACITY
                else:
                    assert lay["opacity"] == 0.85

    def test_layer_opacity_respects_map_opacity(self):
        """map_opacity should flow into every raster layer entry's opacity, but not
        into the raw GPS tracks (a vector layer with its own fixed stroke opacity)."""
        groups = build_layer_group_config(self.layers, has_tracks=True, map_opacity=0.4)
        for g in groups:
            for lay in g["layers"]:
                if g["label"] == "Raw GPS tracks":
                    assert lay["opacity"] == TRACK_OPACITY
                else:
                    assert lay["opacity"] == 0.4

    """Tests for CARTO API key loading and tile URL building."""

    def test_get_carto_api_key_returns_env_value(self, carto_api_key):
        """Should return the key from the environment."""
        assert get_carto_api_key() == "default_public_testkey"

    def test_get_carto_api_key_raises_when_missing(self, monkeypatch):
        """Should raise ValueError when CARTO_API_KEY is not set."""
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        with pytest.raises(ValueError, match="CARTO_API_KEY is not set"):
            get_carto_api_key()

    def test_get_carto_api_key_ignores_blank(self, monkeypatch):
        """Should raise when CARTO_API_KEY is blank or whitespace."""
        monkeypatch.setenv("CARTO_API_KEY", "   ")
        with pytest.raises(ValueError, match="CARTO_API_KEY is not set"):
            get_carto_api_key()

    def test_build_tile_url_contains_key(self, carto_api_key):
        """build_tile_url should embed the API key and default style."""
        url = build_tile_url()
        assert url.startswith("https://basemaps.cartocdn.com/rastertiles/dark_all/")
        assert url.endswith("?key=default_public_testkey")

    def test_build_tile_url_custom_style(self, carto_api_key):
        """build_tile_url should use the supplied style."""
        url = build_tile_url("light_all")
        assert url.startswith("https://basemaps.cartocdn.com/rastertiles/light_all/")
        assert url.endswith("?key=default_public_testkey")


class TestConstants:
    """Tests for module constants."""

    def test_controls_css_not_empty(self):
        """controls_css() should return a non-empty <style> block."""
        css = controls_css()
        assert len(css) > 0
        assert "<style>" in css
        assert "leaflet-control-layers" in css

    def test_folium_map_sizing_beats_folium_id_rule(self):
        """The sidebar map-offset sizing must survive Folium's #map_<hash> rule.

        Folium emits ``#map_<hash> { width: 100%; height: 100% }`` for the map
        container. An ID selector outspecifies the panel's ``.folium-map`` class
        rule, so the sizing properties need ``!important`` — without it the
        margin-left applies but the width silently does not, the container ends
        up sidebar-width too wide, and Leaflet centres the home location inside
        the hidden off-screen overflow (marker right of the visible centre).
        """
        css = controls_css()
        # Extract the .folium-map rule block and check each sizing declaration
        # carries !important (so it wins over Folium's ID rule regardless of
        # the hash suffix in the id).
        import re

        match = re.search(r"\.folium-map\s*\{([^}]*)\}", css)
        assert match, ".folium-map rule missing from panel.css"
        body = match.group(1)
        for prop in ("margin-left", "width", "height"):
            decl = re.search(rf"{prop}\s*:\s*([^;]+);", body)
            assert decl, f"{prop} declaration missing from .folium-map rule"
            assert decl.group(1).rstrip().endswith("!important"), (
                f"{prop} must be !important to beat Folium's #map_<hash> ID rule; "
                f"got: {decl.group(1).strip()}"
            )

    def test_exclusive_layer_control_class_exists(self):
        """ExclusiveLayerControl class should exist and be instantiable."""
        assert ExclusiveLayerControl is not None
        instance = ExclusiveLayerControl()
        assert instance is not None
        assert instance._name == "ExclusiveLayerControl"
