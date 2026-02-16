# Demo: Peter on Claude Code (MCP)

Peter is logged in via the TrustMesh MCP server. He can ask his agent
questions directly through Claude Code.

## Prerequisites
- Peter logged in: `trustmesh login` (already done if MCP connected)
- MCP server running via `.mcp.json` config

## Demo Prompts for Claude Code

### 1. Grandma's Visit
Ask Claude Code:
> "Use TrustMesh to search my vault for information about Grandma Rose's upcoming visit. What do I need to prepare?"

Or:
> "Ask my TrustMesh agent: Grandma Rose is coming next week - what do I need to prepare for her stay?"

### 2. Check Connections
> "Show me my TrustMesh connections and trust networks"

### 3. Pod Status
> "Check my TrustMesh pod status and who I'm connected to"

## What Claude Code Will Do
- Call `search_vault` → finds Peter's visit prep notes
- Call `ask_agent` → triggers gossip to Molly's agent for care details
- Return combined info about house prep + medical care routine
