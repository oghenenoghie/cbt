"""Validated, source-reviewed diagram specifications used by question versions."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DiagramKind = Literal["rect", "ellipse", "line", "arrow", "region", "text"]
_COLOR = re.compile(r"^(?:#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|none)$")


class DiagramElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: DiagramKind
    x: float = Field(ge=0, le=4096, allow_inf_nan=False)
    y: float = Field(ge=0, le=4096, allow_inf_nan=False)
    label: str | None = Field(default=None, max_length=500)
    width: float | None = Field(default=None, gt=0, le=4096, allow_inf_nan=False)
    height: float | None = Field(default=None, gt=0, le=4096, allow_inf_nan=False)
    x2: float | None = Field(default=None, ge=0, le=4096, allow_inf_nan=False)
    y2: float | None = Field(default=None, ge=0, le=4096, allow_inf_nan=False)
    fill: str = Field(default="none", pattern=_COLOR.pattern)
    stroke: str = Field(default="#1f2937", pattern=_COLOR.pattern)
    stroke_width: float = Field(default=2, ge=0, le=64, allow_inf_nan=False)
    font_size: float = Field(default=16, ge=1, le=256, allow_inf_nan=False)

    @model_validator(mode="after")
    def _fields_for_kind(self) -> "DiagramElement":
        if self.kind in {"rect", "ellipse", "region"}:
            if self.width is None or self.height is None:
                raise ValueError(f"{self.kind} elements need width and height")
        elif self.kind in {"line", "arrow"}:
            if self.x2 is None or self.y2 is None:
                raise ValueError(f"{self.kind} elements need x2 and y2")
        elif self.kind == "text":
            if self.label is None or not self.label.strip():
                raise ValueError("text elements need a label")

        if self.kind != "text" and self.label is not None:
            raise ValueError("labels must use a text element")
        return self


class DiagramSpec(BaseModel):
    """A bounded canvas with explicit primitives; arbitrary SVG is never accepted."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=4096)
    elements: list[DiagramElement] = Field(max_length=500)

    @model_validator(mode="after")
    def _elements_fit_canvas(self) -> "DiagramSpec":
        for element in self.elements:
            if element.x > self.width or element.y > self.height:
                raise ValueError("element positions must be inside the canvas")
            if element.kind in {"rect", "ellipse", "region"} and (
                element.x + element.width > self.width or element.y + element.height > self.height
            ):
                raise ValueError("element dimensions must fit inside the canvas")
            if element.kind in {"line", "arrow"} and (
                element.x2 > self.width or element.y2 > self.height
            ):
                raise ValueError("line end positions must be inside the canvas")
        return self


def student_diagram(spec: dict | None) -> dict | None:
    """Return a candidate-safe blank variant, removing labels and answer-like descriptions."""
    if spec is None:
        return None
    return {
        "title": "Question diagram",
        "description": "Unlabelled diagram for this question.",
        "width": spec["width"],
        "height": spec["height"],
        "elements": [element for element in spec["elements"] if element["kind"] != "text"],
    }
