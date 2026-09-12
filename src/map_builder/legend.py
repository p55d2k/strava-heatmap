"""
Legend generation for the heatmap.

This module provides functions and classes to generate the legend HTML,
including individual legend rows and the complete legend container.

Rows are fully configurable: build your own ``LegendRow`` definitions (or
start from ``LegendBuilder.default_rows``) and pass them to ``LegendBuilder``.
Each row can be bound to a map overlay layer name; the builder then exposes
``legend_ids`` / ``exclusive_layer_names`` so the dynamic layer control can
show/hide the correct legend row.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.map_builder.constants import DEFAULT_LEGEND_STYLES
from src.map_builder.utils import build_style_string, cmap_to_css


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


@dataclass(frozen=True)
class LegendContext:
    """Build-time data passed to callable legend row fields.

    Callables may use any of these to compute dynamic labels or gradients.
    """

    normalized: dict
    colormaps: dict
    max_passes: int


def _resolve(value, ctx: LegendContext):
    """Return ``value`` resolved against ``ctx`` if it is a callable."""
    return value(ctx) if callable(value) else value


@dataclass(frozen=True)
class LegendRow:
    """Configuration for a single legend row.

    Each display field (``gradient``, ``label_lo``, ``label_hi``) may be a
    plain value or a callable taking a :class:`LegendContext` and returning a
    string. ``row_id`` must be present in the built HTML so that the dynamic
    layer control can locate and show/hide the row.

    ``layer_name`` optionally links the row to the map overlay layer that
    drives its visibility via ``ExclusiveLayerControl``.
    """

    row_id: str
    title: str
    gradient: str | Callable[[LegendContext], str]
    label_lo: str | Callable[[LegendContext], str]
    label_hi: str | Callable[[LegendContext], str]
    visible: bool = False
    layer_name: str | None = None


class LegendBuilder:
    """Builds the complete legend HTML from normalized data and colormaps.

    Rows are configurable via a list of :class:`LegendRow` definitions; start
    from :meth:`default_rows` and extend/filter it, or pass your own rows.
    Dynamically-linked rows expose :attr:`legend_ids` and
    :attr:`exclusive_layer_names` for the layer control.
    """

    def __init__(
        self,
        styles: dict[str, str] | None = None,
        rows: list[LegendRow] | None = None,
    ):
        self.styles = styles if styles is not None else dict(DEFAULT_LEGEND_STYLES)
        self.rows = list(rows) if rows is not None else self.default_rows()

    def default_rows(self) -> list[LegendRow]:
        """Return the default legend row definitions (configurable starting point)."""
        return [
            LegendRow(
                row_id="legend-frequency",
                title="GPS Density (linear)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_count"]),
                label_lo="1 pass",
                label_hi=lambda ctx: f"{ctx.max_passes} passes",
                visible=True,
                layer_name="GPS Density (linear)",
            ),
            LegendRow(
                row_id="legend-frequency-log",
                title="GPS Density (log)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_count"]),
                label_lo="1 pass",
                label_hi=lambda ctx: f"{ctx.max_passes} passes (log scale)",
                layer_name="GPS Density (log)",
            ),
            LegendRow(
                row_id="legend-pace-avg",
                title="Pace (average)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_speed_rgb"]),
                label_lo=lambda ctx: pace_str(ctx.normalized["s_lo"]),
                label_hi=lambda ctx: pace_str(ctx.normalized["s_hi"]),
                layer_name="Pace (average)",
            ),
            LegendRow(
                row_id="legend-heart-rate-avg",
                title="Heart rate (average)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_hr_rgb"]),
                label_lo=lambda ctx: f"{ctx.normalized['hr_lo']:.0f} bpm",
                label_hi=lambda ctx: f"{ctx.normalized['hr_hi']:.0f} bpm",
                layer_name="Heart rate (average)",
            ),
            LegendRow(
                row_id="legend-gradient",
                title="Gradient (absolute)",
                gradient="linear-gradient(to right, rgba(0,0,0,0), rgba(255,255,255,1))",
                label_lo=lambda ctx: f"{ctx.normalized['g_lo'] * 100:.1f}%",
                label_hi=lambda ctx: f"{ctx.normalized['g_hi'] * 100:.1f}% grade",
                layer_name="Gradient (absolute)",
            ),
            LegendRow(
                row_id="legend-elev-change",
                title="Gradient (change)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_elev_rgb"]),
                label_lo="descending",
                label_hi="ascending",
                layer_name="Gradient (change)",
            ),
        ]

    @property
    def legend_ids(self) -> dict[str, str]:
        """Map each bound layer name to its legend row DOM id (for dynamic visibility)."""
        return {row.layer_name: row.row_id for row in self.rows if row.layer_name}

    @property
    def exclusive_layer_names(self) -> list[str]:
        """Layer names that drive dynamic legend visibility."""
        return [row.layer_name for row in self.rows if row.layer_name]

    def container_style(self) -> str:
        """Return the inline style string for the legend container."""
        return build_style_string(self.styles)

    def build_rows(self, normalized: dict, colormaps: dict, max_passes: int) -> str:
        """Build all configured legend rows as HTML."""
        ctx = LegendContext(normalized=normalized, colormaps=colormaps, max_passes=max_passes)
        rows = [
            legend_row(
                row.row_id,
                row.title,
                _resolve(row.gradient, ctx),
                _resolve(row.label_lo, ctx),
                _resolve(row.label_hi, ctx),
                visible=row.visible,
            )
            for row in self.rows
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
