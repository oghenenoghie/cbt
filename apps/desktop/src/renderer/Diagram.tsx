import { useId } from "react";

import type { DiagramElement, DiagramSpec } from "../shared/api";

function color(value: string | undefined, fallback: string): string {
  return value && /^(#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8}|none)$/.test(value)
    ? value
    : fallback;
}

/** Candidate-safe SVG rendering. Diagram packages are label-stripped by the server as well. */
export function Diagram({ spec, numberedTargets = false }: { spec?: DiagramSpec | null; numberedTargets?: boolean }) {
  const rawId = useId();
  if (
    !spec || !Number.isInteger(spec.width) || spec.width < 1 || spec.width > 4096 ||
    !Number.isInteger(spec.height) || spec.height < 1 || spec.height > 4096 ||
    !Array.isArray(spec.elements)
  ) return null;
  const markerId = `lab-arrow-${rawId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  function shape(node: DiagramElement, index: number) {
    if (!node || (node.kind === "text" && !numberedTargets) || !Number.isFinite(node.x) || !Number.isFinite(node.y)) return null;
    const stroke = color(node.stroke, "#1f2937");
    const fill = color(node.fill, "none");
    const strokeWidth = node.stroke_width != null && Number.isFinite(node.stroke_width)
      ? node.stroke_width
      : 2;
    if (node.kind === "text") {
      return <text key={index} x={node.x} y={node.y} fill={stroke} fontSize={node.font_size ?? 16} fontWeight="bold">{node.label}</text>;
    }
    if (node.kind === "rect" || node.kind === "region") {
      return <rect key={index} x={node.x} y={node.y} width={node.width} height={node.height} stroke={stroke} strokeWidth={strokeWidth} fill={fill} />;
    }
    if (node.kind === "ellipse") {
      const width = node.width ?? 0;
      const height = node.height ?? 0;
      return <ellipse key={index} cx={node.x + width / 2} cy={node.y + height / 2} rx={width / 2} ry={height / 2} stroke={stroke} strokeWidth={strokeWidth} fill={fill} />;
    }
    if ((node.kind === "line" || node.kind === "arrow") && Number.isFinite(node.x2) && Number.isFinite(node.y2)) {
      return <line key={index} x1={node.x} y1={node.y} x2={node.x2} y2={node.y2} stroke={stroke} strokeWidth={strokeWidth} markerEnd={node.kind === "arrow" ? `url(#${markerId})` : undefined} />;
    }
    return null;
  }

  return (
    <div className="question-diagram">
      <svg role="img" aria-label="Unlabelled question diagram" viewBox={`0 0 ${spec.width} ${spec.height}`}>
        <defs>
          <marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="#1f2937" />
          </marker>
        </defs>
        {spec.elements.map(shape)}
      </svg>
    </div>
  );
}

