"""
Utility functions for the map_builder package.

Contains helper functions like colormap-to-CSS conversion that are shared
across the legend and control modules.
"""


def cmap_to_css(cmap, n=14) -> str:
    """Convert colormap to CSS linear-gradient string."""
    stops = []
    for i in range(n):
        t = i / (n - 1)
        r, g, b, a = cmap(t)
        stops.append(f"rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},{a:.2f})")
    return f"linear-gradient(to right, {', '.join(stops)})"


def build_style_string(styles: dict[str, str]) -> str:
    """Convert a dictionary of CSS properties to an inline style string."""
    return "; ".join(f"{key}:{value}" for key, value in styles.items())
