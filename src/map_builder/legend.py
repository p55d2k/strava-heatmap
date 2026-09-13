"""
Legend generation for the heatmap.

This module provides functions and classes to generate the legend HTML,
including individual legend rows and the complete legend container. The markup
is rendered from the external ``assets/legend_row.html`` and
``assets/legend_container.html`` templates, and styled by the shared
``assets/panel.css`` so it stays consistent with the control panel.

Rows are fully configurable: build your own ``LegendRow`` definitions (or start
from ``LegendBuilder.default_rows``) and pass them to ``LegendBuilder``. Each
row can be bound to a map overlay layer name; the builder then exposes
``legend_ids`` / ``exclusive_layer_names`` so the dynamic layer control can
show/hide the correct legend row.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from string import Template

from src.map_builder.constants import (
    DECAY_STRATEGIES,
    DECAY_STRATEGY_SHORT,
    density_layer_names,
)
from src.map_builder.utils import build_style_string, cmap_to_css

_ASSETS_DIR = Path(__file__).parent / "assets"
_ROW_TEMPLATE = Template((_ASSETS_DIR / "legend_row.html").read_text(encoding="utf-8"))
_CONTAINER_TEMPLATE = Template((_ASSETS_DIR / "legend_container.html").read_text(encoding="utf-8"))


def pace_str(ms: float) -> str:
    """Convert m/s to pace string (min:sec/km)."""
    secs = 1000 / ms
    return f"{int(secs // 60)}:{int(secs % 60):02d}/km"


def legend_row(
    row_id: str, title: str, grad_css: str, label_lo: str, label_hi: str, visible: bool = False
) -> str:
    """Generate HTML for a legend row."""
    display = "block" if visible else "none"
    return _ROW_TEMPLATE.substitute(
        row_id=row_id,
        display=display,
        title=title,
        grad_css=grad_css,
        label_lo=label_lo,
        label_hi=label_hi,
    )


@dataclass(frozen=True)
class LegendContext:
    """Build-time data passed to callable legend row fields.

    Callables may use any of these to compute dynamic labels or gradients.
    """

    normalized: dict
    colormaps: dict
    max_passes: int
    max_passes_by_strategy: dict[str, int] | None = None


def _resolve(value, ctx: LegendContext):
    """Return ``value`` resolved against ``ctx`` if it is a callable."""
    return value(ctx) if callable(value) else value


def _max_passes(ctx: LegendContext, strategy: str) -> int:
    """Return the max-pass legend count for a strategy, with a backward-compatible fallback."""
    by_strategy = ctx.max_passes_by_strategy
    if by_strategy and strategy in by_strategy:
        return by_strategy[strategy]
    return ctx.max_passes


@dataclass(frozen=True)
class LegendRow:
    """Configuration for a single legend row.

    Each display field (``gradient``, ``label_lo``, ``label_hi``) may be a plain
    value or a callable taking a :class:`LegendContext` and returning a string.
    ``row_id`` must be present in the built HTML so that the dynamic layer
    control can locate and show/hide the row.

    ``layer_name`` optionally links the row to the map overlay layer that drives
    its visibility via ``ExclusiveLayerControl``.
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

    By default the container is styled by the shared ``.hcp-legend`` class. Pass
    ``styles`` to override (e.g. the legacy ``DEFAULT_LEGEND_STYLES`` dict) as a
    custom inline ``style`` attribute.
    """

    def __init__(
        self,
        styles: dict[str, str] | None = None,
        rows: list[LegendRow] | None = None,
    ):
        self.styles = dict(styles) if styles is not None else {}
        self.rows = list(rows) if rows is not None else self.default_rows()

    def default_rows(self) -> list[LegendRow]:
        """Return the default legend row definitions (configurable starting point)."""
        rows: list[LegendRow] = []
        # One linear + log legend row per decay strategy.
        for strategy in DECAY_STRATEGIES:
            linear_name, log_name = density_layer_names(strategy)
            short = DECAY_STRATEGY_SHORT[strategy]
            linear_id = f"legend-frequency-{short}"
            log_id = f"{linear_id}-log"

            def _hi(ctx: LegendContext, _s: str = strategy, _log: bool = False) -> str:
                n = _max_passes(ctx, _s)
                return f"{n} passes (log scale)" if _log else f"{n} passes"

            rows.append(
                LegendRow(
                    row_id=linear_id,
                    title=linear_name,
                    gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_count"]),
                    label_lo="1 pass",
                    label_hi=lambda ctx, _s=strategy: _hi(ctx, _s),
                    visible=True,
                    layer_name=linear_name,
                )
            )
            rows.append(
                LegendRow(
                    row_id=log_id,
                    title=log_name,
                    gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_count"]),
                    label_lo="1 pass",
                    label_hi=lambda ctx, _s=strategy: _hi(ctx, _s, _log=True),
                    layer_name=log_name,
                )
            )

        rows.append(
            LegendRow(
                row_id="legend-pace-avg",
                title="Pace (average)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_speed_rgb"]),
                label_lo=lambda ctx: pace_str(ctx.normalized["s_lo"]),
                label_hi=lambda ctx: pace_str(ctx.normalized["s_hi"]),
                layer_name="Pace (average)",
            )
        )
        rows.append(
            LegendRow(
                row_id="legend-heart-rate-avg",
                title="Heart rate (average)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_hr_rgb"]),
                label_lo=lambda ctx: f"{ctx.normalized['hr_lo']:.0f} bpm",
                label_hi=lambda ctx: f"{ctx.normalized['hr_hi']:.0f} bpm",
                layer_name="Heart rate (average)",
            )
        )
        rows.append(
            LegendRow(
                row_id="legend-gradient",
                title="Gradient (absolute)",
                gradient="linear-gradient(to right, rgba(0,0,0,0), rgba(255,255,255,1))",
                label_lo=lambda ctx: f"{ctx.normalized['g_lo'] * 100:.1f}%",
                label_hi=lambda ctx: f"{ctx.normalized['g_hi'] * 100:.1f}% grade",
                layer_name="Gradient (absolute)",
            )
        )
        rows.append(
            LegendRow(
                row_id="legend-elev-change",
                title="Gradient (change)",
                gradient=lambda ctx: cmap_to_css(ctx.colormaps["cmap_elev_rgb"]),
                label_lo="descending",
                label_hi="ascending",
                layer_name="Gradient (change)",
            )
        )
        return rows

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

    def build_rows(
        self,
        normalized: dict,
        colormaps: dict,
        max_passes: int,
        max_passes_by_strategy: dict[str, int] | None = None,
    ) -> str:
        """Build all configured legend rows as HTML."""
        ctx = LegendContext(
            normalized=normalized,
            colormaps=colormaps,
            max_passes=max_passes,
            max_passes_by_strategy=max_passes_by_strategy,
        )
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

    def build(
        self,
        normalized: dict,
        colormaps: dict,
        max_passes: int,
        max_passes_by_strategy: dict[str, int] | None = None,
    ) -> str:
        """Build the complete legend HTML."""
        rows = self.build_rows(normalized, colormaps, max_passes, max_passes_by_strategy)
        style_attr = f' style="{self.container_style()}"' if self.styles else ""
        return _CONTAINER_TEMPLATE.substitute(rows=rows, style_attr=style_attr)


def build_legend_html(
    normalized: dict,
    colormaps: dict,
    max_passes: int,
    max_passes_by_strategy: dict[str, int] | None = None,
) -> str:
    """Build the complete legend HTML using the default LegendBuilder."""
    return LegendBuilder().build(normalized, colormaps, max_passes, max_passes_by_strategy)
