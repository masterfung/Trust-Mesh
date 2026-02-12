"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import * as d3 from "d3";
import type { GraphData, QueryResult } from "@/lib/api";

const NETWORK_COLORS: Record<string, string> = {
  family: "#6366f1",
  team: "#a78bfa",
  friends: "#22c55e",
  custom: "#f59e0b",
};

const USER_COLORS: Record<string, string> = {
  peter: "#3b82f6",
  molly: "#a855f7",
  jane: "#ec4899",
  bill: "#22c55e",
  kyle: "#f97316",
};

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
  const gRef = useRef<SVGGElement | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const [selectedNode, setSelectedNode] = useState<SimNode | null>(null);
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

      const queryColor = "#6366f1"; // Indigo: outgoing question
      const replyColor = getQueryColor(decision, trustLevel);

      // === Phase 1: Query dot (indigo) from sender → receiver ===
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

      // === Phase 2: Reply dot (color-coded) from receiver → sender ===
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

    const g = svg.append("g");
    gRef.current = g.node();

    // Zoom
    svg.call(
      d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on("zoom", (event) => g.attr("transform", event.transform))
    );

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
      });

    // Outer glow ring (subtle)
    node
      .append("circle")
      .attr("r", 32)
      .attr("fill", "none")
      .attr("stroke", (d) => USER_COLORS[d.username] || "#6b7280")
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.2);

    // Node circles
    node
      .append("circle")
      .attr("r", 26)
      .attr("fill", (d) => USER_COLORS[d.username] || "#6b7280")
      .attr("stroke", "#09090b")
      .attr("stroke-width", 3)
      .style("filter", "url(#glow)");

    // Node labels (initials)
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", "white")
      .attr("font-size", "12px")
      .attr("font-weight", "bold")
      .attr("font-family", "system-ui, sans-serif")
      .text((d) =>
        d.display_name
          .split(" ")
          .map((w) => w[0])
          .join("")
      );

    // Name labels below
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "44px")
      .attr("fill", "#a1a1aa")
      .attr("font-size", "11px")
      .attr("font-family", "system-ui, sans-serif")
      .attr("font-weight", "500")
      .text((d) => d.display_name);

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

    // Process any queued animations after layout settles
    simulation.on("end", () => {
      const queue = animationQueueRef.current;
      animationQueueRef.current = [];
      for (const anim of queue) {
        animateQuery(anim.fromId, anim.toId, anim.decision, "public");
      }
    });

    return () => {
      simulation.stop();
    };
  }, [data, animateQuery]);

  return (
    <div className="relative w-full" style={{ height: "calc(100vh - 80px)" }}>
      <svg ref={svgRef} className="w-full h-full" />

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
            Query Flow
          </p>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-indigo-500" />
            <span className="text-xs text-muted-foreground">Question sent</span>
          </div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-green-500" />
            <span className="text-xs text-muted-foreground">Knowledge shared</span>
          </div>
          <div className="flex items-center gap-2.5 mb-1.5">
            <div className="w-3 h-3 rounded-full bg-yellow-500" />
            <span className="text-xs text-muted-foreground">Limited (public only)</span>
          </div>
          <div className="flex items-center gap-2.5">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <span className="text-xs text-muted-foreground">Blocked (Citadel)</span>
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
                backgroundColor:
                  USER_COLORS[selectedNode.username] || "#6b7280",
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
              <p className="text-[11px] text-muted">
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
