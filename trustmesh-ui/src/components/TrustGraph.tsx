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
const POD_NEIGHBOR_COLOR = "#52525b"; // Muted zinc for cross-pod (unconfirmed) neighbors

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
  containerWidth: number;
  node: SimNode | null;
}

/** Returns the fill color for a node, accounting for user_type and username overrides. */
function getNodeColor(d: SimNode): string {
  if (d.user_type === "service") return SERVICE_COLOR;
  if (d.user_type === "pod_neighbor") return POD_NEIGHBOR_COLOR;
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
    containerWidth: 0,
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
    (fromId: string, toId: string, decision: string, trustLevel: string, question?: string) => {
      const g = gRef.current;
      if (!g) return;
      const gSel = d3.select(g);

      const fromNode = nodesRef.current.find((n) => n.id === fromId);
      const toNode = nodesRef.current.find((n) => n.id === toId);
      if (!fromNode || !toNode || fromNode.x == null || toNode.x == null)
        return;

      const queryColor = "#FEDC25"; // Mighty yellow: outgoing question
      const replyColor = getQueryColor(decision, trustLevel);

      // === Question bubble at midpoint ===
      if (question) {
        const midX = ((fromNode.x ?? 0) + (toNode.x ?? 0)) / 2;
        const midY = ((fromNode.y ?? 0) + (toNode.y ?? 0)) / 2;
        const truncQ = question.length > 48 ? question.slice(0, 45) + "…" : question;
        const rectW = Math.min(truncQ.length * 6.4 + 20, 220);
        const rectH = 24;

        const bubble = gSel.append("g")
          .attr("transform", `translate(${midX},${midY - 30})`)
          .attr("pointer-events", "none")
          .attr("opacity", 0);

        bubble.append("rect")
          .attr("x", -rectW / 2).attr("y", -rectH / 2)
          .attr("width", rectW).attr("height", rectH)
          .attr("rx", 12).attr("ry", 12)
          .attr("fill", "#111111")
          .attr("stroke", queryColor).attr("stroke-width", 1.5).attr("stroke-opacity", 0.7);

        // Tail pointing down
        const tailY = rectH / 2;
        bubble.append("path")
          .attr("d", `M -5 ${tailY} L 0 ${tailY + 8} L 5 ${tailY}`)
          .attr("fill", "#111111")
          .attr("stroke", queryColor).attr("stroke-width", 1.5)
          .attr("stroke-opacity", 0.7).attr("stroke-linejoin", "round");

        bubble.append("text")
          .attr("text-anchor", "middle").attr("dominant-baseline", "middle")
          .attr("fill", queryColor).attr("font-size", "9.5px")
          .attr("font-family", "system-ui, sans-serif").attr("font-weight", "500")
          .attr("letter-spacing", "0.01em")
          .text(truncQ);

        bubble.transition().duration(150).attr("opacity", 1)
          .transition().delay(900).duration(350).attr("opacity", 0)
          .remove();
      }

      // === Decision badge near toNode when query arrives ===
      const decisionLabel = decision === "allowed" ? "✓" : decision === "denied" ? "✗" : "~";
      const badge = gSel.append("g")
        .attr("transform", `translate(${(toNode.x ?? 0) + 28},${(toNode.y ?? 0) - 28})`)
        .attr("pointer-events", "none")
        .attr("opacity", 0);

      badge.append("circle")
        .attr("r", 10).attr("fill", replyColor).attr("fill-opacity", 0.15)
        .attr("stroke", replyColor).attr("stroke-width", 1.5);

      badge.append("text")
        .attr("text-anchor", "middle").attr("dominant-baseline", "middle")
        .attr("fill", replyColor).attr("font-size", "9px").attr("font-weight", "bold")
        .attr("font-family", "system-ui, sans-serif")
        .text(decisionLabel);

      badge.transition().delay(1400).duration(200).attr("opacity", 1)
        .transition().delay(1000).duration(400).attr("opacity", 0)
        .remove();

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
        .attr("stroke", "#71717a")
        .attr("stroke-width", 1.5)
        .attr("stroke-opacity", 0.6);
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
      latest.trust_level,
      latest.question,
    );
  }, [queries, animateQuery]);

  useEffect(() => {
    if (!svgRef.current || !data) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth || 800;
    const height = svgRef.current.clientHeight || 600;

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

    // Build adjacency set to know which nodes have connections
    const connectedIds = new Set<string>();
    for (const l of links) {
      const src = typeof l.source === "string" ? l.source : (l.source as SimNode).id;
      const tgt = typeof l.target === "string" ? l.target : (l.target as SimNode).id;
      connectedIds.add(src);
      connectedIds.add(tgt);
    }

    // Graph center — offset slightly left to account for right sidebar
    const graphCx = width * 0.45;
    const graphCy = height * 0.45;

    // Simulation — compact layout: moderate repulsion + strong gravity keeps clusters together
    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .id((d) => d.id)
          // Cross-pod edges are longer so neighbors orbit the outside of the main cluster
          .distance((l) => (l as SimLink).type === "cross_pod" ? 200 : 120)
          .strength((l) => (l as SimLink).type === "cross_pod" ? 0.3 : 0.8)
      )
      .force("charge", d3.forceManyBody().strength(-600))
      .force("center", d3.forceCenter(graphCx, graphCy))
      .force("collision", d3.forceCollide(60))
      // Strong gravity keeps sub-clusters near center; even stronger for disconnected service nodes
      .force("x", d3.forceX<SimNode>(graphCx).strength((d) => connectedIds.has(d.id) ? 0.08 : 0.15))
      .force("y", d3.forceY<SimNode>(graphCy).strength((d) => connectedIds.has(d.id) ? 0.08 : 0.15));

    // Warm up the simulation so the layout is stable before first paint
    simulation.alpha(1);
    for (let i = 0; i < 200; i++) simulation.tick();
    simulation.alpha(0.3).restart(); // Continue with gentle settling

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
            .attr("fill-opacity", 0.04)
            .attr("stroke", net.color)
            .attr("stroke-opacity", 0.2)
            .attr("stroke-width", 1)
            .attr("stroke-dasharray", "6,4");

          // Network label — positioned above the hull with a dark background for readability
          const cx = d3.mean(memberNodes, (n) => n.x) ?? 0;
          const cy = (d3.min(memberNodes, (n) => n.y) ?? 0) - 60;

          // Background pill behind label
          const labelText = net.name;
          const charWidth = 6;
          const pillWidth = labelText.length * charWidth + 16;
          hullGroup
            .append("rect")
            .attr("x", cx - pillWidth / 2)
            .attr("y", cy - 9)
            .attr("width", pillWidth)
            .attr("height", 18)
            .attr("rx", 9)
            .attr("fill", "#09090b")
            .attr("fill-opacity", 0.75);

          hullGroup
            .append("text")
            .attr("x", cx)
            .attr("y", cy + 4)
            .attr("text-anchor", "middle")
            .attr("fill", net.color)
            .attr("font-size", "10px")
            .attr("font-weight", "600")
            .attr("font-family", "system-ui, sans-serif")
            .attr("opacity", 0.85)
            .text(labelText);
        }
      }
    }

    // Links — visible connection lines between nodes
    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("class", "edge")
      .attr("stroke", (d) => d.type === "cross_pod" ? POD_NEIGHBOR_COLOR : "#71717a")
      .attr("stroke-width", (d) => d.type === "cross_pod" ? 1 : 1.5)
      .attr("stroke-opacity", (d) => d.type === "cross_pod" ? 0.4 : 0.6)
      .attr("stroke-dasharray", (d) => d.type === "cross_pod" ? "5,4" : "none");

    // Node groups
    const node = g
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .style("cursor", "pointer")
      .call(
        d3
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
          containerWidth: rect.width,
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
          containerWidth: rect.width,
          node: d,
        });
      })
      .on("mouseleave", () => {
        setTooltip({ visible: false, x: 0, y: 0, containerWidth: 0, node: null });
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
    // Outer glow ring for regular person nodes (not pod_neighbor)
    node
      .filter((d) => d.user_type !== "service" && d.user_type !== "pod_neighbor")
      .append("circle")
      .attr("r", 32)
      .attr("fill", "none")
      .attr("stroke", (d) => getNodeColor(d))
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.2);

    // Circle for regular person nodes
    node
      .filter((d) => d.user_type !== "service" && d.user_type !== "pod_neighbor")
      .append("circle")
      .attr("r", 26)
      .attr("fill", (d) => getNodeColor(d))
      .attr("stroke", "#09090b")
      .attr("stroke-width", 3)
      .style("filter", "url(#glow)");

    // --- Pod neighbor nodes: smaller muted dashed-border circle ---
    // Dashed outer ring to signal "unconfirmed / cross-pod" status
    node
      .filter((d) => d.user_type === "pod_neighbor")
      .append("circle")
      .attr("r", 24)
      .attr("fill", "none")
      .attr("stroke", POD_NEIGHBOR_COLOR)
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.5)
      .attr("stroke-dasharray", "4,3");

    // Filled circle (smaller, muted)
    node
      .filter((d) => d.user_type === "pod_neighbor")
      .append("circle")
      .attr("r", 20)
      .attr("fill", POD_NEIGHBOR_COLOR)
      .attr("fill-opacity", 0.55)
      .attr("stroke", "#09090b")
      .attr("stroke-width", 2);

    // Node labels (initials) -- for all nodes
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", (d) => (d.user_type === "service" ? "#09090b" : "white"))
      .attr("font-size", (d) => d.user_type === "pod_neighbor" ? "10px" : "12px")
      .attr("font-weight", "bold")
      .attr("font-family", "system-ui, sans-serif")
      .attr("pointer-events", "none")
      .attr("opacity", (d) => d.user_type === "pod_neighbor" ? 0.7 : 1)
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
      .attr("dy", (d) => d.user_type === "pod_neighbor" ? "36px" : "44px")
      .attr("fill", (d) => d.user_type === "pod_neighbor" ? "#71717a" : "#a1a1aa")
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

    // Port sublabel beneath the name for pod_neighbor nodes
    node
      .filter((d) => d.user_type === "pod_neighbor")
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "49px")
      .attr("fill", POD_NEIGHBOR_COLOR)
      .attr("font-size", "9px")
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", "600")
      .attr("pointer-events", "none")
      .attr("opacity", 0.65)
      .text((d) => {
        // bio contains "Pod name — :port", extract the port part
        const match = d.bio.match(/:(\d+)$/);
        return match ? `POD :${match[1]}` : "POD";
      });

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
      // Re-read actual SVG dimensions (may differ from initial mount / SSR defaults)
      const actualWidth = svgRef.current?.clientWidth || width;
      const actualHeight = svgRef.current?.clientHeight || height;

      // Fit on connected nodes only (the main cluster) — outlier service nodes
      // are accessible via pan/zoom but shouldn't shrink the main view
      const fitNodes = nodes.filter((n) => connectedIds.has(n.id));
      const targetNodes = fitNodes.length > 2 ? fitNodes : nodes;

      const xs = targetNodes.map((n) => n.x ?? 0);
      const ys = targetNodes.map((n) => n.y ?? 0);
      const pad = 90;
      const minX = Math.min(...xs) - pad;
      const maxX = Math.max(...xs) + pad;
      const minY = Math.min(...ys) - pad;
      const maxY = Math.max(...ys) + pad;
      const bboxWidth = maxX - minX;
      const bboxHeight = maxY - minY;

      // Guard against zero-area bounding boxes (no nodes, or all at same position)
      if (bboxWidth <= 0 || bboxHeight <= 0 || !isFinite(bboxWidth) || !isFinite(bboxHeight)) return;

      const scale = Math.max(
        0.5, // Never zoom out below 0.5 — keeps nodes readable
        Math.min(
          actualWidth / bboxWidth,
          actualHeight / bboxHeight,
          1.4 // Don't zoom in too much
        ) * 0.88 // Leave some breathing room
      );

      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const tx = actualWidth / 2 - cx * scale;
      const ty = actualHeight / 2 - cy * scale;

      // Guard against NaN from degenerate calculations
      if (!isFinite(tx) || !isFinite(ty) || !isFinite(scale)) return;

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
    }, 300); // Simulation is pre-warmed, just need a short delay for DOM

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
    const containerWidth = tooltip.containerWidth || 800;

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
          <div className="flex items-center gap-2.5 mb-1.5">
            <svg width="14" height="14" viewBox="0 0 14 14">
              <circle cx="7" cy="7" r="6" fill="#52525b" fillOpacity="0.55" stroke="none" />
              <circle cx="7" cy="7" r="6" fill="none" stroke="#52525b" strokeWidth="1.5" strokeDasharray="3,2" />
            </svg>
            <span className="text-xs text-muted-foreground">Pod Neighbor</span>
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
              {selectedNode.username && (
                <p className="text-[11px] text-muted-foreground">
                  @{selectedNode.username}
                </p>
              )}
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
  const isPodNeighbor = node.user_type === "pod_neighbor";
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
            {node.username && <p className="text-[11px] text-muted-foreground">@{node.username}</p>}
          </div>

          {/* User type badge */}
          <span
            className="flex-shrink-0 text-[10px] font-semibold uppercase px-2 py-0.5 rounded-md"
            style={{
              backgroundColor: isService
                ? `${SERVICE_COLOR}20`
                : isPodNeighbor
                  ? `${POD_NEIGHBOR_COLOR}30`
                  : `${PERSON_COLOR_FALLBACK}20`,
              color: isService
                ? SERVICE_COLOR
                : isPodNeighbor
                  ? "#a1a1aa"
                  : PERSON_COLOR_FALLBACK,
            }}
          >
            {isService ? "Service" : isPodNeighbor ? "Pod" : "Person"}
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
