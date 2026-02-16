#!/usr/bin/env bash
# ============================================================================
# TrustMesh Full Demo — Run All Three Scenarios
# ============================================================================
# Usage: bash demo/demo-all.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              TrustMesh — Hackathon Demo                     ║"
echo "║     Trust-Aware Knowledge Sharing for Personal AI Agents    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "The Johnson Family scenario:"
echo "  Peter (dad) — electrician, CLI/terminal user"
echo "  Molly (mom) — project manager, UI user"
echo "  Bill (14)   — birthday boy, peanut allergy"
echo "  Jane (16)   — soccer player"
echo "  Grandma Rose (78) — visiting, complex medical needs"
echo ""
echo "Three demo scenarios:"
echo "  1. Grandma's Visit  — Peter prepares via agent gossip"
echo "  2. Birthday Party   — Molly discovers allergies, shares with Rose"
echo "  3. Car Accident     — Emergency health data access + family alerts"
echo ""

# Setup
echo "Setting up demo sessions..."
source "$SCRIPT_DIR/demo-setup.sh"
echo ""

read -p "Press Enter to start Demo 1: Grandma's Visit..."
bash "$SCRIPT_DIR/demo-1-grandma-visit.sh"
echo ""
read -p "Press Enter to continue to Demo 2: Birthday Party..."
bash "$SCRIPT_DIR/demo-2-birthday-allergies.sh"
echo ""
read -p "Press Enter to continue to Demo 3: Emergency..."
bash "$SCRIPT_DIR/demo-3-emergency.sh"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    Demo Complete!                            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "What you saw:"
echo "  - Agents gossip across trust boundaries to answer questions"
echo "  - Emergency UCAN tokens provide scoped, time-limited health access"
echo "  - Family gets instant notifications when emergency data is accessed"
echo "  - Full audit trail — who accessed what, when, and why"
echo "  - Private data stays private (journals, report cards, diaries)"
echo ""
echo "Try it yourself:"
echo "  UI:  http://localhost:3050 (login as molly)"
echo "  CLI: trustmesh agent chat"
echo "  MCP: Already connected in Claude Code"
