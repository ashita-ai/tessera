import { useEffect, useRef, useCallback } from "react";
import * as d3 from "d3";
import type { GraphData, GraphNode, GraphEdge } from "@/lib/api";

// ── Team color palette ──────────────────────────────────────────────
const TEAM_COLORS = [
  "#5eead4", // accent/cyan
  "#818cf8", // indigo
  "#f472b6", // pink
  "#fb923c", // orange
  "#a3e635", // lime
  "#facc15", // yellow
  "#c084fc", // purple
  "#38bdf8", // sky
  "#f87171", // red
  "#34d399", // emerald
];

function teamColor(teamId: string | undefined, teamMap: Map<string, number>): string {
  if (!teamId) return "#52525b";
  if (!teamMap.has(teamId)) {
    teamMap.set(teamId, teamMap.size);
  }
  return TEAM_COLORS[teamMap.get(teamId)! % TEAM_COLORS.length];
}

// ── Resource type icons (small SVG paths at 16x16) ──────────────────
const RESOURCE_ICONS: Record<string, string> = {
  api: "M3 8h10M8 3v10",                              // crosshair
  grpc: "M4 4l8 8M12 4l-8 8",                         // X
  graphql: "M4 12L8 4l4 8M5.5 10h5",                  // triangle
  kafka: "M3 8h4l2-4 2 8 2-4h4",                      // wave
  model: "M4 4h8v8H4zM7 4v8M4 8h8",                   // grid
  source: "M4 4h8l-2 4 2 4H4l2-4-2-4z",               // diamond
};

// ── Types for D3 simulation ─────────────────────────────────────────
interface SimNode extends d3.SimulationNodeDatum {
  data: GraphNode;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  data: GraphEdge;
}

interface Props {
  graphData: GraphData;
  width?: number;
  height?: number;
  onNodeClick?: (nodeId: string) => void;
  /** If set, only show this node and its direct neighbors */
  focusNodeId?: string;
}

export function DependencyGraph({
  graphData,
  width: propWidth,
  height: propHeight,
  onNodeClick,
  focusNodeId,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3.Simulation<SimNode, SimLink> | null>(null);
  const teamMap = useRef(new Map<string, number>()).current;

  const render = useCallback(() => {
    const svg = d3.select(svgRef.current);
    if (!svgRef.current || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const w = propWidth ?? rect.width;
    const h = propHeight ?? rect.height;
    if (w === 0 || h === 0) return;

    svg.attr("width", w).attr("height", h);
    svg.selectAll("*").remove();

    // ── Filter to neighborhood if focusNodeId ──
    let filteredData = graphData;
    if (focusNodeId) {
      const neighborIds = new Set<string>([focusNodeId]);
      for (const e of graphData.edges) {
        if (e.source === focusNodeId) neighborIds.add(e.target);
        if (e.target === focusNodeId) neighborIds.add(e.source);
      }
      filteredData = {
        nodes: graphData.nodes.filter((n) => neighborIds.has(n.id)),
        edges: graphData.edges.filter(
          (e) => neighborIds.has(e.source) && neighborIds.has(e.target),
        ),
      };
    }

    if (filteredData.nodes.length === 0) return;

    const simNodes: SimNode[] = filteredData.nodes.map((n) => ({ data: n }));
    const nodeIndex = new Map(simNodes.map((n, i) => [n.data.id, i]));

    const simLinks: SimLink[] = filteredData.edges
      .filter((e) => nodeIndex.has(e.source) && nodeIndex.has(e.target))
      .map((e) => ({
        source: simNodes[nodeIndex.get(e.source)!],
        target: simNodes[nodeIndex.get(e.target)!],
        data: e,
      }));

    // ── Defs: arrow markers, glow filter ──
    const defs = svg.append("defs");

    // Arrow marker
    defs
      .append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 0 10 6")
      .attr("refX", 22)
      .attr("refY", 3)
      .attr("markerWidth", 8)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,0L10,3L0,6")
      .attr("fill", "#3f3f46");

    // Glow filter for breaking proposals
    const glow = defs.append("filter").attr("id", "glow");
    glow
      .append("feGaussianBlur")
      .attr("stdDeviation", "3")
      .attr("result", "coloredBlur");
    const merge = glow.append("feMerge");
    merge.append("feMergeNode").attr("in", "coloredBlur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    // ── Grid background ──
    const gridSize = 48;
    const gridGroup = svg.append("g").attr("class", "grid");
    for (let x = 0; x < w; x += gridSize) {
      gridGroup
        .append("line")
        .attr("x1", x).attr("y1", 0).attr("x2", x).attr("y2", h)
        .attr("stroke", "#1a1a1e").attr("stroke-width", 0.5);
    }
    for (let y = 0; y < h; y += gridSize) {
      gridGroup
        .append("line")
        .attr("x1", 0).attr("y1", y).attr("x2", w).attr("y2", y)
        .attr("stroke", "#1a1a1e").attr("stroke-width", 0.5);
    }

    // ── Main group for zoom/pan ──
    const g = svg.append("g");

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => {
        g.attr("transform", event.transform.toString());
      });
    svg.call(zoom as unknown as (selection: d3.Selection<SVGSVGElement | null, unknown, null, undefined>) => void);

    // ── Tooltip ──
    const tooltip = d3
      .select(containerRef.current)
      .append("div")
      .attr("class", "graph-tooltip")
      .style("position", "absolute")
      .style("pointer-events", "none")
      .style("background", "#18181b")
      .style("border", "1px solid #3f3f46")
      .style("border-radius", "6px")
      .style("padding", "8px 10px")
      .style("font-size", "11px")
      .style("color", "#a1a1aa")
      .style("opacity", "0")
      .style("z-index", "50")
      .style("max-width", "220px");

    // ── Edges ──
    const linkGroup = g.append("g");
    const links = linkGroup
      .selectAll("line")
      .data(simLinks)
      .join("line")
      .attr("stroke", "#3f3f46")
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", (d) => {
        const conf = d.data.confidence;
        return conf != null ? Math.max(0.2, conf) : 0.6;
      })
      .attr("stroke-dasharray", (d) =>
        d.data.source_label === "otel" ? "4 3" : null,
      )
      .attr("marker-end", "url(#arrow)");

    // ── Nodes ──
    const nodeGroup = g.append("g");
    const nodes = nodeGroup
      .selectAll<SVGGElement, SimNode>("g")
      .data(simNodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(
        d3
          .drag<SVGGElement, SimNode>()
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

    // Node circle
    nodes
      .append("circle")
      .attr("r", (d) => (d.data.id === focusNodeId ? 14 : 10))
      .attr("fill", (d) => {
        const color = teamColor(d.data.team_id, teamMap);
        return color + "20"; // 12% opacity fill
      })
      .attr("stroke", (d) => teamColor(d.data.team_id, teamMap))
      .attr("stroke-width", (d) => (d.data.id === focusNodeId ? 2 : 1.5))
      .attr("filter", (d) =>
        d.data.has_breaking_proposal ? "url(#glow)" : null,
      );

    // Breaking proposal glow ring
    nodes
      .filter((d) => !!d.data.has_breaking_proposal)
      .append("circle")
      .attr("r", 16)
      .attr("fill", "none")
      .attr("stroke", "#f87171")
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.5)
      .attr("stroke-dasharray", "3 2");

    // Resource type icon inside node
    nodes
      .append("path")
      .attr("d", (d) => {
        const icon = RESOURCE_ICONS[d.data.resource_type ?? ""] ?? RESOURCE_ICONS["api"];
        return icon;
      })
      .attr("transform", "translate(-8,-8) scale(1)")
      .attr("stroke", (d) => teamColor(d.data.team_id, teamMap))
      .attr("stroke-width", 1.2)
      .attr("fill", "none")
      .attr("stroke-linecap", "round")
      .attr("opacity", 0.7);

    // Node label
    nodes
      .append("text")
      .text((d) => d.data.label)
      .attr("dy", 22)
      .attr("text-anchor", "middle")
      .attr("font-size", "10px")
      .attr("font-family", "'IBM Plex Mono', monospace")
      .attr("fill", "#a1a1aa")
      .attr("pointer-events", "none");

    // ── Interactions ──
    nodes
      .on("mouseenter", (_event: MouseEvent, d: SimNode) => {
        const node = d.data;
        const lines = [
          `<strong style="color:#fafafa">${node.label}</strong>`,
          node.team_name ? `Team: ${node.team_name}` : null,
          node.resource_type ? `Type: ${node.resource_type}` : null,
          node.has_breaking_proposal
            ? `<span style="color:#f87171">Breaking proposal</span>`
            : null,
        ].filter(Boolean);
        tooltip.html(lines.join("<br/>")).style("opacity", "1");

        // Highlight connected edges
        links
          .attr("stroke", (l) =>
            (l.source as SimNode).data.id === node.id ||
            (l.target as SimNode).data.id === node.id
              ? teamColor(node.team_id, teamMap)
              : "#3f3f46",
          )
          .attr("stroke-opacity", (l) =>
            (l.source as SimNode).data.id === node.id ||
            (l.target as SimNode).data.id === node.id
              ? 1
              : 0.15,
          );

        // Dim unconnected nodes
        const connectedIds = new Set<string>([node.id]);
        for (const l of simLinks) {
          if ((l.source as SimNode).data.id === node.id) connectedIds.add((l.target as SimNode).data.id);
          if ((l.target as SimNode).data.id === node.id) connectedIds.add((l.source as SimNode).data.id);
        }
        nodes.select("circle").attr("opacity", (dd) =>
          connectedIds.has((dd as SimNode).data.id) ? 1 : 0.2,
        );
      })
      .on("mousemove", (event) => {
        const containerRect = containerRef.current!.getBoundingClientRect();
        tooltip
          .style("left", `${event.clientX - containerRect.left + 12}px`)
          .style("top", `${event.clientY - containerRect.top - 10}px`);
      })
      .on("mouseleave", () => {
        tooltip.style("opacity", "0");
        links.attr("stroke", "#3f3f46").attr("stroke-opacity", (d) => {
          const conf = d.data.confidence;
          return conf != null ? Math.max(0.2, conf) : 0.6;
        });
        nodes.select("circle").attr("opacity", 1);
      })
      .on("click", (_event: MouseEvent, d: SimNode) => {
        onNodeClick?.(d.data.id);
      });

    // ── Force simulation ──
    const simulation = d3
      .forceSimulation(simNodes)
      .force(
        "link",
        d3
          .forceLink(simLinks)
          .id((_, i) => simNodes[i].data.id)
          .distance(100),
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(w / 2, h / 2))
      .force("collision", d3.forceCollide().radius(30))
      .on("tick", () => {
        links
          .attr("x1", (d) => (d.source as SimNode).x ?? 0)
          .attr("y1", (d) => (d.source as SimNode).y ?? 0)
          .attr("x2", (d) => (d.target as SimNode).x ?? 0)
          .attr("y2", (d) => (d.target as SimNode).y ?? 0);

        nodes.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
      });

    simulationRef.current = simulation;

    // Cleanup tooltip on unmount
    return () => {
      tooltip.remove();
      simulation.stop();
    };
  }, [graphData, propWidth, propHeight, onNodeClick, focusNodeId, teamMap]);

  useEffect(() => {
    const cleanup = render();
    return () => cleanup?.();
  }, [render]);

  // Re-render on container resize
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(() => {
      render();
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [render]);

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      <svg ref={svgRef} className="h-full w-full" />
    </div>
  );
}
