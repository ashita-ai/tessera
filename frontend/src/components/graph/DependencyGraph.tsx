import { useEffect, useRef, useCallback, useState } from "react";
import * as d3 from "d3";
import type { SimulationNodeDatum, SimulationLinkDatum } from "d3";

export interface GraphNode extends SimulationNodeDatum {
  id: string;
  label: string;
  group: string;
  assetCount: number;
  hasBreakingProposal: boolean;
}

export interface GraphLink extends SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  type: "CONSUMES" | "REFERENCES" | "TRANSFORMS";
  confidence?: number;
}

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  onNodeClick?: (node: GraphNode) => void;
  className?: string;
}

const EDGE_STYLES: Record<string, { color: string; dash?: string }> = {
  CONSUMES: { color: "rgba(94,234,212,0.25)" },
  REFERENCES: { color: "rgba(251,191,36,0.2)", dash: "4,3" },
  TRANSFORMS: { color: "rgba(74,222,128,0.2)", dash: "2,2" },
};

const GROUP_PALETTE = [
  "#5eead4", "#a78bfa", "#fbbf24", "#4ade80", "#f87171",
  "#f472b6", "#818cf8", "#2dd4bf",
];

function groupColor(group: string, groups: string[]): string {
  return GROUP_PALETTE[groups.indexOf(group) % GROUP_PALETTE.length];
}

export function DependencyGraph({ nodes, links, onNodeClick, className }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<GraphNode | null>(null);

  const groups = [...new Set(nodes.map((n) => n.group))];

  const build = useCallback(() => {
    const svg = d3.select(svgRef.current);
    const wrap = wrapRef.current;
    if (!svg.node() || !wrap) return;

    const w = wrap.clientWidth;
    const h = wrap.clientHeight;
    svg.attr("viewBox", `0 0 ${w} ${h}`);
    svg.selectAll("*").remove();

    const defs = svg.append("defs");

    // Subtle glow for breaking nodes
    const glow = defs.append("filter").attr("id", "glow").attr("x", "-50%").attr("y", "-50%").attr("width", "200%").attr("height", "200%");
    glow.append("feGaussianBlur").attr("stdDeviation", "4").attr("result", "blur");
    const merge = glow.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    // Arrow markers
    for (const [type, style] of Object.entries(EDGE_STYLES)) {
      defs.append("marker")
        .attr("id", `arr-${type}`).attr("viewBox", "0 -3 6 6")
        .attr("refX", 18).attr("refY", 0)
        .attr("markerWidth", 5).attr("markerHeight", 5)
        .attr("orient", "auto")
        .append("path").attr("d", "M0,-3L6,0L0,3Z")
        .attr("fill", style.color);
    }

    const g = svg.append("g");

    (svg as unknown as d3.Selection<SVGSVGElement, unknown, null, undefined>).call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on("zoom", (e) => g.attr("transform", e.transform)),
    );

    const sim = d3.forceSimulation<GraphNode>(nodes)
      .force("link", d3.forceLink<GraphNode, GraphLink>(links).id((d) => d.id).distance(140))
      .force("charge", d3.forceManyBody().strength(-500))
      .force("center", d3.forceCenter(w / 2, h / 2))
      .force("collide", d3.forceCollide().radius(35));

    // Edges
    const edge = g.append("g").selectAll("line").data(links).join("line")
      .attr("stroke", (d) => EDGE_STYLES[d.type]?.color ?? "rgba(255,255,255,0.06)")
      .attr("stroke-width", 1)
      .attr("stroke-dasharray", (d) => EDGE_STYLES[d.type]?.dash ?? "")
      .attr("marker-end", (d) => `url(#arr-${d.type})`);

    // Node groups
    const node = g.append("g").selectAll<SVGGElement, GraphNode>("g").data(nodes).join("g")
      .style("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on("drag", (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on("end", (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }),
      );

    // Breaking pulse
    node.filter((d) => d.hasBreakingProposal)
      .append("circle").attr("r", 16)
      .attr("fill", "none").attr("stroke", "var(--red)").attr("stroke-width", 1)
      .attr("opacity", 0.4).attr("class", "node-pulse");

    // Outer ring
    node.append("circle")
      .attr("r", (d) => 7 + Math.min(d.assetCount * 0.6, 8))
      .attr("fill", (d) => groupColor(d.group, groups))
      .attr("fill-opacity", 0.06)
      .attr("stroke", (d) => groupColor(d.group, groups))
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.4)
      .attr("filter", (d) => d.hasBreakingProposal ? "url(#glow)" : "");

    // Center dot
    node.append("circle").attr("r", 2.5)
      .attr("fill", (d) => groupColor(d.group, groups))
      .attr("fill-opacity", 0.8);

    // Label
    node.append("text")
      .text((d) => d.label)
      .attr("dy", (d) => -(10 + Math.min(d.assetCount * 0.6, 8)))
      .attr("text-anchor", "middle")
      .attr("fill", "var(--text-2)")
      .attr("font-size", "10px")
      .attr("font-family", "'IBM Plex Mono', monospace")
      .attr("font-weight", "500")
      .attr("letter-spacing", "-0.02em");

    // Hover interactions
    node
      .on("mouseenter", (_, d) => {
        setHover(d);
        edge.attr("stroke-opacity", (l) => {
          const s = typeof l.source === "object" ? l.source.id : l.source;
          const t = typeof l.target === "object" ? l.target.id : l.target;
          return s === d.id || t === d.id ? 1 : 0.1;
        }).attr("stroke-width", (l) => {
          const s = typeof l.source === "object" ? l.source.id : l.source;
          const t = typeof l.target === "object" ? l.target.id : l.target;
          return s === d.id || t === d.id ? 1.5 : 0.5;
        });
      })
      .on("mouseleave", () => {
        setHover(null);
        edge.attr("stroke-opacity", 1).attr("stroke-width", 1);
      })
      .on("click", (_, d) => onNodeClick?.(d));

    sim.on("tick", () => {
      edge
        .attr("x1", (d) => (d.source as GraphNode).x!)
        .attr("y1", (d) => (d.source as GraphNode).y!)
        .attr("x2", (d) => (d.target as GraphNode).x!)
        .attr("y2", (d) => (d.target as GraphNode).y!);
      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    return () => sim.stop();
  }, [nodes, links, groups, onNodeClick]);

  useEffect(() => {
    const cleanup = build();
    const obs = new ResizeObserver(() => build());
    if (wrapRef.current) obs.observe(wrapRef.current);
    return () => { cleanup?.(); obs.disconnect(); };
  }, [build]);

  return (
    <div ref={wrapRef} className={`relative ${className ?? ""}`}>
      <svg ref={svgRef} className="h-full w-full" />

      {/* Hover tooltip */}
      {hover && (
        <div className="pointer-events-none absolute left-4 top-4 rounded-md border border-line bg-bg-raised/90 px-3 py-2 backdrop-blur-sm">
          <p className="font-mono text-xs font-medium text-accent">{hover.label}</p>
          <p className="mt-0.5 text-[11px] text-t3">
            {hover.group} &middot; {hover.assetCount} assets
          </p>
          {hover.hasBreakingProposal && (
            <p className="mt-1 text-[11px] font-medium text-red">breaking change</p>
          )}
        </div>
      )}

      {/* Minimal legend */}
      <div className="absolute bottom-3 right-3 flex gap-4 font-mono text-[10px] text-t3">
        {Object.entries(EDGE_STYLES).map(([type, s]) => (
          <span key={type} className="flex items-center gap-1.5">
            <span className="inline-block h-px w-3" style={{ background: s.color.replace(/[\d.]+\)$/, "0.6)") }} />
            {type.toLowerCase()}
          </span>
        ))}
      </div>
    </div>
  );
}
