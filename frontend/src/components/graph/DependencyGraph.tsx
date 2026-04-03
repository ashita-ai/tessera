import { useEffect, useRef, useCallback, useState } from "react";
import * as d3 from "d3";
import type { SimulationNodeDatum, SimulationLinkDatum } from "d3";

export interface GraphNode extends SimulationNodeDatum {
  id: string;
  label: string;
  group: string; // team name — used for coloring
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

const EDGE_COLORS: Record<string, string> = {
  CONSUMES: "var(--accent)",
  REFERENCES: "var(--warning)",
  TRANSFORMS: "var(--success)",
};

const GROUP_COLORS = [
  "#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444",
  "#ec4899", "#6366f1", "#14b8a6", "#f97316", "#84cc16",
];

function colorForGroup(group: string, groups: string[]): string {
  const idx = groups.indexOf(group);
  return GROUP_COLORS[idx % GROUP_COLORS.length];
}

export function DependencyGraph({ nodes, links, onNodeClick, className }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    node: GraphNode;
  } | null>(null);

  const groups = [...new Set(nodes.map((n) => n.group))];

  const buildGraph = useCallback(() => {
    const svg = d3.select(svgRef.current);
    const container = containerRef.current;
    if (!svg.node() || !container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;

    svg.attr("viewBox", `0 0 ${width} ${height}`);
    svg.selectAll("*").remove();

    // Defs: arrow markers, glow filter
    const defs = svg.append("defs");

    // Glow filter for active nodes
    const filter = defs.append("filter").attr("id", "glow");
    filter
      .append("feGaussianBlur")
      .attr("stdDeviation", "3")
      .attr("result", "coloredBlur");
    const feMerge = filter.append("feMerge");
    feMerge.append("feMergeNode").attr("in", "coloredBlur");
    feMerge.append("feMergeNode").attr("in", "SourceGraphic");

    // Arrow markers per edge type
    for (const [type, color] of Object.entries(EDGE_COLORS)) {
      defs
        .append("marker")
        .attr("id", `arrow-${type}`)
        .attr("viewBox", "0 -4 8 8")
        .attr("refX", 20)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-4L8,0L0,4Z")
        .attr("fill", color)
        .attr("opacity", 0.6);
    }

    const g = svg.append("g");

    // Zoom
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });
    svg.call(zoom);

    // Force simulation
    const simulation = d3
      .forceSimulation<GraphNode>(nodes)
      .force(
        "link",
        d3
          .forceLink<GraphNode, GraphLink>(links)
          .id((d) => d.id)
          .distance(120),
      )
      .force("charge", d3.forceManyBody().strength(-400))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(30));

    // Links
    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => {
        const type = typeof d.type === "string" ? d.type : "CONSUMES";
        return EDGE_COLORS[type] ?? "var(--border-strong)";
      })
      .attr("stroke-opacity", (d) => (d.confidence ?? 1) * 0.4)
      .attr("stroke-width", 1.5)
      .attr("marker-end", (d) => {
        const type = typeof d.type === "string" ? d.type : "CONSUMES";
        return `url(#arrow-${type})`;
      });

    // Node groups
    const node = g
      .append("g")
      .selectAll<SVGGElement, GraphNode>("g")
      .data(nodes)
      .join("g")
      .style("cursor", "pointer")
      .call(
        d3
          .drag<SVGGElement, GraphNode>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }),
      );

    // Pulse ring for nodes with breaking proposals
    node
      .filter((d) => d.hasBreakingProposal)
      .append("circle")
      .attr("r", 14)
      .attr("fill", "none")
      .attr("stroke", "var(--danger)")
      .attr("stroke-width", 1.5)
      .attr("opacity", 0.4)
      .attr("class", "node-pulse");

    // Node circles
    node
      .append("circle")
      .attr("r", (d) => 8 + Math.min(d.assetCount, 10))
      .attr("fill", (d) => colorForGroup(d.group, groups))
      .attr("fill-opacity", 0.15)
      .attr("stroke", (d) => colorForGroup(d.group, groups))
      .attr("stroke-width", 1.5)
      .attr("filter", (d) => (d.hasBreakingProposal ? "url(#glow)" : ""));

    // Inner dot
    node
      .append("circle")
      .attr("r", 3)
      .attr("fill", (d) => colorForGroup(d.group, groups));

    // Labels
    node
      .append("text")
      .text((d) => d.label)
      .attr("dy", (d) => -(12 + Math.min(d.assetCount, 10)))
      .attr("text-anchor", "middle")
      .attr("fill", "var(--text-secondary)")
      .attr("font-size", "11px")
      .attr("font-family", "Outfit, system-ui, sans-serif")
      .attr("font-weight", "500");

    // Interactions
    node
      .on("mouseenter", (event, d) => {
        const rect = container.getBoundingClientRect();
        setTooltip({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
          node: d,
        });

        // Highlight connected edges
        link
          .attr("stroke-opacity", (l) => {
            const src = typeof l.source === "object" ? l.source.id : l.source;
            const tgt = typeof l.target === "object" ? l.target.id : l.target;
            return src === d.id || tgt === d.id ? 0.9 : 0.08;
          })
          .attr("stroke-width", (l) => {
            const src = typeof l.source === "object" ? l.source.id : l.source;
            const tgt = typeof l.target === "object" ? l.target.id : l.target;
            return src === d.id || tgt === d.id ? 2.5 : 1;
          });

        node.select("circle:nth-child(2)").attr("fill-opacity", (n) => {
          const isConnected = links.some((l) => {
            const src = typeof l.source === "object" ? l.source.id : l.source;
            const tgt = typeof l.target === "object" ? l.target.id : l.target;
            return (
              (src === d.id && tgt === n.id) ||
              (tgt === d.id && src === n.id) ||
              n.id === d.id
            );
          });
          return isConnected ? 0.25 : 0.05;
        });
      })
      .on("mouseleave", () => {
        setTooltip(null);
        link
          .attr("stroke-opacity", (d) => (d.confidence ?? 1) * 0.4)
          .attr("stroke-width", 1.5);
        node.select("circle:nth-child(2)").attr("fill-opacity", 0.15);
      })
      .on("click", (_event, d) => {
        onNodeClick?.(d);
      });

    // Tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as GraphNode).x!)
        .attr("y1", (d) => (d.source as GraphNode).y!)
        .attr("x2", (d) => (d.target as GraphNode).x!)
        .attr("y2", (d) => (d.target as GraphNode).y!);

      node.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });

    // Center on load
    svg.call(zoom.transform, d3.zoomIdentity);

    return () => {
      simulation.stop();
    };
  }, [nodes, links, groups, onNodeClick]);

  useEffect(() => {
    const cleanup = buildGraph();

    const observer = new ResizeObserver(() => {
      buildGraph();
    });
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => {
      cleanup?.();
      observer.disconnect();
    };
  }, [buildGraph]);

  return (
    <div ref={containerRef} className={`relative overflow-hidden ${className ?? ""}`}>
      <svg
        ref={svgRef}
        className="h-full w-full"
        style={{ background: "transparent" }}
      />

      {/* Tooltip */}
      {tooltip && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-border bg-surface-2 px-3 py-2 shadow-lg"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 8,
          }}
        >
          <p className="font-mono text-xs font-semibold text-accent">
            {tooltip.node.label}
          </p>
          <p className="mt-0.5 text-2xs text-text-muted">
            {tooltip.node.group} &middot; {tooltip.node.assetCount} asset
            {tooltip.node.assetCount !== 1 ? "s" : ""}
          </p>
          {tooltip.node.hasBreakingProposal && (
            <p className="mt-1 text-2xs font-medium text-danger">
              Breaking change pending
            </p>
          )}
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-3 left-3 flex gap-4 rounded-md border border-border bg-surface-1/80 px-3 py-1.5 backdrop-blur-sm">
        {Object.entries(EDGE_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1.5">
            <div
              className="h-0.5 w-4 rounded-full"
              style={{ background: color }}
            />
            <span className="font-mono text-2xs text-text-muted">
              {type.toLowerCase()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
