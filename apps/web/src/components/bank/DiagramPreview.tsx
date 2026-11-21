"use client";

import { useId } from "react";

import type { DiagramElement, DiagramSpec } from "@/lib/types";

function validColor(value: string | undefined, fallback: string): string {
  return value && /^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|none)$/.test(value)
    ? value
    : fallback;
}

/** Render the question's structured drawing. Blank mode hides all text labels for candidates. */
export function DiagramPreview({
  spec,
  labelled = true,
}: {
  spec?: DiagramSpec | null;
  labelled?: boolean;
}) {
  const rawId = useId();
  if (!spec || !Number.isFinite(spec.width) || !Number.isFinite(spec.height)) return null;
  const markerId = `diagram-arrow-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  function element(node: DiagramElement, index: number) {
    const stroke = validColor(node.stroke, "#1f2937");
    const fill = validColor(node.fill, "none");
    const common = { key: index, stroke, strokeWidth: node.stroke_width ?? 2, fill };
    if (node.kind === "text") {
      return labelled && node.label ? (
        <text key={index} x={node.x} y={node.y} fill={stroke} fontSize={node.font_size ?? 16}>
          {node.label}
        </text>
      ) : null;
    }
    if (["rect", "region"].includes(node.kind)) {
      return <rect {...common} x={node.x} y={node.y} width={node.width} height={node.height} />;
    }
    if (node.kind === "ellipse") {
      return (
        <ellipse
          {...common}
          cx={node.x + (node.width ?? 0) / 2}
          cy={node.y + (node.height ?? 0) / 2}
          rx={(node.width ?? 0) / 2}
          ry={(node.height ?? 0) / 2}
        />
      );
    }
    return (
      <line
        key={index}
        x1={node.x}
        y1={node.y}
        x2={node.x2}
        y2={node.y2}
        stroke={stroke}
        strokeWidth={node.stroke_width ?? 2}
        markerEnd={node.kind === "arrow" ? `url(#${markerId})` : undefined}
      />
    );
  }

  return (
    <figure style={{ margin: "12px 0", maxWidth: "100%" }}>
      <svg
        role="img"
        aria-label={labelled ? spec.title : "Unlabelled question diagram"}
        viewBox={`0 0 ${spec.width} ${spec.height}`}
        style={{ display: "block", width: "100%", maxHeight: 420, border: "1px solid var(--border)", borderRadius: 8 }}
      >
        <defs>
          <marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#1f2937" />
          </marker>
        </defs>
        {spec.elements.map(element)}
      </svg>
      {labelled && <figcaption className="hint">{spec.description}</figcaption>}
    </figure>
  );
}
