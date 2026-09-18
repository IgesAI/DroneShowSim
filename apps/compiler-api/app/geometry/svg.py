from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from svgpathtools import parse_path


@dataclass
class Sample:
    x: float
    y: float
    importance: float
    color: tuple[float, float, float]


NAMED = {
    "black": "#111111",
    "white": "#f4f1ea",
    "red": "#ff3b3b",
    "gold": "#f0c14b",
    "blue": "#3b82f6",
    "green": "#22c55e",
    "purple": "#a855f7",
    "pink": "#ec4899",
    "orange": "#f97316",
    "yellow": "#eab308",
    "cyan": "#22d3ee",
    "magenta": "#d946ef",
    "indigo": "#6366f1",
    "gray": "#9ca3af",
    "grey": "#9ca3af",
}

FALLBACK = (1.0, 0.85, 0.7)


def _hex_rgb(value: str | None) -> tuple[float, float, float] | None:
    if not value or value.lower() in {"none", "transparent", "inherit"}:
        return None
    value = value.strip()
    value = NAMED.get(value.lower(), value)
    rgb = re.match(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", value, re.I)
    if rgb:
        r, g, b = (float(rgb.group(1)), float(rgb.group(2)), float(rgb.group(3)))
        scale = 255.0 if max(r, g, b) > 1.0 else 1.0
        return (r / scale, g / scale, b / scale)
    m = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})", value)
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r / 255.0, g / 255.0, b / 255.0)


def _style_map(el: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in el.attrib.get("style", "").split(";"):
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        out[key.strip().lower()] = val.strip()
    return out


def _elem_color(el: ET.Element, inherited: tuple[float, float, float]) -> tuple[float, float, float]:
    style = _style_map(el)
    stroke = el.attrib.get("stroke") or style.get("stroke")
    fill = el.attrib.get("fill") or style.get("fill")
    return _hex_rgb(stroke) or _hex_rgb(fill) or inherited


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1].lower()


def _element_paths(
    el: ET.Element,
    inherited: tuple[float, float, float] = FALLBACK,
) -> list[tuple[str, tuple[float, float, float]]]:
    tag = _local_tag(el.tag)
    color = _elem_color(el, inherited)
    out: list[tuple[str, tuple[float, float, float]]] = []
    if tag == "path" and el.attrib.get("d"):
        out.append((el.attrib["d"], color))
    elif tag == "circle":
        cx, cy, r = float(el.attrib.get("cx", 0)), float(el.attrib.get("cy", 0)), float(el.attrib.get("r", 0))
        out.append((f"M {cx + r},{cy} A {r},{r} 0 1 1 {cx - r},{cy} A {r},{r} 0 1 1 {cx + r},{cy}", color))
    elif tag == "ellipse":
        cx, cy = float(el.attrib.get("cx", 0)), float(el.attrib.get("cy", 0))
        rx, ry = float(el.attrib.get("rx", 0)), float(el.attrib.get("ry", 0))
        out.append((f"M {cx + rx},{cy} A {rx},{ry} 0 1 1 {cx - rx},{cy} A {rx},{ry} 0 1 1 {cx + rx},{cy}", color))
    elif tag == "rect":
        x, y = float(el.attrib.get("x", 0)), float(el.attrib.get("y", 0))
        w, h = float(el.attrib.get("width", 0)), float(el.attrib.get("height", 0))
        out.append((f"M {x},{y} H {x + w} V {y + h} H {x} Z", color))
    elif tag == "line":
        x1, y1 = float(el.attrib.get("x1", 0)), float(el.attrib.get("y1", 0))
        x2, y2 = float(el.attrib.get("x2", 0)), float(el.attrib.get("y2", 0))
        out.append((f"M {x1},{y1} L {x2},{y2}", color))
    elif tag in {"polygon", "polyline"}:
        pts = el.attrib.get("points", "").strip()
        if pts:
            close = " Z" if tag == "polygon" else ""
            out.append((f"M {pts.replace(',', ' ')}{close}", color))
    for child in list(el):
        out.extend(_element_paths(child, color))
    return out


@dataclass
class Stroke:
    length: float
    color: tuple[float, float, float]
    # cumulative arc length, x, y
    knots: list[tuple[float, float, float]]


def _interp_stroke(stroke: Stroke, s: float) -> Sample:
    target = min(max(s, 0.0), stroke.length)
    lo, hi = 0, len(stroke.knots) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if stroke.knots[mid][0] < target:
            lo = mid + 1
        else:
            hi = mid
    i = max(1, lo)
    a = stroke.knots[i - 1]
    b = stroke.knots[i]
    span = max(b[0] - a[0], 1e-9)
    t = (target - a[0]) / span
    return Sample(a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, 1.0, stroke.color)


def _allocate(lengths: list[float], n: int) -> list[int]:
    m = len(lengths)
    if m == 0:
        return []
    total = sum(lengths) or 1.0
    raw = [n * L / total for L in lengths]
    floor_min = 1 if n >= m else 0
    counts = [max(floor_min, int(round(x))) for x in raw]
    while sum(counts) > n:
        candidates = [k for k in range(m) if counts[k] > floor_min]
        if not candidates:
            break
        i = max(candidates, key=lambda k: (counts[k] - raw[k], counts[k]))
        counts[i] -= 1
    while sum(counts) < n:
        i = max(range(m), key=lambda k: (raw[k] - counts[k], lengths[k]))
        counts[i] += 1
    return counts


def even_from_strokes(strokes: list[Stroke], count: int) -> list[Sample]:
    if not strokes:
        return [Sample(math.cos(2 * math.pi * i / max(count, 1)), math.sin(2 * math.pi * i / max(count, 1)), 1.0, FALLBACK) for i in range(count)]
    counts = _allocate([s.length for s in strokes], count)
    out: list[Sample] = []
    for stroke, k in zip(strokes, counts, strict=True):
        if k <= 0:
            continue
        for j in range(k):
            s = ((j + 0.5) / k) * stroke.length
            out.append(_interp_stroke(stroke, s))
    return out[:count]


def _path_stroke(d: str, color: tuple[float, float, float]) -> Stroke | None:
    try:
        path = parse_path(d)
    except Exception:
        return None
    steps = 96
    knots: list[tuple[float, float, float]] = []
    acc = 0.0
    prev = path.point(0)
    for i in range(steps + 1):
        p = path.point(i / steps)
        acc += abs(p - prev)
        knots.append((acc, float(p.real), float(p.imag)))
        prev = p
    if not math.isfinite(acc) or acc < 1e-4:
        return None
    return Stroke(length=acc, color=color, knots=knots)


def sample_svg(svg_text: str, candidate_count: int = 4000) -> list[Sample]:
    root = ET.fromstring(svg_text)
    samples: list[Sample] = []
    for d, color in _element_paths(root):
        try:
            path = parse_path(d)
        except Exception:
            continue
        length = path.length(error=1e-3)
        if not math.isfinite(length) or length < 1e-4:
            continue
        steps = max(32, int(length * 4))
        prev = path.point(0)
        for i in range(steps + 1):
            t = i / steps
            p = path.point(t)
            step = abs(p - prev)
            try:
                deriv2 = path.derivative(t, n=2)
                curv = abs(deriv2)
            except Exception:
                curv = 0.0
            importance = 1.0 + step + min(curv, 20.0) * 0.15
            samples.append(Sample(x=float(p.real), y=float(p.imag), importance=importance, color=color))
            prev = p
    if not samples:
        for i in range(candidate_count):
            a = 2 * math.pi * i / candidate_count
            samples.append(Sample(math.cos(a), math.sin(a), 1.0, (1.0, 0.85, 0.7)))
    return samples


def sample_svg_even(svg_text: str, count: int) -> list[Sample]:
    return even_from_strokes(_svg_strokes(svg_text), count)


def _svg_strokes(svg_text: str) -> list[Stroke]:
    root = ET.fromstring(svg_text)
    strokes: list[Stroke] = []
    for d, color in _element_paths(root):
        stroke = _path_stroke(d, color)
        if stroke:
            strokes.append(stroke)
    return strokes


def _stroke_endpoints(strokes: list[Stroke]) -> list[Sample]:
    out: list[Sample] = []
    for stroke in strokes:
        a = _interp_stroke(stroke, 0.0)
        b = _interp_stroke(stroke, stroke.length)
        out.append(Sample(a.x, a.y, 1.4, a.color))
        out.append(Sample(b.x, b.y, 1.4, b.color))
    return out


def sample_svg_with_corners(svg_text: str, count: int) -> list[Sample]:
    strokes = _svg_strokes(svg_text)
    return _stroke_endpoints(strokes) + even_from_strokes(strokes, max(count * 8, 64))


TEXT_STROKES: dict[str, list[tuple[float, float, float, float]]] = {
    "C": [(-0.35, 0.7, 0.35, 0.7), (-0.35, 0.7, -0.45, 0.0), (-0.45, 0.0, -0.35, -0.7), (-0.35, -0.7, 0.35, -0.7)],
    "O": [(-0.35, 0.7, 0.35, 0.7), (0.35, 0.7, 0.45, 0.0), (0.45, 0.0, 0.35, -0.7), (0.35, -0.7, -0.35, -0.7), (-0.35, -0.7, -0.45, 0.0), (-0.45, 0.0, -0.35, 0.7)],
    "B": [(-0.4, 0.7, -0.4, -0.7), (-0.4, 0.7, 0.25, 0.7), (0.25, 0.7, 0.35, 0.35), (0.35, 0.35, 0.2, 0.0), (0.2, 0.0, -0.4, 0.0), (0.2, 0.0, 0.38, -0.35), (0.38, -0.35, 0.25, -0.7), (0.25, -0.7, -0.4, -0.7)],
    "R": [(-0.4, 0.7, -0.4, -0.7), (-0.4, 0.7, 0.25, 0.7), (0.25, 0.7, 0.35, 0.3), (0.35, 0.3, 0.15, 0.0), (0.15, 0.0, -0.4, 0.0), (0.05, 0.0, 0.4, -0.7)],
    "A": [(-0.4, -0.7, 0.0, 0.7), (0.0, 0.7, 0.4, -0.7), (-0.22, -0.05, 0.22, -0.05)],
    "D": [(-0.4, 0.7, -0.4, -0.7), (-0.4, 0.7, 0.2, 0.7), (0.2, 0.7, 0.42, 0.0), (0.42, 0.0, 0.2, -0.7), (0.2, -0.7, -0.4, -0.7)],
    "S": [(0.35, 0.55, 0.2, 0.7), (0.2, 0.7, -0.3, 0.7), (-0.3, 0.7, -0.4, 0.25), (-0.4, 0.25, 0.3, -0.15), (0.3, -0.15, 0.35, -0.55), (0.35, -0.55, -0.2, -0.7), (-0.2, -0.7, -0.35, -0.5)],
    "H": [(-0.4, 0.7, -0.4, -0.7), (0.4, 0.7, 0.4, -0.7), (-0.4, 0.0, 0.4, 0.0)],
    "W": [(-0.5, 0.7, -0.28, -0.7), (-0.28, -0.7, 0.0, 0.15), (0.0, 0.15, 0.28, -0.7), (0.28, -0.7, 0.5, 0.7)],
    "E": [(-0.35, 0.7, -0.35, -0.7), (-0.35, 0.7, 0.4, 0.7), (-0.35, 0.0, 0.25, 0.0), (-0.35, -0.7, 0.4, -0.7)],
    "L": [(-0.35, 0.7, -0.35, -0.7), (-0.35, -0.7, 0.4, -0.7)],
    "I": [(0.0, 0.7, 0.0, -0.7), (-0.2, 0.7, 0.2, 0.7), (-0.2, -0.7, 0.2, -0.7)],
    "N": [(-0.4, -0.7, -0.4, 0.7), (-0.4, 0.7, 0.4, -0.7), (0.4, -0.7, 0.4, 0.7)],
    "T": [(-0.45, 0.7, 0.45, 0.7), (0.0, 0.7, 0.0, -0.7)],
    "M": [(-0.5, -0.7, -0.5, 0.7), (-0.5, 0.7, 0.0, -0.1), (0.0, -0.1, 0.5, 0.7), (0.5, 0.7, 0.5, -0.7)],
    "U": [(-0.4, 0.7, -0.4, -0.35), (-0.4, -0.35, 0.0, -0.7), (0.0, -0.7, 0.4, -0.35), (0.4, -0.35, 0.4, 0.7)],
    "P": [(-0.4, -0.7, -0.4, 0.7), (-0.4, 0.7, 0.25, 0.7), (0.25, 0.7, 0.35, 0.25), (0.35, 0.25, -0.4, 0.05)],
    "G": [(0.3, 0.55, -0.1, 0.7), (-0.1, 0.7, -0.4, 0.2), (-0.4, 0.2, -0.3, -0.6), (-0.3, -0.6, 0.25, -0.7), (0.25, -0.7, 0.4, -0.15), (0.4, -0.15, 0.05, -0.15)],
}


def sample_text(text: str, candidate_count: int = 3000) -> list[Sample]:
    letters = [ch for ch in text.upper() if ch in TEXT_STROKES or ch == " "]
    if not letters:
        letters = list("COBRA")
    samples: list[Sample] = []
    cursor = 0.0
    for ch in letters:
        if ch == " ":
            cursor += 0.7
            continue
        strokes = TEXT_STROKES[ch]
        for x1, y1, x2, y2 in strokes:
            segs = 18
            for i in range(segs + 1):
                t = i / segs
                # Glyph table is Y-up; emit SVG Y-down so fit_points' SVG flip stands letters upright.
                samples.append(Sample(cursor + x1 + (x2 - x1) * t, -(y1 + (y2 - y1) * t), 1.4, (1, 0.85, 0.7)))
        cursor += 1.15
    return samples


def _text_strokes(text: str) -> list[Stroke]:
    letters = [ch for ch in text.upper() if ch in TEXT_STROKES or ch == " "]
    if not letters:
        letters = list("COBRA")
    strokes: list[Stroke] = []
    cursor = 0.0
    for ch in letters:
        if ch == " ":
            cursor += 0.7
            continue
        for x1, y1, x2, y2 in TEXT_STROKES[ch]:
            dx, dy = (x2 - x1), (y2 - y1)
            length = math.hypot(dx, dy) or 1e-3
            knots = [
                (0.0, cursor + x1, -y1),
                (length, cursor + x2, -y2),
            ]
            strokes.append(Stroke(length=length, color=(1.0, 0.85, 0.7), knots=knots))
        cursor += 1.15
    return strokes


def sample_text_even(text: str, count: int) -> list[Sample]:
    return even_from_strokes(_text_strokes(text), count)


def sample_text_with_corners(text: str, count: int) -> list[Sample]:
    strokes = _text_strokes(text)
    return _stroke_endpoints(strokes) + even_from_strokes(strokes, max(count * 8, 64))
