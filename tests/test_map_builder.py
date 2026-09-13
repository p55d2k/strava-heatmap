"""
Unit tests for src/map_builder.py - map building and HTML output functions.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.map_builder import (
    CARTO_STYLES,
    DEFAULT_CARTO_STYLE,
    ControlPanel,
    ExclusiveLayerControl,
    LegendBuilder,
    LegendRow,
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

        # Check container uses shared CSS class
        assert 'id="heatmap-legend"' in html
        assert 'class="hcp-legend"' in html

        # Check all legend rows present
        assert "GPS Density (linear)" in html
        assert "GPS Density (log)" in html
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
        }
        self.colormaps = {
            key: MagicMock(side_effect=lambda t: (t, 1 - t, 0.5, 1.0))
            for key in ["cmap_count", "cmap_speed_rgb", "cmap_hr_rgb", "cmap_elev_rgb"]
        }

    def test_default_rows_use_legend_ids_and_exclusive_names(self):
        """Default builder should expose the standard layer->legend id mapping."""
        builder = LegendBuilder()
        assert builder.exclusive_layer_names == [
            "GPS Density (linear)",
            "GPS Density (log)",
            "Pace (average)",
            "Heart rate (average)",
            "Gradient (absolute)",
            "Gradient (change)",
        ]
        assert builder.legend_ids == {
            "GPS Density (linear)": "legend-frequency",
            "GPS Density (log)": "legend-frequency-log",
            "Pace (average)": "legend-pace-avg",
            "Heart rate (average)": "legend-heart-rate-avg",
            "Gradient (absolute)": "legend-gradient",
            "Gradient (change)": "legend-elev-change",
        }

    def test_default_rows_renders_same_html(self):
        """Default-builder output should match the legacy build output."""
        builder = LegendBuilder()
        html = builder.build(self.normalized, self.colormaps, self.normalized["max_passes"])
        assert "GPS Density (linear)" in html
        assert "Heart rate (average)" in html
        assert "120 bpm" in html
        assert "180 bpm" in html
        assert "2.0%" in html
        assert "10.0%" in html

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
        self.legend_html = "<div>Legend</div>"
        self.output_path = Path("/tmp/test_map.html")
        self.map_opacity = 0.7

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

    def test_html_contains_panel_markup(self):
        """build_control_panel_html should contain the key controls."""
        html = build_control_panel_html(opacity=0.7)
        assert "heatmap-control-panel" in html
        assert "hcp-basemap" in html
        assert "hcp-opacity" in html
        assert 'value="70"' in html
        assert "70%" in html
        assert "hcp-fit" in html
        assert "hcp-reset" in html
        assert "hcp-legend" in html
        assert "hcp-toggle" in html

    def test_html_respects_opacity(self):
        """build_control_panel_html should reflect the given opacity percentage."""
        assert 'value="85"' in build_control_panel_html(opacity=0.85)
        assert 'value="0"' in build_control_panel_html(opacity=0.0)

    def test_script_contains_init_function(self):
        """control_panel_script should expose initHeatmapControlPanel."""
        script = control_panel_script()
        assert "initHeatmapControlPanel" in script
        assert "findOverlays" in script
        assert "basemaps.cartocdn.com" in script

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
            ("GPS Density (linear)", "data:image/png;base64,1", True),
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

    def test_exclusive_heatmap_layers_in_radio_group(self):
        """Only the density variants should land in the exclusive radio group."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        radio = [g for g in groups if g["mode"] == "radio"]
        assert radio
        labels = [g["label"] for g in radio]
        assert labels == ["Heatmap"]
        names = [lay["name"] for lay in radio[0]["layers"]]
        assert "GPS Density (linear)" in names
        assert "Custom overlay" not in names  # not a density layer
        assert "Pace (average)" not in names  # metric layers are independent now

    def test_metric_layers_in_independent_check_group(self):
        """Distinct metrics should be independent checkboxes, not exclusive."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        metric_group = next(g for g in groups if g["label"] == "Metrics")
        assert metric_group["mode"] == "check"
        names = [lay["name"] for lay in metric_group["layers"]]
        assert "Pace (average)" in names

    def test_non_exclusive_layers_in_check_group(self):
        """Non-exclusive layers should be in a checkbox (independent) group."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        checks = [g for g in groups if g["mode"] == "check"]
        assert checks
        names = [lay["name"] for g in checks for lay in g["layers"]]
        assert "Custom overlay" in names
        assert "GPS Density (linear)" not in names

    def test_no_tracks_group_when_missing(self):
        """Should omit the tracks group when has_tracks is False."""
        groups = build_layer_group_config(self.layers, has_tracks=False)
        assert all(g["label"] != "Raw GPS tracks" for g in groups)

    def test_empty_layers(self):
        """With no overlay layers and no tracks, groups should be empty."""
        assert build_layer_group_config([], has_tracks=False) == []

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

    def test_exclusive_layer_control_class_exists(self):
        """ExclusiveLayerControl class should exist and be instantiable."""
        assert ExclusiveLayerControl is not None
        instance = ExclusiveLayerControl()
        assert instance is not None
        assert instance._name == "ExclusiveLayerControl"
