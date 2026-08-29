import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";

const colors = {
  person: "#f3c63f",
  phone: "#7fb7c9",
  account: "#d4866a",
  vehicle: "#9a8cc7",
  location: "#8da56f",
  organization: "#d69b5d",
  email: "#77a9d3",
  other: "#9da39a",
};

export function NetworkCanvas({ elements, filter, search, pathNodeIds, pathEdgeIds, centralityIds, showEdgeLabels, onSelect }) {
  const hostRef = useRef(null);
  const cyRef = useRef(null);

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const cy = cytoscape({
      container: hostRef.current,
      elements,
      minZoom: 0.42,
      maxZoom: 2.4,
      wheelSensitivity: 0.25,
      layout: { name: "cose", animate: false, padding: 70, nodeRepulsion: 420000, nodeOverlap: 36, idealEdgeLength: 165, edgeElasticity: 90, nestingFactor: 1.15, gravity: 0.1, componentSpacing: 130, numIter: 1800, randomize: true },
      style: [
        { selector: "node", style: { width: (node) => 48 + Math.min(Number(node.data("degree") || 0), 8) * 2, height: (node) => 48 + Math.min(Number(node.data("degree") || 0), 8) * 2, "background-color": (node) => colors[node.data("type")] || colors.other, "border-color": "#171917", "border-width": 4, label: "data(label)", color: "#f1eee5", "font-family": "Inter", "font-size": 10, "font-weight": 700, "min-zoomed-font-size": 9, "text-wrap": "ellipsis", "text-max-width": 110, "text-valign": "bottom", "text-margin-y": 9, "text-background-color": "#181a18", "text-background-opacity": 0.88, "text-background-padding": 3, "overlay-padding": 6, "overlay-color": "#f3c63f", "overlay-opacity": 0 } },
        { selector: "edge", style: { width: 1.25, opacity: 0.46, "curve-style": "bezier", "line-color": "#71776e", "target-arrow-color": "#71776e", "target-arrow-shape": "triangle", "arrow-scale": 0.62, label: "", color: "#d6d8d2", "font-family": "IBM Plex Mono", "font-size": 8, "min-zoomed-font-size": 8, "text-background-color": "#1d201d", "text-background-opacity": 0.96, "text-background-padding": 3 } },
        { selector: "edge.show-labels, edge.selected, edge.path", style: { label: "data(relation)", opacity: 0.95 } },
        { selector: "node.selected", style: { "border-color": "#f7f3e8", "border-width": 7, "overlay-opacity": 0.14 } },
        { selector: "edge.selected", style: { "line-color": "#f7f3e8", "target-arrow-color": "#f7f3e8", width: 4, opacity: 1, "z-index": 999 } },
        { selector: ".path", style: { "line-color": "#e34f44", "target-arrow-color": "#e34f44", width: 5, "z-index": 999 } },
        { selector: "node.path", style: { "border-color": "#e34f44", "border-width": 7 } },
        { selector: "node.central", style: { width: 78, height: 78, "border-color": "#f3c63f", "border-width": 7, "overlay-color": "#f3c63f", "overlay-opacity": 0.12, "z-index": 900 } },
        { selector: "node.central-rank-1", style: { width: 94, height: 94, "border-width": 9 } },
        { selector: "node.central-rank-2", style: { width: 86, height: 86 } },
        { selector: ".dim", style: { opacity: 0.12 } },
        { selector: ".context-dim", style: { opacity: 0.075 } },
      ],
    });
    cyRef.current = cy;
    cy.on("tap", "node, edge", (event) => {
      const item = event.target;
      cy.elements().removeClass("selected context-dim"); item.addClass("selected");
      if (item.isNode()) {
        cy.elements().addClass("context-dim");
        item.closedNeighborhood().removeClass("context-dim");
      }
      onSelect({ group: item.isNode() ? "node" : "edge", ...item.data() });
    });
    cy.on("tap", (event) => { if (event.target === cy) { cy.elements().removeClass("selected context-dim"); onSelect(null); } });
    return () => { cy.destroy(); cyRef.current = null; };
  }, [elements, onSelect]);

  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    cy.elements().removeClass("dim");
    const term = search.trim().toLowerCase();
    cy.nodes().forEach((node) => {
      const filterMismatch = filter !== "all" && node.data("type") !== filter;
      const searchMismatch = term && !String(node.data("label") || "").toLowerCase().includes(term) && !String(node.data("entity_type") || "").toLowerCase().includes(term);
      if (filterMismatch || searchMismatch) node.addClass("dim");
    });
    cy.edges().forEach((edge) => { if (edge.source().hasClass("dim") || edge.target().hasClass("dim")) edge.addClass("dim"); });
  }, [filter, search]);

  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    cy.edges().toggleClass("show-labels", showEdgeLabels);
  }, [showEdgeLabels]);

  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    cy.elements().removeClass("path");
    pathNodeIds.forEach((id) => cy.getElementById(id).addClass("path"));
    pathEdgeIds.forEach((id) => cy.getElementById(id).addClass("path"));
  }, [pathNodeIds, pathEdgeIds]);

  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    cy.nodes().removeClass("central central-rank-1 central-rank-2");
    centralityIds.forEach((id, index) => cy.getElementById(id).addClass(`central ${index === 0 ? "central-rank-1" : index === 1 ? "central-rank-2" : ""}`));
  }, [centralityIds]);

  return <div className="network-canvas" ref={hostRef} aria-label="Interactive reviewed evidence graph" />;
}
