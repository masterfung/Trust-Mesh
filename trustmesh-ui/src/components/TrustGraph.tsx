"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import * as d3 from "d3";
import type { GraphData, QueryResult, ProfileData } from "@/lib/api";

const NETWORK_COLORS: Record<string, string> = {
  family: "#FEDC25",
  team: "#ffb800",
  friends: "#22c55e",
  custom: "#f59e0b",
};

const USER_COLORS: Record<string, string> = {
  peter: "#3b82f6",
  molly: "#FEDC25",
  jane: "#ec4899",
  bill: "#22c55e",
  kyle: "#f97316",
};

const SERVICE_COLOR = "#f59e0b"; // Amber for service providers
const PERSON_COLOR_FALLBACK = "#06b6d4"; // Cyan fallback for persons

const DECISION_COLORS: Record<string, string> = {
  allowed: "#22c55e",
  denied: "#ef4444",
  redacted: "#f59e0b",
};

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  username: string;
  display_name: string;
  bio: string;
  user_type?: string;
  profile_data?: ProfileData | null;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

interface QueryAnimation {
  fromId: string;
  toId: string;
  decision: string;
  question: string;
  id: string;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  node: SimNode | null;
}

/** Returns the fill color for a node, accounting for user_type and username overrides. */
function getNodeColor(d: SimNode): string {
  if (d.user_type === "service") return SERVICE_COLOR;
  return USER_COLORS[d.username] || PERSON_COLOR_FALLBACK;
}

/** Draws a diamond (rotated square) SVG path centered at 0,0 with the given size. */
function diamondPath(size: number): string {
  return `M 0 ${-size} L ${size} 0 L 0 ${size} L ${-size} 0 Z`;
}

export function TrustGraph({
  data,
  queries,
  onTriggerQuery,
}: {
  data: GraphData;
  queries?: QueryResult[];
  onTriggerQuery?: (fromId: string, toId: string) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const gRef = useRef<SVGGElement | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    node: null,
  });
  const animationQueueRef = useRef<QueryAnimation[]>([]);
  const lastAnimatedRef = useRef<string>("");

  // Determine animation color based on both decision and trust level
  const getQueryColor = useCallback(
    (decision: string, trustLevel: string): string => {
      if (decision === "denied") return DECISION_COLORS.denied; // Red: Citadel blocked
      if (decision === "redacted") return DECISION_COLORS.redacted; // Yellow: output redacted
      // For "allowed" decisions, color by trust level
      if (trustLevel === "network" || trustLevel === "private")
        return DECISION_COLORS.allowed; // Green: trusted, knowledge shared
      return "#f59e0b"; // Amber: public tier, limited info
    },
    []
  );

  // Animate a query pulse along an edge with reply
  const animateQuery = useCallback(
    (fromId: string, toId: string, decision: string, trustLevel: string) => {
      const g = gRef.current;
      if (!g) return;
      const gSel = d3.select(g);

      const fromNode = nodesRef.current.find((n) => n.id === fromId);
      const toNode = nodesRef.current.find((n) => n.id === toId);
      if (!fromNode || !toNode || fromNode.x == null || toNode.x == null)
        return;

      const queryColor = "#FEDC25"; // Mighty yellow: outgoing question
      const replyColor = getQueryColor(decision, trustLevel);

      // === Phase 1: Query dot (yellow) from sender -> receiver ===
      const dot = gSel
        .append("circle")
        .attr("cx", fromNode.x)
        .attr("cy", fromNode.y ?? 0)
        .attr("r", 6)
        .attr("fill", queryColor)
        .attr("opacity", 0.9)
        .style("filter", `drop-shadow(0 0 8px ${queryColor})`);

      dot
        .transition()
        .duration(800)
        .ease(d3.easeCubicInOut)
        .attr("cx", toNode.x)
        .attr("cy", toNode.y ?? 0)
        .attr("r", 4)
        .transition()
        .duration(300)
        .attr("r", 14)
        .attr("opacity", 0)
        .remove();

      // Pulse ring at receiver when query arrives
      const queryRing = gSel
        .append("circle")
        .attr("cx", toNode.x)
        .attr("cy", toNode.y ?? 0)
        .attr("r", 26)
        .attr("fill", "none")
        .attr("stroke", queryColor)
        .attr("stroke-width", 2)
        .attr("opacity", 0);

      queryRing
        .transition()
        .delay(800)
        .duration(400)
        .attr("r", 45)
        .attr("opacity", 0.5)
        .transition()
        .duration(300)
        .attr("r", 55)
        .attr("opacity", 0)
        .remove();

      // === Phase 2: Reply dot (color-coded) from receiver -> sender ===
      const replyDot = gSel
        .append("circle")
        .attr("cx", toNode.x)
        .attr("cy", toNode.y ?? 0)
        .attr("r", 0)
        .attr("fill", replyColor)
        .attr("opacity", 0)
        .style("filter", `drop-shadow(0 0 8px ${replyColor})`);

      replyDot
        .transition()
        .delay(1300) // Wait for query to arrive + brief processing
        .duration(100)
        .attr("r", 6)
        .attr("opacity", 0.9)
        .transition()
        .duration(800)
        .ease(d3.easeCubicInOut)
        .attr("cx", fromNode.x)
        .attr("cy", fromNode.y ?? 0)
        .attr("r", 4)
        .transition()
        .duration(300)
        .attr("r", 14)
        .attr("opacity", 0)
        .remove();

      // Pulse ring at sender when reply arrives
      const replyRing = gSel
        .append("circle")
        .attr("cx", fromNode.x)
        .attr("cy", fromNode.y ?? 0)
        .attr("r", 26)
        .attr("fill", "none")
        .attr("stroke", replyColor)
        .attr("stroke-width", 2)
        .attr("opacity", 0);

      replyRing
        .transition()
        .delay(2200)
        .duration(500)
        .attr("r", 50)
        .attr("opacity", 0.6)
        .transition()
        .duration(400)
        .attr("r", 65)
        .attr("opacity", 0)
        .remove();

      // Flash the edge with query color, then reply color
      const edgeLines = gSel
        .selectAll<SVGLineElement, SimLink>("line.edge")
        .filter(
          (d) =>
            ((d.source as SimNode).id === fromId &&
              (d.target as SimNode).id === toId) ||
            ((d.source as SimNode).id === toId &&
              (d.target as SimNode).id === fromId)
        );

      edgeLines
        .transition()
        .duration(200)
        .attr("stroke", queryColor)
        .attr("stroke-width", 3)
        .attr("stroke-opacity", 0.8)
        .transition()
        .delay(800)
        .duration(200)
        .attr("stroke", replyColor)
        .attr("stroke-width", 3)
        .attr("stroke-opacity", 1)
        .transition()
        .duration(1200)
        .attr("stroke", "#3f3f46")
        .attr("stroke-width", 1.5)
        .attr("stroke-opacity", 0.5);
    },
    [getQueryColor]
  );

  // Watch for new queries and animate them
  useEffect(() => {
    if (!queries || queries.length === 0) return;
    const latest = queries[0];
    if (latest.id === lastAnimatedRef.current) return;
    lastAnimatedRef.current = latest.id;
    animateQuery(
      latest.from_user_id,
      latest.to_user_id,
      latest.decision,
      latest.trust_level
    );
  }, [queries, animateQuery]);

  useEffect(() => {
    if (!svgRef.current || !data) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    // Defs for gradients and filters
    const defs = svg.append("defs");

    // Glow filter
    const glow = defs.append("filter").attr("id", "glow");
    glow
      .append("feGaussianBlur")
      .attr("stdDeviation", "3")
      .attr("result", "coloredBlur");
    const feMerge = glow.append("feMerge");
    feMerge.append("feMergeNode").attr("in", "coloredBlur");
    feMerge.append("feMergeNode").attr("in", "SourceGraphic");

    // Service glow filter (warmer)
    const serviceGlow = defs.append("filter").attr("id", "serviceGlow");
    serviceGlow
      .append("feGaussianBlur")
      .attr("stdDeviation", "4")
      .attr("result", "coloredBlur");
    const serviceFeMerge = serviceGlow.append("feMerge");
    serviceFeMerge.append("feMergeNode").attr("in", "coloredBlur");
    serviceFeMerge.append("feMergeNode").attr("in", "SourceGraphic");

    const g = svg.append("g");
    gRef.current = g.node();

    // Zoom
    const zoomBehavior = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoomBehavior);

    // Prepare data
    const nodes: SimNode[] = data.nodes.map((n) => ({ ...n }));
    nodesRef.current = nodes;
    const links: SimLink[] = data.edges.map((e) => ({
      source: e.source,
      target: e.target,
      type: e.type,
    }));

    // Network hulls
    const networkGroups = data.networks.map((n) => ({
      ...n,
      color: NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom,
    }));

    // Simulation
    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          .distance(160)
      )
      .force("charge", d3.forceManyBody().strength(-600))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide(60));

    // Draw network hulls
    const hullGroup = g.append("g").attr("class", "hulls");

    function drawHulls() {
      hullGroup.selectAll("*").remove();

      for (const net of networkGroups) {
        const memberNodes = nodes.filter((n) => net.members.includes(n.id));
        if (memberNodes.length < 2) continue;

        const points: [number, number][] = [];
        memberNodes.forEach((n) => {
          const x = n.x ?? 0;
          const y = n.y ?? 0;
          const pad = 50;
          points.push([x - pad, y - pad]);
          points.push([x + pad, y - pad]);
          points.push([x - pad, y + pad]);
          points.push([x + pad, y + pad]);
        });

        const hull = d3.polygonHull(points);
        if (hull) {
          hullGroup
            .append("path")
            .datum(hull)
            .attr("d", (d) => `M${d.join("L")}Z`)
            .attr("fill", net.color)
            .attr("fill-opacity", 0.06)
            .attr("stroke", net.color)
            .attr("stroke-opacity", 0.25)
            .attr("stroke-width", 1.5)
            .attr("stroke-dasharray", "6,4");

          // Network label
          const cx = d3.mean(memberNodes, (n) => n.x) ?? 0;
          const cy = (d3.min(memberNodes, (n) => n.y) ?? 0) - 65;
          hullGroup
            .append("text")
            .attr("x", cx)
            .attr("y", cy)
            .attr("text-anchor", "middle")
            .attr("fill", net.color)
            .attr("font-size", "11px")
            .attr("font-weight", "600")
            .attr("font-family", "system-ui, sans-serif")
            .attr("opacity", 0.7)
            .text(net.name);
        }
      }
    }

    // Links
    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("class", "edge")
      .attr("stroke", "#3f3f46")
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.5);

    // Node groups
    const node = g
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .style("cursor", "pointer")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .call(
        d3
          .drag<any, SimNode>()
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
          })
      )
      .on("click", (_event, d) => {
        setSelectedNode((prev) => (prev?.id === d.id ? null : d));
      })
      .on("mouseenter", (event: MouseEvent, d: SimNode) => {
        // Get position relative to the container
        const container = containerRef.current;
        if (!container) return;
        const rect = container.getBoundingClientRect();
        setTooltip({
          visible: true,
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
          node: d,
        });
      })
      .on("mousemove", (event: MouseEvent, d: SimNode) => {
        const container = containerRef.current;
        if (!container) return;
        const rect = container.getBoundingClientRect();
        setTooltip({
          visible: true,
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
          node: d,
        });
      })
      .on("mouseleave", () => {
        setTooltip({ visible: false, x: 0, y: 0, node: null });
      });

    // --- Service provider nodes: diamond shape ---
    // Outer glow ring for service nodes
    node
      .filter((d) => d.user_type === "service")
      .append("path")
      .attr("d", diamondPath(34))
      .attr("fill", "none")
      .attr("stroke", SERVICE_COLOR)
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.25);

    // Diamond shape for service nodes
    node
      .filter((d) => d.user_type === "service")
      .append("path")
      .attr("d", diamondPath(27))
      .attr("fill", SERVICE_COLOR)
      .attr("stroke", "#09090b")
      .attr("stroke-width", 3)
      .style("filter", "url(#serviceGlow)");

    // --- Person nodes: circle shape ---
    // Outer glow ring for person nodes
    node
      .filter((d) => d.user_type !== "service")
      .append("circle")
      .attr("r", 32)
      .attr("fill", "none")
      .attr("stroke", (d) => getNodeColor(d))
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.2);

    // Circle for person nodes
    node
      .filter((d) => d.user_type !== "service")
      .append("circle")
      .attr("r", 26)
      .attr("fill", (d) => getNodeColor(d))
      .attr("stroke", "#09090b")
      .attr("stroke-width", 3)
      .style("filter", "url(#glow)");

    // Node labels (initials) -- for all nodes
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", (d) => (d.user_type === "service" ? "#09090b" : "white"))
      .attr("font-size", "12px")
      .attr("font-weight", "bold")
      .attr("font-family", "system-ui, sans-serif")
      .attr("pointer-events", "none")
      .text((d) =>
        d.display_name
          .split(" ")
          .map((w) => w[0])
          .join("")
      );

    // Name labels below -- for all nodes
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "44px")
      .attr("fill", "#a1a1aa")
      .attr("font-size", "11px")
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", "500")
      .attr("pointer-events", "none")
      .text((d) => d.display_name);

    // Small user_type label beneath the name for service nodes
    node
      .filter((d) => d.user_type === "service")
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "57px")
      .attr("fill", SERVICE_COLOR)
      .attr("font-size", "9px")
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", "600")
      .attr("pointer-events", "none")
      .attr("opacity", 0.7)
      .text("SERVICE");

    // Tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as SimNode).x ?? 0)
        .attr("y1", (d) => (d.source as SimNode).y ?? 0)
        .attr("x2", (d) => (d.target as SimNode).x ?? 0)
        .attr("y2", (d) => (d.target as SimNode).y ?? 0);

      node.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);

      drawHulls();
    });

    // Auto-fit the graph to viewport after simulation settles
    const fitTimer = setTimeout(() => {
      // Calculate bounding box of all nodes
      const xs = nodes.map((n) => n.x ?? 0);
      const ys = nodes.map((n) => n.y ?? 0);
      const minX = Math.min(...xs) - 80;
      const maxX = Math.max(...xs) + 80;
      const minY = Math.min(...ys) - 80;
      const maxY = Math.max(...ys) + 80;
      const bboxWidth = maxX - minX;
      const bboxHeight = maxY - minY;

      const scale =
        Math.min(
          width / bboxWidth,
          height / bboxHeight,
          1.8 // Don't zoom in too much
        ) * 0.85; // Leave some padding

      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const tx = width / 2 - cx * scale;
      const ty = height / 2 - cy * scale - 20; // Nudge up slightly for visual balance

      svg
        .transition()
        .duration(800)
        .ease(d3.easeCubicOut)
        .call(
          zoomBehavior.transform,
          d3.zoomIdentity.translate(tx, ty).scale(scale)
        );

      // Process any queued animations
      const queue = animationQueueRef.current;
      animationQueueRef.current = [];
      for (const anim of queue) {
        animateQuery(anim.fromId, anim.toId, anim.decision, "public");
      }
    }, 1500); // Wait for simulation to mostly settle

    // Process queued animations on simulation end too
    simulation.on("end", () => {
      const queue = animationQueueRef.current;
      animationQueueRef.current = [];
      for (const anim of queue) {
        animateQuery(anim.fromId, anim.toId, anim.decision, "public");
      }
    });

    return () => {
      simulation.stop();
      clearTimeout(fitTimer);
    };
  }, [data, animateQuery]);

  // Compute tooltip position to keep it within bounds
  const getTooltipStyle = (): React.CSSProperties => {
    if (!tooltip.visible) return { display: "none" };
    const tooltipWidth = 280;
    const tooltipOffset = 16;
    const containerWidth = containerRef.current?.clientWidth ?? 800;

    // Position to the right by default; flip left if it would overflow
    let left = tooltip.x + tooltipOffset;
    if (left + tooltipWidth > containerWidth) {
      left = tooltip.x - tooltipWidth - tooltipOffset;
    }

    return {
      position: "absolute",
      left: `${left}px`,
      top: `${tooltip.y - 20}px`,
      pointerEvents: "none" as const,
      zIndex: 50,
    };
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full"
      style={{ height: "calc(100vh - 80px)" }}
    >
      <svg ref={svgRef} className="w-full h-full" />

      {/* Hover Tooltip */}
      {tooltip.visible && tooltip.node && (
        <div style={getTooltipStyle()}>
          <NodeTooltip node={tooltip.node} networks={data.networks} />
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-card/95 backdrop-blur-sm border border-card-border rounded-2xl p-4 shadow-lg">
        <p className="text-xs font-semibold text-muted-foreground mb-3">
          Networks
        </p>
        {data.networks.map((n) => (
          <div key={n.id} className="flex items-center gap-2.5 mb-1.5">
            <div
              className="w-3 h-3 rounded-sm"
              style={{
                backgroundColor:
                  NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom,
              }}
            />
            <span className="text-xs text-muted-foreground">{n.name}</span>
          </div>
        ))}
        <div className="border-t border-card-border mt-3 pt-3">
          <p className="text-xs font-semibold text-muted-foreground mb-2">
            Node Types
          </p>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-cyan-500" />
            <span className="text-xs text-muted-foreground">Person</span>
          </div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <svg width="14" height="14" viewBox="0 0 14 14">
              <path
                d="M 7 1 L 13 7 L 7 13 L 1 7 Z"
                fill="#f59e0b"
                stroke="#09090b"
                strokeWidth="1"
              />
            </svg>
            <span className="text-xs text-muted-foreground">
              Service Provider
            </span>
          </div>
        </div>
        <div className="border-t border-card-border mt-3 pt-3">
          <p className="text-xs font-semibold text-muted-foreground mb-2">
            Query Flow
          </p>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-[#FEDC25]" />
            <span className="text-xs text-muted-foreground">
              Question sent
            </span>
          </div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-green-500" />
            <span className="text-xs text-muted-foreground">
              Knowledge shared
            </span>
          </div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-yellow-500" />
            <span className="text-xs text-muted-foreground">
              Limited (public only)
            </span>
          </div>
          <div className="flex items-center gap-2.5">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <span className="text-xs text-muted-foreground">
              Blocked (Citadel)
            </span>
          </div>
        </div>
      </div>

      {/* Selected Node Info */}
      {selectedNode && (
        <div className="absolute top-4 right-4 bg-card/95 backdrop-blur-sm border border-card-border rounded-2xl p-4 shadow-lg max-w-xs">
          <div className="flex items-center gap-3 mb-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center text-white font-bold text-sm"
              style={{
                backgroundColor: getNodeColor(selectedNode),
              }}
            >
              {selectedNode.display_name
                .split(" ")
                .map((w) => w[0])
                .join("")}
            </div>
            <div>
              <p className="text-sm font-semibold">
                {selectedNode.display_name}
              </p>
              <p className="text-[11px] text-muted-foreground">
                @{selectedNode.username}
              </p>
            </div>
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            {selectedNode.bio}
          </p>
          <div className="text-[11px] text-muted-foreground">
            <p className="font-semibold mb-1">Networks:</p>
            {data.networks
              .filter((n) => n.members.includes(selectedNode.id))
              .map((n) => (
                <span
                  key={n.id}
                  className="inline-block px-2 py-0.5 rounded-md mr-1 mb-1"
                  style={{
                    backgroundColor: `${NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom}20`,
                    color:
                      NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom,
                  }}
                >
                  {n.name}
                </span>
              ))}
          </div>
          {onTriggerQuery && (
            <button
              onClick={() => setSelectedNode(null)}
              className="mt-3 w-full text-xs text-muted-foreground hover:text-foreground transition-colors text-center"
            >
              Click node again to deselect
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NodeTooltip - Rich HTML tooltip shown on node hover
// ---------------------------------------------------------------------------

function NodeTooltip({
  node,
  networks,
}: {
  node: SimNode;
  networks: GraphData["networks"];
}) {
  const isService = node.user_type === "service";
  const pd = node.profile_data;

  const nodeNetworks = networks.filter((n) => n.members.includes(node.id));

  const truncatedBio =
    node.bio && node.bio.length > 100
      ? node.bio.slice(0, 100) + "..."
      : node.bio;

  return (
    <div
      className="w-[280px] bg-card/98 backdrop-blur-md border border-card-border rounded-xl shadow-2xl overflow-hidden"
      style={{ backdropFilter: "blur(12px)" }}
    >
      {/* Header with color strip */}
      <div
        className="px-3.5 pt-3 pb-2.5"
        style={{
          borderBottom: `2px solid ${getNodeColor(node)}25`,
        }}
      >
        <div className="flex items-center gap-2.5">
          {/* Avatar */}
          <div
            className="flex-shrink-0 w-9 h-9 flex items-center justify-center text-xs font-bold"
            style={{
              backgroundColor: getNodeColor(node),
              color: isService ? "#09090b" : "white",
              borderRadius: isService ? "4px" : "50%",
              transform: isService ? "rotate(45deg)" : "none",
            }}
          >
            <span style={{ transform: isService ? "rotate(-45deg)" : "none", display: "block" }}>
              {node.display_name
                .split(" ")
                .map((w) => w[0])
                .join("")}
            </span>
          </div>

          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground truncate">
              {node.display_name}
            </p>
            <p className="text-[11px] text-muted-foreground">@{node.username}</p>
          </div>

          {/* User type badge */}
          <span
            className="flex-shrink-0 text-[10px] font-semibold uppercase px-2 py-0.5 rounded-md"
            style={{
              backgroundColor: isService
                ? `${SERVICE_COLOR}20`
                : `${PERSON_COLOR_FALLBACK}20`,
              color: isService ? SERVICE_COLOR : PERSON_COLOR_FALLBACK,
            }}
          >
            {isService ? "Service" : "Person"}
          </span>
        </div>
      </div>

      {/* Profile data section */}
      <div className="px-3.5 py-2.5 space-y-2">
        {/* Occupation */}
        {pd?.occupation && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-0.5">
              Occupation
            </p>
            <p className="text-xs text-foreground">
              {pd.occupation.title}
              {pd.occupation.industry && (
                <span className="text-muted-foreground">
                  {" "}
                  -- {pd.occupation.industry}
                </span>
              )}
            </p>
          </div>
        )}

        {/* Age range + Family status on the same line */}
        {(pd?.age_range || pd?.family_status) && (
          <div className="flex items-center gap-3">
            {pd.age_range && (
              <div>
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-0.5">
                  Age
                </p>
                <p className="text-xs text-muted-foreground">
                  {pd.age_range}
                </p>
              </div>
            )}
            {pd.family_status && (
              <div>
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-0.5">
                  Family
                </p>
                <p className="text-xs text-muted-foreground">
                  {pd.family_status}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Skills as tags */}
        {pd?.skills && pd.skills.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
              Skills
            </p>
            <div className="flex flex-wrap gap-1">
              {pd.skills.slice(0, 4).map((skill, i) => (
                <span
                  key={i}
                  className="inline-block text-[10px] px-1.5 py-0.5 rounded bg-accent/10 text-accent-hover"
                >
                  {skill.name}
                </span>
              ))}
              {pd.skills.length > 4 && (
                <span className="inline-block text-[10px] px-1.5 py-0.5 rounded bg-card-hover text-muted-foreground">
                  +{pd.skills.length - 4}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Networks the node belongs to */}
        {nodeNetworks.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">
              Networks
            </p>
            <div className="flex flex-wrap gap-1">
              {nodeNetworks.map((n) => (
                <span
                  key={n.id}
                  className="inline-block text-[10px] px-1.5 py-0.5 rounded"
                  style={{
                    backgroundColor: `${NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom}20`,
                    color:
                      NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom,
                  }}
                >
                  {n.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Bio (truncated) */}
        {truncatedBio && (
          <p className="text-[11px] text-muted-foreground leading-relaxed border-t border-card-border pt-2">
            {truncatedBio}
          </p>
        )}
      </div>
    </div>
  );
}
