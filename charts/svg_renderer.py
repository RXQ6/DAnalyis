"""Render a validated chart specification as deterministic SVG."""

from __future__ import annotations

import hashlib
import html
import math
import re
from pathlib import Path
from typing import Any


WIDTH = 800
HEIGHT = 480
MARGIN_LEFT = 72
MARGIN_RIGHT = 28
MARGIN_TOP = 64
MARGIN_BOTTOM = 88


def render_svg(
    spec: dict[str, Any], *, artifact_dir: str | Path, artifact_name: str
) -> dict[str, Any]:
    """Render one validated bar or line spec into a controlled directory."""
    root = Path(artifact_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", artifact_name).strip("._-")
    if not safe_name:
        safe_name = "chart"
    target = (root / f"{safe_name}.svg").resolve()
    if target.parent != root:
        raise ValueError("chart artifact path escaped the controlled directory")

    svg = _svg_document(spec)
    target.write_text(svg, encoding="utf-8")
    return {
        "path": str(target),
        "mediaType": "image/svg+xml",
        "width": WIDTH,
        "height": HEIGHT,
        "sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(),
    }


def _svg_document(spec: dict[str, Any]) -> str:
    chart_type = spec["chartType"]
    values = spec["data"]["values"]
    y_values = [item["y"] for item in values]
    minimum = min(0, min(y_values))
    maximum = max(0, max(y_values))
    if math.isclose(minimum, maximum):
        maximum = minimum + 1

    plot_width = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    plot_height = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    def y_position(value: float) -> float:
        return MARGIN_TOP + (maximum - value) * plot_height / (maximum - minimum)

    baseline = y_position(0)
    x_values = [item["x"] for item in values] if chart_type == "scatter" else []
    x_minimum = min(x_values) if x_values else 0
    x_maximum = max(x_values) if x_values else 1
    if math.isclose(x_minimum, x_maximum):
        x_maximum = x_minimum + 1

    def x_position(value: float) -> float:
        return MARGIN_LEFT + (value - x_minimum) * plot_width / (x_maximum - x_minimum)

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{WIDTH / 2:g}" y="32" text-anchor="middle" font-family="sans-serif" font-size="20">{_escape(spec["title"])}</text>',
        f'<line x1="{MARGIN_LEFT}" y1="{MARGIN_TOP}" x2="{MARGIN_LEFT}" y2="{HEIGHT - MARGIN_BOTTOM}" stroke="#475569"/>',
        f'<line x1="{MARGIN_LEFT}" y1="{baseline:.3f}" x2="{WIDTH - MARGIN_RIGHT}" y2="{baseline:.3f}" stroke="#475569"/>',
    ]
    elements.extend(_y_ticks(minimum, maximum, y_position))
    if chart_type == "bar":
        elements.extend(_bars(values, plot_width, baseline, y_position))
    elif chart_type == "line":
        elements.extend(_line(values, plot_width, y_position))
    elif chart_type == "scatter":
        elements.extend(_scatter(values, x_position, y_position))
    else:
        raise ValueError(f"unsupported chart type: {chart_type}")
    elements.extend(
        [
            f'<text x="{WIDTH / 2:g}" y="{HEIGHT - 18}" text-anchor="middle" font-family="sans-serif" font-size="13">{_escape(spec["encoding"]["x"]["title"])}</text>',
            f'<text x="18" y="{HEIGHT / 2:g}" text-anchor="middle" font-family="sans-serif" font-size="13" transform="rotate(-90 18 {HEIGHT / 2:g})">{_escape(spec["encoding"]["y"]["title"])}</text>',
            "</svg>",
        ]
    )
    return "\n".join(elements) + "\n"


def _bars(
    values: list[dict[str, Any]],
    plot_width: float,
    baseline: float,
    y_position: Any,
) -> list[str]:
    slot = plot_width / len(values)
    bar_width = max(1.0, slot * 0.72)
    output = []
    for index, item in enumerate(values):
        center = MARGIN_LEFT + slot * (index + 0.5)
        value_y = y_position(item["y"])
        top = min(value_y, baseline)
        height = max(1.0, abs(baseline - value_y))
        output.append(
            f'<rect x="{center - bar_width / 2:.3f}" y="{top:.3f}" width="{bar_width:.3f}" height="{height:.3f}" fill="#2563eb"><title>{_escape(item["x"])}: {_number(item["y"])}</title></rect>'
        )
        output.extend(_x_label(center, item["x"], index, len(values)))
    return output


def _line(
    values: list[dict[str, Any]], plot_width: float, y_position: Any
) -> list[str]:
    step = plot_width / max(1, len(values) - 1)
    points = [
        (MARGIN_LEFT + step * index, y_position(item["y"]))
        for index, item in enumerate(values)
    ]
    coordinates = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
    output = [
        f'<polyline points="{coordinates}" fill="none" stroke="#2563eb" stroke-width="2.5"/>'
    ]
    for index, (item, (x, y)) in enumerate(zip(values, points, strict=True)):
        output.append(
            f'<circle cx="{x:.3f}" cy="{y:.3f}" r="3.5" fill="#1d4ed8"><title>{_escape(item["x"])}: {_number(item["y"])}</title></circle>'
        )
        output.extend(_x_label(x, item["x"], index, len(values)))
    return output


def _scatter(values: list[dict[str, Any]], x_position: Any, y_position: Any) -> list[str]:
    return [
        f'<circle cx="{x_position(item["x"]):.3f}" cy="{y_position(item["y"]):.3f}" r="4" fill="#2563eb"><title>{_number(item["x"])}: {_number(item["y"])}</title></circle>'
        for item in values
    ]


def _x_label(x: float, label: Any, index: int, count: int) -> list[str]:
    every = max(1, math.ceil(count / 12))
    if index % every and index != count - 1:
        return []
    return [
        f'<text x="{x:.3f}" y="{HEIGHT - MARGIN_BOTTOM + 18}" text-anchor="end" font-family="sans-serif" font-size="11" transform="rotate(-35 {x:.3f} {HEIGHT - MARGIN_BOTTOM + 18})">{_escape(label)}</text>'
    ]


def _y_ticks(minimum: float, maximum: float, y_position: Any) -> list[str]:
    output = []
    for index in range(6):
        value = minimum + (maximum - minimum) * index / 5
        y = y_position(value)
        output.append(
            f'<line x1="{MARGIN_LEFT}" y1="{y:.3f}" x2="{WIDTH - MARGIN_RIGHT}" y2="{y:.3f}" stroke="#e2e8f0"/>'
        )
        output.append(
            f'<text x="{MARGIN_LEFT - 8}" y="{y + 4:.3f}" text-anchor="end" font-family="sans-serif" font-size="11">{_number(value)}</text>'
        )
    return output


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.12g}"
