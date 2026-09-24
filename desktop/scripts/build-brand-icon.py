"""Build a Windows ICO from the simple geometry in assets/brand/mark.svg.

This stdlib-only exporter supports the current rect/polygon placeholder. Replace
the SVG and exporter together when final artwork is approved.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "brand" / "mark.svg"
TARGET = ROOT / "assets" / "brand" / "icon.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def color(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def inside_polygon(x: float, y: float, points: list[tuple[float, float]]) -> bool:
    inside = False
    previous = points[-1]
    for point in points:
        x1, y1 = previous
        x2, y2 = point
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = point
    return inside


def inside_rounded_rect(x: float, y: float, shape: dict[str, float]) -> bool:
    left, top, width, height, radius = (shape[key] for key in ("x", "y", "width", "height", "rx"))
    if not (left <= x <= left + width and top <= y <= top + height):
        return False
    corner_x = min(max(x, left + radius), left + width - radius)
    corner_y = min(max(y, top + radius), top + height - radius)
    return (x - corner_x) ** 2 + (y - corner_y) ** 2 <= radius**2


def shapes() -> list[tuple[str, object, tuple[int, int, int]]]:
    root = ET.parse(SOURCE).getroot()
    output: list[tuple[str, object, tuple[int, int, int]]] = []
    for element in root:
        tag = element.tag.rsplit("}", 1)[-1]
        fill = color(element.attrib["fill"])
        if tag == "rect":
            output.append((tag, {key: float(element.attrib[key]) for key in ("x", "y", "width", "height", "rx")}, fill))
        elif tag == "polygon":
            points = [tuple(map(float, pair.split(","))) for pair in element.attrib["points"].split()]
            output.append((tag, points, fill))
        else:
            raise ValueError(f"Unsupported icon shape: {tag}")
    return output


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def render_png(size: int, artwork: list[tuple[str, object, tuple[int, int, int]]]) -> bytes:
    samples = 4 if size <= 48 else 2
    rows: list[bytes] = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            channels = [0, 0, 0, 0]
            for sy in range(samples):
                for sx in range(samples):
                    x = (px + (sx + 0.5) / samples) * 256 / size
                    y = (py + (sy + 0.5) / samples) * 256 / size
                    visible: tuple[int, int, int] | None = None
                    for kind, geometry, fill in artwork:
                        if kind == "rect" and inside_rounded_rect(x, y, geometry):
                            visible = fill
                        elif kind == "polygon" and inside_polygon(x, y, geometry):
                            visible = fill
                    if visible is not None:
                        for channel in range(3):
                            channels[channel] += visible[channel]
                        channels[3] += 255
            count = samples * samples
            row.extend(round(channel / count) for channel in channels)
        rows.append(bytes(row))
    pixels = zlib.compress(b"".join(rows), level=9)
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0)) + png_chunk(b"IDAT", pixels) + png_chunk(b"IEND", b"")


def main() -> None:
    artwork = shapes()
    images = [render_png(size, artwork) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = len(header) + 16 * len(SIZES)
    entries = []
    for size, data in zip(SIZES, images):
        entries.append(struct.pack("<BBBBHHII", size if size < 256 else 0, size if size < 256 else 0, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    TARGET.write_bytes(header + b"".join(entries) + b"".join(images))
    print(TARGET)


if __name__ == "__main__":
    main()
