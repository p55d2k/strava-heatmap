"""
Legend generation for the heatmap.

This module provides functions to generate the legend HTML, including
individual legend rows and the complete legend container. Customize the
``LegendBuilder`` class to further control legend appearance.
"""

from src.map_builder.constants import LEGEND_IDS, DEFAULT_LEGEND_STYLES
from src.map_builder.utils import cmap_to_css, build_style_string


def pace_str(ms: float) -> str:
    """Convert m/s to pace string (min:sec/km)."""
    secs = 1000 / ms
    return f"{int(secs // 60)}:{int(secs % 60):02d}/km"


def legend_row(
    row_id: str, title: str, grad_css: str, label_lo: str, label_hi: str, visible: bool = False
) -> str:
    """Generate HTML for a legend row."""
    display = "block" if visible else "none"
    return f"""
    <div id="{row_id}" style="display:{display}">
      <div style="font-weight:600;margin-bottom:3px;color:#eee">{title}</div>
      <div style="height:10px;border-radius:3px;background:{grad_css};
                  border:1px solid rgba(255,255,255,0.08)"></div>
      <div style="display:flex;justify-content:space-between;
                  margin-top:3px;color:#aaa;font-size:11px">
        <span>{label_lo}</span><span>{label_hi}</span>
      </div>
    </div>"""


class LegendBuilder:
    """Builds the complete legend HTML from normalized data and colormaps.

    Subclass this to customize legend structure, styles, or entries.
    """

    def __init__(self, styles: dict[str, str] | None = None):
        self.styles = styles if styles is not None else dict(DEFAULT_LEGEND_STYLES)

    def container_style(self) -> str:
        """Return the inline style string for the legend container."""
        return build_style_string(self.styles)

    def build_rows(self, normalized: dict, colormaps: dict, max_passes: int) -> str:
        """Build all legend rows as HTML."""
        freq_css = cmap_to_css(colormaps["cmap_count"])
        pace_css = cmap_to_css(colormaps["cmap_speed_rgb"])
        hr_css = cmap_to_css(colormaps["cmap_hr_rgb"])

        rows = [
            legend_row(
                "legend-frequency",
                "Frequency (linear)",
                freq_css,
                "1 pass",
                f"{max_passes} passes",
                visible=True,
            ),
            legend_row(
                "legend-frequency-log",
                "Frequency (log)",
                freq_css,
                "1 pass",
                f"{max_passes} passes (log scale)",
            ),
            legend_row(
                "legend-pace-avg",
                "Pace (average)",
                pace_css,
                pace_str(normalized["s_lo"]),
                pace_str(normalized["s_hi"]),
            ),
            legend_row(
                "legend-heart-rate-avg",
                "Heart rate (average)",
                hr_css,
                f"{normalized['hr_lo']:.0f} bpm",
                f"{normalized['hr_hi']:.0f} bpm",
            ),
            legend_row(
                "legend-gradient",
                "Gradient (absolute)",
                "linear-gradient(to right, rgba(0,0,0,0), rgba(255,255,255,1))",
                f"{normalized['g_lo'] * 100:.1f}%",
                f"{normalized['g_hi'] * 100:.1f}% grade",
            ),
            legend_row(
                "legend-elev-change",
                "Gradient (change)",
                cmap_to_css(colormaps["cmap_elev_rgb"]),
                "descending",
                "ascending",
            ),
        ]
        return "\n      ".join(rows)

    def build(self, normalized: dict, colormaps: dict, max_passes: int) -> str:
        """Build the complete legend HTML."""
        legend_html = f"""
    <div id="heatmap-legend" style="
        {self.container_style()}
    ">
      {self.build_rows(normalized, colormaps, max_passes)}
    </div>
    """
        return legend_html


def build_legend_html(normalized: dict, colormaps: dict, max_passes: int) -> str:
    """Build the complete legend HTML using the default LegendBuilder."""
    return LegendBuilder().build(normalized, colormaps, max_passes)
