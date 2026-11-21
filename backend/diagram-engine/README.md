# Diagram and Sketch Engine

Create accurate, reproducible and editable assessment visuals.

Preferred outputs:
- SVG diagrams with structured labels, arrows, callouts and regions;
- programmatic charts and graphs from validated data;
- question-specific blank/labelled variants;
- accessible text descriptions and alternative text.

The engine receives a validated diagram specification grounded in approved learning material. Scientific labels and relationships must be checked against source evidence. Generative image models are optional for illustrative assets, not a substitute for precise technical diagrams.

## Current implementation

The standalone `diagram_engine` Python package renders bounded structured SVG primitives and
creates labelled and blank variants. The API now stores these structured specifications on
immutable question versions, shows labelled and blank previews in the teacher question editor,
and returns a sanitized unlabelled diagram to student exam, review and offline-package payloads.
AI drafts can include structured diagrams; text labels must be found in the cited learning material
before a draft passes review. The student web and offline desktop apps render the blank form. Keep
specifications as structured data; never accept raw SVG markup.

Import it by adding this directory to `PYTHONPATH`:

```python
from diagram_engine import DiagramElement, DiagramSpec, render_svg

spec = DiagramSpec(
    title="Cell outline",
    description="A teacher-reviewed cell diagram.",
    width=320,
    height=220,
    elements=(
        DiagramElement("ellipse", 40, 30, width=240, height=160, fill="#ecfeff"),
        DiagramElement(
            "region", 100, 80, width=48, height=32, fill="#fef3c7", stroke="#b91c1c"
        ),
        DiagramElement("arrow", 300, 48, x2=245, y2=72, stroke="#0f766e"),
        DiagramElement("text", 110, 118, label="Cell membrane"),
    ),
)
labelled_svg = render_svg(spec)
blank_svg = render_svg(spec, labelled=False)
```
