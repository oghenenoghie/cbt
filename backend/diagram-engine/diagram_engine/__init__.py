"""Deterministic SVG rendering for assessment diagrams.

This package accepts a small, explicit specification instead of arbitrary SVG or HTML. Callers
should only create specifications from reviewed source material.
"""

from dataclasses import dataclass
from html import escape
import math
import re

__all__ = ["DiagramElement", "DiagramSpec", "render_svg"]

_COLOR = re.compile(r"^(?:#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|none)$")
_KINDS = {"rect", "ellipse", "line", "arrow", "region", "text"}


@dataclass(frozen=True)
class DiagramElement:
    """One basic SVG primitive. Text elements are omitted in the blank variant."""

    kind: str
    x: float
    y: float
    label: str | None = None
    width: float | None = None
    height: float | None = None
    x2: float | None = None
    y2: float | None = None
    fill: str = "none"
    stroke: str = "#1f2937"
    stroke_width: float = 2
    font_size: float = 16


@dataclass(frozen=True)
class DiagramSpec:
    """A versionable canvas and its explicitly positioned elements."""

    title: str
    description: str
    width: int
    height: int
    elements: tuple[DiagramElement, ...]


def _number(value: float | int | None, name: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _color(value: str, name: str) -> str:
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        raise ValueError(f"{name} must be a hexadecimal color or 'none'")
    return value


def _validate(spec: DiagramSpec) -> None:
    if not isinstance(spec.title, str) or not spec.title.strip():
        raise ValueError("title must not be empty")
    if not isinstance(spec.description, str) or not spec.description.strip():
        raise ValueError("description must not be empty")
    if isinstance(spec.width, bool) or not isinstance(spec.width, int) or not 1 <= spec.width <= 4096:
        raise ValueError("width must be an integer from 1 to 4096")
    if isinstance(spec.height, bool) or not isinstance(spec.height, int) or not 1 <= spec.height <= 4096:
        raise ValueError("height must be an integer from 1 to 4096")
    if len(spec.elements) > 500:
        raise ValueError("a diagram may contain at most 500 elements")

    for index, element in enumerate(spec.elements):
        name = f"elements[{index}]"
        if element.kind not in _KINDS:
            raise ValueError(f"{name}.kind must be one of {', '.join(sorted(_KINDS))}")
        x = _number(element.x, f"{name}.x")
        y = _number(element.y, f"{name}.y")
        if not 0 <= x <= spec.width or not 0 <= y <= spec.height:
            raise ValueError(f"{name} position must be inside the canvas")
        _color(element.fill, f"{name}.fill")
        _color(element.stroke, f"{name}.stroke")
        stroke_width = _number(element.stroke_width, f"{name}.stroke_width")
        if stroke_width < 0 or stroke_width > 64:
            raise ValueError(f"{name}.stroke_width must be from 0 to 64")
        if element.label is not None and not isinstance(element.label, str):
            raise ValueError(f"{name}.label must be text or null")

        if element.kind in {"rect", "ellipse", "region"}:
            width = _number(element.width, f"{name}.width")
            height = _number(element.height, f"{name}.height")
            if width <= 0 or height <= 0 or x + width > spec.width or y + height > spec.height:
                raise ValueError(f"{name} dimensions must be positive and fit inside the canvas")
        elif element.kind in {"line", "arrow"}:
            x2 = _number(element.x2, f"{name}.x2")
            y2 = _number(element.y2, f"{name}.y2")
            if not 0 <= x2 <= spec.width or not 0 <= y2 <= spec.height:
                raise ValueError(f"{name} end position must be inside the canvas")
        elif element.kind == "text":
            if not element.label or not element.label.strip():
                raise ValueError(f"{name}.label is required for text elements")
            font_size = _number(element.font_size, f"{name}.font_size")
            if not 1 <= font_size <= 256:
                raise ValueError(f"{name}.font_size must be from 1 to 256")


def render_svg(spec: DiagramSpec, *, labelled: bool = True) -> str:
    """Render a labelled or blank SVG from a validated diagram specification."""

    _validate(spec)
    elements: list[str] = []
    arrow_colors = sorted({element.stroke for element in spec.elements if element.kind == "arrow"})
    arrow_ids = {color: f"arrowhead-{index}" for index, color in enumerate(arrow_colors)}
    for element in spec.elements:
        if element.kind == "text" and not labelled:
            continue
        fill = _color(element.fill, "fill")
        stroke = _color(element.stroke, "stroke")
        stroke_width = _number(element.stroke_width, "stroke_width")
        common = f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width:g}"'

        if element.kind == "rect":
            width = _number(element.width, "width")
            height = _number(element.height, "height")
            elements.append(
                f'<rect x="{element.x:g}" y="{element.y:g}" width="{width:g}" '
                f'height="{height:g}" {common}/>'
            )
        elif element.kind == "region":
            width = _number(element.width, "width")
            height = _number(element.height, "height")
            elements.append(
                f'<rect x="{element.x:g}" y="{element.y:g}" width="{width:g}" '
                f'height="{height:g}" {common} stroke-dasharray="6 4" fill-opacity="0.12"/>'
            )
        elif element.kind == "ellipse":
            width = _number(element.width, "width")
            height = _number(element.height, "height")
            elements.append(
                f'<ellipse cx="{element.x + width / 2:g}" cy="{element.y + height / 2:g}" '
                f'rx="{width / 2:g}" ry="{height / 2:g}" {common}/>'
            )
        elif element.kind in {"line", "arrow"}:
            marker = (
                f' marker-end="url(#{arrow_ids[stroke]})"' if element.kind == "arrow" else ""
            )
            elements.append(
                f'<line x1="{element.x:g}" y1="{element.y:g}" '
                f'x2="{element.x2:g}" y2="{element.y2:g}" {common}{marker}/>'
            )
        else:
            font_size = _number(element.font_size, "font_size")
            elements.append(
                f'<text x="{element.x:g}" y="{element.y:g}" fill="{stroke}" '
                f'font-size="{font_size:g}" font-family="sans-serif">'
                f'{escape(element.label or "")}</text>'
            )

    title = escape(spec.title)
    description = escape(spec.description)
    body = "".join(elements)
    arrow_defs = "".join(
        f'<marker id="{arrow_ids[color]}" markerWidth="8" markerHeight="8" '
        f'refX="7" refY="4" orient="auto" markerUnits="strokeWidth">'
        f'<path d="M0,0 L8,4 L0,8 z" fill="{color}"/></marker>'
        for color in arrow_colors
    )
    defs = f"<defs>{arrow_defs}</defs>" if arrow_defs else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'viewBox="0 0 {spec.width} {spec.height}" width="{spec.width}" height="{spec.height}">'
        f"<title>{title}</title><desc>{description}</desc>{defs}{body}</svg>"
    )
