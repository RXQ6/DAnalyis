"""Deterministic chart specification and rendering helpers."""

from .spec import ChartSpecError, build_chart_spec
from .svg_renderer import render_svg

__all__ = ["ChartSpecError", "build_chart_spec", "render_svg"]
