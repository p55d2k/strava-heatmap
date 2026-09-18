"""
Unit tests for src/map_builder.py - map building and HTML output functions.
"""

import json
import os
import re
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
    CartoApiKeyMissingError,
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
    compute_layer_counts,
    control_panel_script,
    controls_css,
    encode_for_embedding,
    get_carto_api_key,
    home_marker_radius,
    legend_css,
    legend_row,
    load_env_files,
    pace_str,
    require_carto_api_key,
)
from src.map_builder.constants import (
    COVERAGE_LAYER,
    DEFAULT_RASTER_MODE,
    DENSITY_LAYER_NAMES,
    DENSITY_VIRTUAL_LAYER,
    LEGEND_IDS,
    RASTER_MODE_LABELS,
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

    def test_visible_for_marks_only_the_requested_layers(self):
        """The widget's legend must show exactly the rows for the layers it ships
        (it has no layer control to sync a full legend)."""
        builder = LegendBuilder()

        rows = builder.visible_for(["GPS Density (Time Spent)", "Pace (average)"])

        assert {row.layer_name for row in rows if row.visible} == {
            "GPS Density (Time Spent)",
            "Pace (average)",
        }
        # The other rows keep their configured (hidden) state.
        hidden = {row.layer_name for row in rows if not row.visible}
        assert "Heart rate (average)" in hidden
        assert "Coverage (Places Visited)" in hidden

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

    def test_marks_itself_for_exclusion_from_png_exports(self):
        """The marker must carry the class the PNG export filters on, so the
        home location never ends up in an exported picture."""
        m = folium.Map(location=[45.0, -122.0], zoom_start=14, tiles=None)
        marker = ScalableHomeMarker(location=[45.0, -122.0])
        marker.add_to(m)

        script = marker._template.module.script(marker, {})

        # Leaflet's Path option (applied to the SVG path by the SVG renderer).
        assert 'className: "hcp-home-marker"' in script


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
    @patch("src.map_builder.map_builder.ControlPanel")
    def test_forwards_tooltips_payload(
        self,
        mock_control_panel,
        mock_layer_control,
        mock_image_overlay,
        mock_polyline,
        mock_feature_group,
        mock_tile_layer,
        mock_map,
    ):
        """build_map should hand the activity index to the control panel."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_control_panel.return_value = MagicMock()

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
            tooltips="encoded-activity-index",
        )

        mock_control_panel.assert_called_once()
        assert mock_control_panel.call_args[1]["tooltips"] == "encoded-activity-index"

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
        assert tile_kwargs["keep_buffer"] == 0
        assert "carto.com/attributions" in tile_kwargs["attr"]
        # Tiles must be requested with CORS (Leaflet's camelCase option name) so
        # the control panel's "Save as PNG" export can read them off a canvas.
        assert tile_kwargs["crossOrigin"] is True

    def test_build_map_requires_carto_api_key(self, monkeypatch):
        """build_map refuses to render without a key instead of falling back."""
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        with pytest.raises(CartoApiKeyMissingError):
            build_map(
                self.tracks,
                self.layers,
                self.bounds,
                self.centre,
                self.legend_html,
                self.output_path,
                self.map_opacity,
            )

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

    def test_html_contains_save_as_png_button(self):
        """The panel offers a static image export: a Save as PNG button plus the
        status line it reports progress and failures in.

        The button sits in its own section after the view actions so it reads as
        the primary action rather than another view control.
        """
        html = build_control_panel_html()
        match = re.search(r'<button[^>]*id="hcp-export-png".*?</button>', html, re.DOTALL)
        assert match, "no Save as PNG button in the panel markup"
        assert "Save as PNG" in match.group(0)
        assert 'id="hcp-export-status"' in html
        # What the export captures is not obvious from the label, so this one
        # button does carry an explanation (unlike Fit map / Reset / Legend).
        assert "data-hcp-help=" in match.group(0)
        assert "hcp-info" in match.group(0)
        # It comes after the Fit/reset/legend action row.
        assert html.index("hcp-actions") < html.index('id="hcp-export-png"')

    def test_script_contains_png_export_logic(self):
        """panel.js must wire the Save as PNG button to the html2canvas export."""
        script = control_panel_script()
        assert "hcp-export-png" in script
        assert "hcp-export-status" in script
        assert "exportMapPng" in script
        assert "html2canvas" in script
        assert "useCORS" in script
        # The library is fetched lazily, and the export requests the tiles with
        # CORS so the canvas can be written out at all.
        assert "cdn.jsdelivr.net/npm/html2canvas" in script
        assert "crossOrigin: true" in script

    def test_html_contains_export_geojson_button(self):
        """The panel offers a GeoJSON download of the rasterized grids.

        Like Save as PNG it is a primary action, so it lives in the export
        section (below the view actions) and carries an explanation.
        """
        html = build_control_panel_html()
        match = re.search(r'<button[^>]*id="hcp-export-geojson".*?</button>', html, re.DOTALL)
        assert match, "no Export GeoJSON button in the panel markup"
        assert "Export GeoJSON" in match.group(0)
        assert "data-hcp-help=" in match.group(0)
        assert "hcp-info" in match.group(0)
        # Shares the export section (and its status line) with Save as PNG.
        assert html.index('id="hcp-export-png"') < html.index('id="hcp-export-geojson"')
        assert html.index('id="hcp-export-geojson"') < html.index('id="hcp-export-status"')

    def test_script_contains_geojson_export_logic(self):
        """panel.js must inflate the embedded grids and hand them to the browser."""
        script = control_panel_script()
        assert "hcp-export-geojson" in script
        assert "hcp-geojson-data" in script
        assert "heatmap.geojson" in script
        assert "application/geo+json" in script
        assert "exportGeojsonData" in script
        # The grids are embedded compressed too, so the button has to inflate
        # them with the browser's own decompressor before offering the download.
        assert "DecompressionStream" in script
        assert "deflate" in script

    def test_control_panel_embeds_geojson_for_the_download(self):
        """ControlPanel should inline the compressed grids in an inert block."""
        geojson = '{"type":"FeatureCollection","features":[]}'
        payload = encode_for_embedding(geojson)
        panel = ControlPanel(centre=[1.0, 2.0], geojson=payload)
        html = panel._template.module.html(panel, {})
        assert 'id="hcp-geojson-data"' in html
        assert 'type="application/geo+json"' in html
        assert payload in html
        # The document travels compressed, not verbatim.
        assert geojson not in html
        # Without grids the block is left out entirely; the button then reports
        # that there is nothing to export.
        bare = ControlPanel(centre=[1.0, 2.0])
        assert "hcp-geojson-data" not in bare._template.module.html(bare, {})

    def test_html_contains_export_gpx_button(self):
        """The panel offers a download of the raw tracks as GPX.

        Like the other two exports it lives in the export section and carries an
        explanation (nothing on the button says it is the same document the
        build wrote to OUTPUT_GPX).
        """
        html = build_control_panel_html()
        match = re.search(r'<button[^>]*id="hcp-export-gpx".*?</button>', html, re.DOTALL)
        assert match, "no Export GPX button in the panel markup"
        assert "Export GPX" in match.group(0)
        assert "data-hcp-help=" in match.group(0)
        assert "hcp-info" in match.group(0)
        # Shares the export section (and its status line) with the other exports.
        assert html.index('id="hcp-export-geojson"') < html.index('id="hcp-export-gpx"')
        assert html.index('id="hcp-export-gpx"') < html.index('id="hcp-export-status"')

    def test_script_contains_gpx_export_logic(self):
        """panel.js must inflate the embedded GPX and hand it to the browser."""
        script = control_panel_script()
        assert "hcp-export-gpx" in script
        assert "hcp-gpx-data" in script
        assert "tracks.gpx" in script
        assert "application/gpx+xml" in script
        assert "exportGpxTracks" in script
        # The document is embedded compressed, so the button has to inflate it
        # with the browser's own decompressor before offering the download.
        assert "DecompressionStream" in script
        assert "deflate" in script

    def test_control_panel_embeds_gpx_for_the_download(self):
        """ControlPanel should inline the compressed GPX in an inert script block."""
        payload = encode_for_embedding("<gpx><trk><name>run</name></trk></gpx>")
        panel = ControlPanel(centre=[1.0, 2.0], gpx=payload)
        html = panel._template.module.html(panel, {})
        assert 'id="hcp-gpx-data"' in html
        assert 'type="application/gpx+xml"' in html
        assert payload in html
        # Without tracks the block is left out entirely; the button then reports
        # that there is nothing to export.
        bare = ControlPanel(centre=[1.0, 2.0])
        assert "hcp-gpx-data" not in bare._template.module.html(bare, {})

    def test_control_panel_embeds_activity_index_for_click_tooltips(self):
        """ControlPanel should inline the compressed per-cell activity index."""
        payload = encode_for_embedding(
            '{"cellSize":10.0,"xMin":0.0,"yMax":0.0,"cols":1,"rows":1,'
            '"activities":[["2024-01-01","Run","5:00/km",150,""]],"cells":{"0":[0]}}'
        )
        panel = ControlPanel(centre=[1.0, 2.0], tooltips=payload)
        html = panel._template.module.html(panel, {})
        assert 'id="hcp-activity-data"' in html
        assert 'type="application/json"' in html
        assert payload in html
        # Without an index the block is left out; clicks then do nothing.
        bare = ControlPanel(centre=[1.0, 2.0])
        assert "hcp-activity-data" not in bare._template.module.html(bare, {})

    def test_script_contains_activity_tooltip_logic(self):
        """panel.js must inflate the index and list activities on a map click."""
        script = control_panel_script()
        assert "hcp-activity-data" in script
        assert "installActivityTooltips" in script
        assert "buildActivityPopup" in script
        # A click gathers activities from a neighbourhood, not just one cell, so
        # a route beside the clicked pixel is still found.
        assert "activitiesNear" in script
        assert "ACTIVITY_SEARCH_RADIUS_PX" in script
        # Each row reports how far the route is, so several routes caught by one
        # click stay tellable apart.
        assert "hcp-activity-distance" in script
        assert "formatDistance" in script
        # The list can be narrowed in place, by activity type and date range.
        assert "hcp-filter-chip" in script
        assert "hcp-filter-date-input" in script
        # The index travels compressed, so the click has to inflate it with the
        # browser's own decompressor (lazily — see the constant + guard).
        assert "DecompressionStream" in script
        assert "inflateZlib" in script

    def test_css_styles_activity_popup(self):
        """The popup is dark-themed to match the rest of the map chrome."""
        css = controls_css()
        assert ".hcp-activity-popup" in css
        assert ".hcp-activity-name" in css
        assert ".hcp-activity-distance" in css
        assert ".hcp-activity-link" in css
        assert ".hcp-filter-chip" in css
        assert ".hcp-filter-date" in css

    def test_gpx_download_is_named_after_output_gpx(self):
        """The panel offers the download under the configured OUTPUT_GPX name."""
        default = json.loads(ControlPanel(centre=[1.0, 2.0]).config_json)
        assert default["gpxFilename"] == "tracks.gpx"

        named = json.loads(ControlPanel(centre=[1.0, 2.0], gpx_filename="my_runs.gpx").config_json)
        assert named["gpxFilename"] == "my_runs.gpx"

    def test_script_renders_a_still_map_without_the_home_marker(self):
        """The export must capture a map that is not moving, and must leave the
        home marker out of the picture.

        Tiles shifting mid-capture smear the image, so the exporter waits for
        the map to settle and holds it still while rendering; the home marker
        (a personal location that reads as an artefact in a shared image) is
        filtered out by the class ScalableHomeMarker puts on it.
        """
        script = control_panel_script()
        # Wait for / enforce a still map.
        assert "mapIsMoving" in script
        assert "whenMapSettled" in script
        assert "freezeMapInteractions" in script
        assert "thawMapInteractions" in script
        assert "_animatingZoom" in script
        assert "hcp-exporting" in script
        # Leave the home marker out of the render.
        assert "ignoreElements" in script
        assert '"hcp-home-marker"' in script

    def test_export_disables_map_controls_while_rendering(self):
        """The interaction handlers that could move the map mid-capture are
        switched off for the duration of the export."""
        script = control_panel_script()
        for handler in ("dragging", "touchZoom", "doubleClickZoom", "scrollWheelZoom"):
            assert f'"{handler}"' in script, f"{handler} is not frozen during export"
        # The zoom control's stylesheet hook lives in the panel CSS.
        assert ".folium-map.hcp-exporting .leaflet-control-zoom" in controls_css()

    def test_html_contains_advanced_section(self):
        """The Advanced section is its own collapsible menu (like Layer opacity)
        holding the rasterization-mode dropdown; collapsed on first paint."""
        html = build_control_panel_html()
        assert "hcp-advanced-toggle" in html
        assert "hcp-advanced-body" in html
        assert "hcp-density-mode" in html
        assert "hcp-select" in html
        assert 'aria-expanded="false"' in html
        assert "Advanced" in html

    def test_advanced_section_layout(self):
        """The Advanced section sits BELOW the Layer opacity section, and the
        Home marker toggle lives INSIDE the Advanced body so it collapses
        together with the rasterization-mode dropdown."""
        html = build_control_panel_html()
        opacity_pos = html.index('id="hcp-opacity-toggle"')
        advanced_pos = html.index('id="hcp-advanced-toggle"')
        advanced_body_pos = html.index('id="hcp-advanced-body"')
        home_pos = html.index('id="hcp-home-section"')
        actions_pos = html.index("hcp-actions")
        # Advanced comes after Layer opacity (and before the action buttons).
        assert opacity_pos < advanced_pos < actions_pos
        # The Home marker section is nested inside the Advanced body.
        assert advanced_body_pos < home_pos
        adv_body = html[advanced_body_pos:actions_pos]
        assert 'id="hcp-home-section"' in adv_body
        assert 'id="hcp-density-mode"' in adv_body

    def test_html_has_no_inline_opacity(self):
        """build_control_panel_html no longer hard-codes an opacity percentage."""
        html = build_control_panel_html()
        assert "opacity_pct" not in html
        assert 'value="85"' not in html
        assert 'value="0"' not in html

    def test_script_renders_per_layer_data_counts(self):
        """Each layer toggle must be able to show how much data it carries."""
        script = control_panel_script()
        assert "makeLayerCountBadge" in script
        assert "hcp-layer-count" in script
        # The badge reads the build-time count/unit pair off the layer config.
        assert "lDef.count" in script
        assert "lDef.unit" in script
        # The badge is styled by the shared panel stylesheet.
        assert ".heatmap-control-panel .hcp-layer-count" in controls_css()

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

    def test_script_contains_advanced_dropdown_logic(self):
        """control_panel_script must wire the Advanced dropdown and the virtual
        GPS Density row binding."""
        script = control_panel_script()
        assert "hcp-advanced-toggle" in script
        assert "hcp-advanced-body" in script
        assert "hcp-density-mode" in script
        assert "resolveDensityLayer" in script
        assert "syncAdvancedFromMap" in script

    def test_html_explains_the_controls_that_need_it(self):
        """Controls whose purpose isn't obvious must carry an explanation.

        A user shouldn't have to guess what a control does: each one advertises
        a `data-hcp-help` blurb plus the `.hcp-info` badge that points at it.
        """
        html = build_control_panel_html()
        for control in (
            'id="hcp-basemap"',
            'id="hcp-density-mode"',
            'id="hcp-home-marker"',
        ):
            # The explanation may sit on the control itself or on its label, but
            # it must appear before the next control's markup starts.
            start = html.index(control)
            window = html[max(0, start - 400) : start + 400]
            assert "data-hcp-help=" in window, f"no help text near {control}"
            assert "hcp-info" in window, f"no info badge near {control}"

    def test_html_leaves_self_explanatory_controls_alone(self):
        """Section headers and action buttons get no hover card or badge.

        Their labels already say what they do, so an explanation there would be
        noise rather than help.
        """
        html = build_control_panel_html()
        for control in (
            "hcp-opacity-toggle",
            "hcp-advanced-toggle",
            "hcp-fit",
            "hcp-reset",
            "hcp-legend",
        ):
            match = re.search(rf'<button[^>]*id="{control}".*?</button>', html, re.DOTALL)
            assert match, f"{control} not found in the panel markup"
            assert "data-hcp-help" not in match.group(0), f"{control} has help text"
            assert "hcp-info" not in match.group(0), f"{control} has an info badge"

    def test_html_help_text_is_plain_language(self):
        """Help text must be short and jargon-free enough for a lay person."""
        html = build_control_panel_html()
        blurbs = re.findall(r'data-hcp-help="([^"]+)"', html)
        assert blurbs, "the panel must carry at least one explanation"
        for blurb in blurbs:
            # Long enough to actually explain, short enough to read at a glance.
            assert 30 <= len(blurb) <= 220, blurb
            # Plain sentences — no implementation jargon leaking into the UI.
            for jargon in ("rasteriz", "normaliz", "opacity value", "layer group"):
                assert jargon not in blurb.lower(), blurb
            assert blurb.endswith("."), blurb

    def test_script_explains_every_layer_toggle(self):
        """panel.js must supply help text for every layer the panel can show."""
        script = control_panel_script()
        assert "installHelpTooltips" in script
        assert "hcp-tooltip" in script
        assert "data-hcp-help" in script
        # The panel renders the virtual "GPS Density" row, not the per-mode
        # layer names behind it, so those are the rows that need explanations.
        rows = [DENSITY_VIRTUAL_LAYER, COVERAGE_LAYER, *METRIC_LAYER_NAMES, "Raw GPS tracks"]
        assert DENSITY_VIRTUAL_LAYER not in INDEPENDENT_LAYER_NAMES  # sanity
        for name in rows:
            assert f'"{name}":' in script, f"no help text for layer {name!r}"

    def test_script_explains_opacity_and_basemap_controls(self):
        """The client-rendered controls carry explanations too."""
        script = control_panel_script()
        assert "OPACITY_HELP" in script
        assert "HEATMAP_OPACITY_HELP" in script
        assert "BASEMAP_HELP" in script
        for style in CARTO_STYLES:
            assert f"{style}:" in script, f"no help text for basemap style {style!r}"

    def test_control_panel_carries_advanced_config(self):
        """ControlPanel should embed the advanced raster-mode config for panel.js."""
        from src.map_builder.control import build_advanced_config

        panel = ControlPanel(centre=[1.0, 2.0], advanced=build_advanced_config("raw-count"))
        cfg = json.loads(panel.config_json)
        assert cfg["advanced"]["active"] == "raw-count"
        assert [m["key"] for m in cfg["advanced"]["modes"]] == list(RASTER_MODES)
        assert [m["label"] for m in cfg["advanced"]["modes"]] == [
            RASTER_MODE_LABELS[m] for m in RASTER_MODES
        ]
        # Without an advanced section the config key stays present but empty.
        assert json.loads(ControlPanel(centre=[1.0, 2.0]).config_json)["advanced"] == {}

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
        # Each toggle carries how much data feeds it: the fixture track counts
        # as a raw track (the vector layer uses the "track" unit).
        tracks_group = next(g for g in layer_groups if g["label"] == "Raw GPS tracks")
        assert tracks_group["layers"][0]["count"] == 1
        assert tracks_group["layers"][0]["unit"] == "track"

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
    def test_forwards_geojson_to_control_panel(
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
        """build_map should hand the GeoJSON grids to the panel for embedding."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_exclusive_control.return_value = MagicMock()
        mock_panel.return_value = MagicMock()
        geojson = '{"type":"FeatureCollection","features":[]}'
        payload = encode_for_embedding(geojson)

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
            geojson=payload,
        )

        mock_panel.assert_called_once()
        assert mock_panel.call_args[1]["geojson"] == payload

    @patch("src.map_builder.map_builder.folium.Map")
    @patch("src.map_builder.map_builder.folium.TileLayer")
    @patch("src.map_builder.map_builder.folium.FeatureGroup")
    @patch("src.map_builder.map_builder.folium.PolyLine")
    @patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay")
    @patch("src.map_builder.map_builder.folium.LayerControl")
    @patch("src.map_builder.map_builder.ExclusiveLayerControl")
    @patch("src.map_builder.map_builder.ControlPanel")
    def test_passes_the_gpx_export_to_the_panel(
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
        """build_map should hand the compressed tracks and their name to the panel."""
        mock_map.return_value = MagicMock()
        mock_tile_layer.return_value = MagicMock()
        mock_feature_group.return_value = MagicMock()
        mock_polyline.return_value = MagicMock()
        mock_image_overlay.return_value = MagicMock()
        mock_layer_control.return_value = MagicMock()
        mock_exclusive_control.return_value = MagicMock()
        mock_panel.return_value = MagicMock()
        payload = encode_for_embedding("<gpx/>")

        build_map(
            self.tracks,
            self.layers,
            self.bounds,
            self.centre,
            self.legend_html,
            self.output_path,
            self.map_opacity,
            gpx=payload,
            gpx_filename="my_runs.gpx",
        )

        mock_panel.assert_called_once()
        assert mock_panel.call_args[1]["gpx"] == payload
        assert mock_panel.call_args[1]["gpx_filename"] == "my_runs.gpx"

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


class TestComputeLayerCounts:
    """Tests for compute_layer_counts (per-layer data-volume figures)."""

    def test_counts_activities_carrying_each_metric(self):
        """Density/coverage count every activity; each metric counts only the
        activities whose devices recorded that metric."""
        tracks = [
            ("full", [[1.0, 2.0, 3.0, 120.0, 10.0]]),
            ("speed-only", [[1.0, 2.0, 4.0, None, None]]),
            ("bare", [[1.0, 2.0]]),
        ]
        counts = compute_layer_counts(tracks)

        assert counts["Raw GPS tracks"] == 3
        assert counts[DENSITY_VIRTUAL_LAYER] == 3
        assert counts[COVERAGE_LAYER] == 3
        assert counts["Pace (average)"] == 2
        assert counts["Heart rate (average)"] == 1
        assert counts["Gradient (absolute)"] == 1
        assert counts["Gradient (change)"] == 1

    def test_empty_tracks_yield_zero_counts(self):
        counts = compute_layer_counts([])
        assert counts
        assert all(value == 0 for value in counts.values())


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

    def test_heatmap_group_shows_two_concepts(self):
        """The Heatmap radio group presents only the two density CONCEPTS — a
        virtual "GPS Density" row (bound client-side to the raster mode picked
        in the Advanced dropdown) plus Coverage. The per-mode layers never
        appear as their own toggles."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        heatmap = next(g for g in groups if g["label"] == "Heatmap")
        assert heatmap["mode"] == "radio"
        names = [lay["name"] for lay in heatmap["layers"]]
        assert names == [DENSITY_VIRTUAL_LAYER, COVERAGE_LAYER]
        # The virtual GPS Density row inherits the visibility of whichever mode
        # layer is on at first paint (Time Spent in this fixture).
        assert [lay["visible"] for lay in heatmap["layers"]] == [True, False]
        assert "Custom overlay" not in names
        assert "Pace (average)" not in names  # metric layers stay independent checkboxes

    def test_density_layers_match_raster_modes(self):
        """Every raster mode keeps exactly one density overlay; none of them is
        offered as an individual panel toggle any more (the Advanced dropdown
        swaps between them client-side)."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        heatmap = next(g for g in groups if g["label"] == "Heatmap")
        group_names = {lay["name"] for lay in heatmap["layers"]}
        mode_layer_names = set(DENSITY_MODE_LAYERS.values())
        # The per-mode layers are NOT individual rows; Coverage is.
        assert COVERAGE_LAYER in group_names
        assert not (mode_layer_names & group_names)
        assert mode_layer_names <= set(DENSITY_LAYER_NAMES)

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
        groups. Every layer appears at most once across all groups, and each
        layer lives in exactly the group the panel expects: the Heatmap group
        shows the two density concepts (virtual "GPS Density" + Coverage), the
        per-mode layers appear in no toggle group (the Advanced dropdown swaps
        them), and the four pure metrics stay in "Metrics"."""
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

        by_label = {g["label"]: [lay["name"] for lay in g["layers"]] for g in groups}
        heatmap_names = by_label.get("Heatmap", [])
        metric_names = by_label.get("Metrics", [])

        assert DENSITY_VIRTUAL_LAYER in heatmap_names
        assert COVERAGE_LAYER in heatmap_names
        assert COVERAGE_LAYER not in metric_names

        # None of the per-mode density layers is offered as an individual toggle.
        for mode_layer in DENSITY_MODE_LAYERS.values():
            assert mode_layer not in heatmap_names
            assert mode_layer not in metric_names

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

    def test_layers_carry_data_counts_when_provided(self):
        """layer_counts should attach ``count`` + ``unit`` to each matching layer
        so the panel can show the layer's data volume on its toggle."""
        counts = {
            "Raw GPS tracks": 3,
            DENSITY_VIRTUAL_LAYER: 3,
            COVERAGE_LAYER: 2,
            "Pace (average)": 1,
        }
        groups = build_layer_group_config(self.layers, has_tracks=True, layer_counts=counts)
        by_label = {g["label"]: g for g in groups}

        # Raw tracks count polylines; every other layer counts activities.
        tracks = by_label["Raw GPS tracks"]["layers"][0]
        assert tracks["count"] == 3
        assert tracks["unit"] == "track"

        heatmap = {lay["name"]: lay for lay in by_label["Heatmap"]["layers"]}
        assert heatmap[DENSITY_VIRTUAL_LAYER]["count"] == 3
        assert heatmap[DENSITY_VIRTUAL_LAYER]["unit"] == "activity"
        assert heatmap[COVERAGE_LAYER]["count"] == 2

        metrics = {lay["name"]: lay for lay in by_label["Metrics"]["layers"]}
        assert metrics["Pace (average)"]["count"] == 1
        assert metrics["Pace (average)"]["unit"] == "activity"

        # A layer with no count (a bespoke overlay) gets no badge fields.
        overlays = {lay["name"]: lay for lay in by_label["Overlays"]["layers"]}
        assert "count" not in overlays["Custom overlay"]
        assert "unit" not in overlays["Custom overlay"]

    def test_layers_have_no_count_without_layer_counts(self):
        """Without layer_counts no toggle advertises a data volume."""
        groups = build_layer_group_config(self.layers, has_tracks=True)
        for group in groups:
            for lay in group["layers"]:
                assert "count" not in lay
                assert "unit" not in lay

    """Tests for CARTO API key loading and tile URL building."""

    def test_get_carto_api_key_returns_env_value(self, carto_api_key):
        """Should return the key from the environment."""
        assert get_carto_api_key() == "default_public_testkey"

    def test_get_carto_api_key_blank_reads_as_unset(self, monkeypatch):
        """A blank key is reported as unset rather than as whitespace."""
        monkeypatch.setenv("CARTO_API_KEY", "   ")
        assert get_carto_api_key() == ""

    def test_require_carto_api_key_raises_when_missing(self, monkeypatch):
        """CARTO is the only basemap, so a missing key is a hard error."""
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        with pytest.raises(CartoApiKeyMissingError):
            require_carto_api_key()

    def test_require_carto_api_key_raises_when_blank(self, monkeypatch):
        """A whitespace-only key is treated as missing too."""
        monkeypatch.setenv("CARTO_API_KEY", "   ")
        with pytest.raises(CartoApiKeyMissingError):
            require_carto_api_key()

    def test_require_carto_api_key_rejects_env_example_placeholder(self, monkeypatch):
        """An unfilled .env copied from the template is not a usable key."""
        monkeypatch.setenv("CARTO_API_KEY", "your_key_here")
        with pytest.raises(CartoApiKeyMissingError):
            require_carto_api_key()

    def test_require_carto_api_key_returns_configured_key(self, carto_api_key):
        """A configured key is returned unchanged."""
        assert require_carto_api_key() == "default_public_testkey"

    def test_load_env_files_reads_from_the_given_directory(self, tmp_path, monkeypatch):
        """`.env` is resolved from the search directory, not this module.

        Regression: a bare ``load_dotenv()`` resolves the file relative to the
        calling module, so the ``uv tool install .`` CLI (whose copy lives in
        site-packages) never saw the project's ``.env``.
        """
        monkeypatch.setenv("CARTO_TEST_KEY", "placeholder")
        monkeypatch.delenv("CARTO_TEST_KEY")
        (tmp_path / ".env").write_text("CARTO_TEST_KEY=from_env_file\n")

        loaded = load_env_files(tmp_path)

        assert (tmp_path / ".env").resolve() in [path.resolve() for path in loaded]
        assert os.environ["CARTO_TEST_KEY"] == "from_env_file"

    def test_load_env_files_lets_the_real_environment_win(self, tmp_path, monkeypatch):
        """An exported variable is not overwritten by the file."""
        monkeypatch.setenv("CARTO_TEST_KEY", "from_shell")
        (tmp_path / ".env").write_text("CARTO_TEST_KEY=from_env_file\n")

        load_env_files(tmp_path)

        assert os.environ["CARTO_TEST_KEY"] == "from_shell"

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

    def test_build_tile_url_requires_api_key(self, monkeypatch):
        """Without a key there is no tile URL: CARTO is the only provider."""
        monkeypatch.delenv("CARTO_API_KEY", raising=False)
        with pytest.raises(CartoApiKeyMissingError):
            build_tile_url()

    def test_build_tile_url_rejects_unknown_style(self, carto_api_key):
        """Only the supported CARTO styles may be requested."""
        with pytest.raises(ValueError):
            build_tile_url("rainbow")


class TestConstants:
    """Tests for module constants."""

    def test_controls_css_not_empty(self):
        """controls_css() should return a non-empty <style> block."""
        css = controls_css()
        assert len(css) > 0
        assert "<style>" in css
        assert "leaflet-control-layers" in css

    def test_controls_css_includes_legend_and_panel(self):
        """The full page needs both stylesheets: the shared legend rules and the
        panel (with its sidebar layout)."""
        css = controls_css()
        assert "#heatmap-legend" in css
        assert ".folium-map" in css

    def test_legend_css_is_widget_safe(self):
        """The legend-only stylesheet keeps the legend card but none of the
        sidebar layout that would misplace a control-less widget's map."""
        css = legend_css()
        assert "<style>" in css
        assert "#heatmap-legend" in css
        assert ".hcp-legend-row" in css
        assert ".folium-map" not in css
        assert "leaflet-control-layers" not in css
        assert css.count(":root") == 1

    def test_attribution_is_minimal_but_not_hidden(self):
        """The basemap credit is styled down, never hidden.

        The credit is required by the tile licence (CARTO tiles are a rendering
        of OpenStreetMap data), so the stylesheet may shrink and mute it but
        must not contain any rule that removes it from view.
        """
        css = legend_css()
        assert ".leaflet-control-attribution" in css
        # Shrunk and muted...
        assert "font-size: 10px" in css
        # ...but never taken off the map.
        assert "display: none" not in css
        assert "visibility: hidden" not in css

    def test_attribution_styling_ships_to_both_pages(self):
        """Full page and widget both show attribution, so both get the styling."""
        assert ".leaflet-control-attribution" in legend_css()
        assert ".leaflet-control-attribution" in controls_css()

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


class TestEmbedMap:
    """Tests for the minimal iframe widget built with ``embed=True``.

    The widget is the same heatmap with every control removed and the view
    pinned to the data bounds, so these tests pin the two halves of that
    promise: nothing interactive is emitted, and the configurable pieces
    (legend, attribution, home marker, tracks) follow the caller's flags.
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.tracks = [("Track 1", [[45.0, -122.0], [45.001, -122.001]])]
        self.layers = [
            ("GPS Density (Time Spent)", "data:image/png;base64,visible", True),
            ("GPS Density (Raw Passes)", "data:image/png;base64,hidden", False),
            ("Pace (average)", "data:image/png;base64,pace", False),
            ("Heart rate (average)", "data:image/png;base64,hr", False),
            ("Gradient (absolute)", "data:image/png;base64,grad", False),
        ]
        self.bounds = [[44.9, -122.1], [45.1, -121.9]]
        self.centre = [45.0, -122.0]
        self.home = [45.01, -122.01]
        self.legend_html = "<div>Legend</div>"
        self.output_path = Path("/tmp/test_embed_map.html")
        self.map_opacity = 0.7

    def _build(self, **overrides):
        """Call build_map in widget mode with every Folium element mocked.

        Returns the mocks so a test can assert on what was (and was not)
        emitted. ``overrides`` lets a test flip one embed_* flag at a time.
        """
        kwargs = {"carto_style": "dark_all", "home": self.home, "embed": True}
        kwargs.update(overrides)
        with (
            patch("src.map_builder.map_builder.folium.Map") as mock_map,
            patch("src.map_builder.map_builder.folium.TileLayer") as mock_tile,
            patch("src.map_builder.map_builder.folium.FeatureGroup") as mock_feature_group,
            patch("src.map_builder.map_builder.folium.PolyLine") as mock_polyline,
            patch("src.map_builder.map_builder.folium.raster_layers.ImageOverlay") as mock_overlay,
            patch("src.map_builder.map_builder.folium.LayerControl") as mock_layer_control,
            patch("src.map_builder.map_builder.ExclusiveLayerControl") as mock_exclusive,
            patch("src.map_builder.map_builder.ControlPanel") as mock_panel,
            patch("src.map_builder.map_builder.ScalableHomeMarker") as mock_home_marker,
        ):
            for mock in (
                mock_tile,
                mock_feature_group,
                mock_polyline,
                mock_overlay,
                mock_layer_control,
                mock_exclusive,
                mock_panel,
                mock_home_marker,
            ):
                mock.return_value = MagicMock()
            build_map(
                self.tracks,
                self.layers,
                self.bounds,
                self.centre,
                self.legend_html,
                self.output_path,
                self.map_opacity,
                **kwargs,
            )
            return {
                "map": mock_map,
                "map_instance": mock_map.return_value,
                "overlay": mock_overlay,
                "feature_group": mock_feature_group,
                "polyline": mock_polyline,
                "layer_control": mock_layer_control,
                "exclusive": mock_exclusive,
                "panel": mock_panel,
                "home_marker": mock_home_marker,
            }

    def test_stays_interactive_and_drops_only_the_scale_bar(self):
        """The widget can still be panned, zoomed and scrolled.

        Only the heatmap control panel is dropped, so none of Leaflet's
        interaction options may be switched off — a widget locked to a fixed
        view would defeat the point. Folium's camelCase option names are what
        the JS sees, so an accidental snake_case override would silently do
        nothing; asserting the keys are absent pins both.
        """
        kwargs = self._build()["map"].call_args[1]

        assert kwargs["control_scale"] is False
        for option in (
            "dragging",
            "touchZoom",
            "scrollWheelZoom",
            "doubleClickZoom",
            "boxZoom",
            "keyboard",
            "zoomControl",
            "zoom_control",
        ):
            assert option not in kwargs, f"{option} must not be disabled in the widget"
        # Attribution stays on unless explicitly dropped.
        assert "attributionControl" not in kwargs

    def test_attribution_control_cannot_be_dropped(self):
        """Legacy EMBED_ATTRIBUTION=False must not hide required attribution."""
        kwargs = self._build(embed_attribution=False)["map"].call_args[1]
        assert "attributionControl" not in kwargs

    def test_frames_the_data_bounds_on_load(self):
        """The initial view frames the data; the visitor can move on from there."""
        calls = self._build()
        calls["map_instance"].fit_bounds.assert_called_once_with(self.bounds)

    def test_omits_control_panel_and_layer_control(self):
        """No panel, no hidden Leaflet layer control, no legend-sync script."""
        calls = self._build()
        calls["panel"].assert_not_called()
        calls["layer_control"].assert_not_called()
        calls["exclusive"].assert_not_called()

    def test_writes_only_the_visible_layers(self):
        """Hidden layers are dead weight in a control-less widget, so they are
        left out entirely; only the visible layer's image is embedded."""
        calls = self._build()

        assert calls["overlay"].call_count == 1
        assert calls["overlay"].call_args[1]["image"] == "data:image/png;base64,visible"
        # The raw track group is absent by default, so just the one layer group.
        assert calls["feature_group"].call_count == 1

    def test_keeps_the_legend_by_default(self):
        """The legend (markup plus its stylesheet) is added to the widget.

        The stylesheet must be the legend-only one: the panel stylesheet docks
        a 300px sidebar and offsets the map beside it, which in a widget with no
        sidebar would just leave a blank strip.
        """
        calls = self._build()
        added = calls["map_instance"].get_root().html.add_child.call_args_list
        assert len(added) == 2
        css = added[0].args[0]._template_str
        assert "#heatmap-legend" in css
        assert ".folium-map" not in css
        assert added[1].args[0]._template_str == self.legend_html

    def test_drops_the_legend_when_disabled(self):
        """EMBED_LEGEND=False should add neither the legend nor its stylesheet."""
        calls = self._build(embed_legend=False)
        calls["map_instance"].get_root().html.add_child.assert_not_called()

    def test_no_metrics_by_default(self):
        """Without EMBED_METRICS the widget stays the bare density heatmap."""
        calls = self._build()
        assert calls["overlay"].call_count == 1

    def test_bakes_in_and_shows_configured_metrics(self):
        """Requested metrics travel with the widget and start shown.

        The widget has no toggle to switch a metric on, so a requested metric
        must be visible — unlike the full map, where metric layers start hidden.
        """
        calls = self._build(embed_metrics=["Pace (average)", "Heart rate (average)"])

        images = [call.kwargs["image"] for call in calls["overlay"].call_args_list]
        # The visible density layer comes first, then only the requested metrics.
        assert images == [
            "data:image/png;base64,visible",
            "data:image/png;base64,pace",
            "data:image/png;base64,hr",
        ]
        # Every included layer is added visible (tracks are off here).
        assert [call.kwargs["show"] for call in calls["feature_group"].call_args_list] == [
            True,
            True,
            True,
        ]
        # A metric that was not requested stays out of the file entirely.
        assert "data:image/png;base64,grad" not in images

    def test_tracks_are_left_out_by_default(self):
        """A minimal widget shows the heatmap alone unless tracks are asked for."""
        calls = self._build()
        calls["polyline"].assert_not_called()

    def test_tracks_included_and_visible_when_requested(self):
        """With no controls to switch them on, requested tracks must start shown."""
        calls = self._build(embed_tracks=True)

        assert calls["polyline"].call_count == 1
        track_group = calls["feature_group"].call_args_list[0]
        assert track_group[1]["name"] == "Raw GPS tracks"
        assert track_group[1]["show"] is True

    def test_home_marker_kept_by_default_and_droppable(self):
        """The home marker follows EMBED_HOME_MARKER."""
        calls = self._build()
        calls["home_marker"].assert_called_once()
        calls["home_marker"].return_value.add_to.assert_called_once()

        calls = self._build(embed_home_marker=False)
        calls["home_marker"].assert_not_called()

    def test_saves_to_the_given_output_path(self):
        """The widget is written to its own file, leaving the full map alone."""
        calls = self._build()
        calls["map_instance"].save.assert_called_once_with(self.output_path)
