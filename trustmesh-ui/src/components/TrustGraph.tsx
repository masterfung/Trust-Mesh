"use client";

import { useEffect, useRef } from "react";
import * as d3 from "d3";
import type { GraphData } from "@/lib/api";

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

interface SimNode extends d3.SimulationNodeDatum {
  id: string;
  username: string;
  display_name: string;
  bio: string;
}

interface SimLink extends d3.SimulationLinkDatum<SimNode> {
  type: string;
}

export function TrustGraph({ data }: { data: GraphData }) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || !data) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    const g = svg.append("g");

    // Zoom
    svg.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on("zoom", (event) => g.attr("transform", event.transform))
    );

    // Prepare data
    const nodes: SimNode[] = data.nodes.map((n) => ({ ...n }));
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
        d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(140)
      )
      .force("charge", d3.forceManyBody().strength(-500))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide(55));

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
          points.push([x - 40, y - 40]);
          points.push([x + 40, y - 40]);
          points.push([x - 40, y + 40]);
          points.push([x + 40, y + 40]);
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
            .attr("stroke-dasharray", "6,4")
            .attr("rx", 12);

          // Network label
          const cx = d3.mean(memberNodes, (n) => n.x) ?? 0;
          const cy = (d3.min(memberNodes, (n) => n.y) ?? 0) - 55;
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
      .attr("stroke", "#3f3f46")
      .attr("stroke-width", 1.5)
      .attr("stroke-opacity", 0.5);

    // Node groups
    const node = g
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .call(
        d3.drag<any, SimNode>()
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
      );

    // Node circles with glow
    node
      .append("circle")
      .attr("r", 26)
      .attr("fill", (d) => USER_COLORS[d.username] || "#6b7280")
      .attr("stroke", "#09090b")
      .attr("stroke-width", 3)
      .style("filter", "drop-shadow(0 0 6px rgba(99, 102, 241, 0.15))");

    // Node labels (initials)
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", "white")
      .attr("font-size", "12px")
      .attr("font-weight", "bold")
      .attr("font-family", "system-ui, sans-serif")
      .text((d) => d.display_name.split(" ").map((w) => w[0]).join(""));

    // Name labels below
    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "42px")
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

    return () => { simulation.stop(); };
  }, [data]);

  return (
    <div className="relative w-full" style={{ height: "calc(100vh - 80px)" }}>
      <svg ref={svgRef} className="w-full h-full" />

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-card/95 backdrop-blur-sm border border-card-border rounded-2xl p-4 shadow-lg">
        <p className="text-xs font-semibold text-muted-foreground mb-3">Networks</p>
        {data.networks.map((n) => (
          <div key={n.id} className="flex items-center gap-2.5 mb-1.5">
            <div
              className="w-3 h-3 rounded-sm"
              style={{ backgroundColor: NETWORK_COLORS[n.network_type] || NETWORK_COLORS.custom }}
            />
            <span className="text-xs text-muted-foreground">{n.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
