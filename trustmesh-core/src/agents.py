"""Sonnet 4.5 personal agent logic — the core intelligence layer.

Agents have two modes:
- Cross-query (read-only): Another user asks your agent. Agent reasons about
  what to share based on trust level. No tools.
- Self-query (tool-enabled): You talk to your own agent. Agent can search your
  vault, create capsules, update capsules. Smart dedup via search-before-save.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.model_router import get_router
from src.models import Agent, AgentTask, KnowledgeCapsule, Network, Notification

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Tool Definitions (for self-query mode)
# ═══════════════════════════════════════════════════════════════

AGENT_TOOLS = [
    {
        "name": "search_vault",
        "description": (
            "Search the owner's knowledge vault for existing capsules related to a topic. "
            "ALWAYS call this before saving new information to check for duplicates or "
            "existing capsules that should be updated instead of creating new ones."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to find related capsules (e.g., 'Peter allergies', 'grandma medications', 'work schedule')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_capsule",
        "description": (
            "Save new knowledge to the vault OR update an existing capsule. "
            "If existing_capsule_id is provided, updates that capsule (replaces content). "
            "Otherwise creates a new capsule. The agent should intelligently classify "
            "the type, tier, category, and freshness based on the content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Short descriptive title. Include the person's name if the info is "
                        "about someone else (e.g., \"Peter's Shellfish Allergy\", "
                        "\"Grandma Rose's Medications\")"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "The knowledge content to save. Be clear and specific.",
                },
                "capsule_type": {
                    "type": "string",
                    "enum": ["memory", "skill", "procedure", "schedule", "preference", "contact"],
                    "description": (
                        "Type: memory (events/observations), skill (expertise/how-to), "
                        "procedure (step-by-step instructions), schedule (time-based events), "
                        "preference (likes, dislikes, allergies, dietary — note: 'hate' = dislike, NOT allergy), "
                        "contact (people/phone/email)"
                    ),
                },
                "visibility": {
                    "type": "string",
                    "enum": ["private", "internal", "shareable", "open"],
                    "description": (
                        "Visibility level: "
                        "private (owner only — diary entries, secrets), "
                        "internal (owner + trusted networks — family health info, work data), "
                        "shareable (explicitly shared with specific people, has expiry), "
                        "open (discoverable by anyone — professional bio). "
                        "Use category defaults: health→internal, personal→private, work→internal, general→open."
                    ),
                },
                "emergency_accessible": {
                    "type": "boolean",
                    "description": (
                        "Can verified healthcare providers access this via emergency UCAN tokens? "
                        "Default true for health category (allergies, medications, conditions). "
                        "Default false for everything else. Owner can override."
                    ),
                },
                "can_reshare": {
                    "type": "boolean",
                    "description": (
                        "Can someone who views this data share it with others? "
                        "Default false for health/personal, true for open/general. "
                        "When false, viewing agents say 'This is shared for your reference only.'"
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": ["health", "home", "work", "personal", "family", "general"],
                    "description": (
                        "Category: health (actual medical conditions, allergies, medications), "
                        "home (house/property), work (professional), personal (hobbies, dislikes, preferences), "
                        "family (family events/info), general (other). "
                        "IMPORTANT: food dislikes are 'personal', NOT 'health'. Only real allergies are 'health'."
                    ),
                },
                "freshness": {
                    "type": "string",
                    "enum": ["permanent", "temporary", "recurring"],
                    "description": (
                        "permanent (facts, skills — doesn't change), "
                        "temporary (events, locations — may expire), "
                        "recurring (schedules, routines — repeats)"
                    ),
                },
                "network_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Names of networks to share with (for network tier). "
                        "Must match exact network names from the owner's networks list."
                    ),
                },
                "existing_capsule_id": {
                    "type": "string",
                    "description": (
                        "If updating an existing capsule instead of creating new, provide its ID. "
                        "The content will REPLACE the old content. Use this when search_vault found "
                        "a related capsule that should be updated rather than duplicated."
                    ),
                },
            },
            "required": ["title", "content", "capsule_type", "visibility", "category", "freshness"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for real, current information. Use for finding services, "
            "prices, reviews, or any external data not in the vault."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "context": {
                    "type": "string",
                    "description": "Why you're searching — helps refine results",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "browse_web",
        "description": (
            "Browse a real website and extract structured data using an AI-powered browser. "
            "Use for: finding home care agencies, searching Kayak for flights, reading "
            "service listings, extracting pricing, or filling out forms on behalf of the user. "
            "Use a direct results URL when possible to skip navigation steps. "
            "Results are returned as JSON and optionally saved to the vault. "
            "Takes 60-120s — only call when real web data is needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to browse. Use a direct results URL when possible.",
                },
                "goal": {
                    "type": "string",
                    "description": "What to extract or do on the page. Be specific.",
                },
                "save_as_capsule": {
                    "type": "boolean",
                    "description": "If true, save result as a vault capsule. Default false.",
                },
                "capsule_title": {
                    "type": "string",
                    "description": "Title for the capsule if save_as_capsule is true.",
                },
                "capsule_visibility": {
                    "type": "string",
                    "enum": ["private", "internal", "open"],
                    "description": "Visibility for saved capsule. Use 'internal' to share with trust network.",
                },
            },
            "required": ["url", "goal"],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create a trackable task for multi-step work. Use when research or "
            "comparison involves multiple steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title"},
                "description": {"type": "string", "description": "What needs to be done"},
                "task_type": {
                    "type": "string",
                    "enum": ["search", "compare", "compile", "follow_up"],
                    "description": "Type of task",
                },
            },
            "required": ["title", "description", "task_type"],
        },
    },
    {
        "name": "query_peer",
        "description": (
            "Ask another user's or service's agent a question. Trust rules apply — "
            "you can only get information your owner has access to."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_username": {
                    "type": "string",
                    "description": "Username of the person or service to query",
                },
                "question": {
                    "type": "string",
                    "description": "The question to ask their agent",
                },
                "reason": {
                    "type": "string",
                    "description": "Why you're asking — helps with context",
                },
            },
            "required": ["target_username", "question"],
        },
    },
    {
        "name": "request_quotes",
        "description": (
            "Send a quote request to service providers in the mesh. "
            "Returns structured quotes for comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service_type": {
                    "type": "string",
                    "description": "Type of service: 'cleaning', 'tutoring', 'handyman', etc.",
                },
                "requirements": {
                    "type": "string",
                    "description": "Detailed requirements for the quote",
                },
                "budget_hint": {
                    "type": "string",
                    "description": "Optional budget range",
                },
            },
            "required": ["service_type", "requirements"],
        },
    },
    {
        "name": "discover_agents",
        "description": (
            "Discover agents across the pod and federation by capability, specialty, or name. "
            "Returns agents with their trust level relative to the owner, pool membership, and skills. "
            "Use this when looking for specialists (doctors, tutors, services), people in specific pools, "
            "or to find who can help with a particular need. More powerful than list_connections — "
            "this searches ALL discoverable agents, not just direct connections."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — matches name, bio, skills (e.g., 'doctor', 'cleaning service', 'tutor')",
                },
                "capability": {
                    "type": "string",
                    "description": "Filter by skill category (e.g., 'medical', 'professional', 'education')",
                },
                "user_type": {
                    "type": "string",
                    "enum": ["person", "organization", "government"],
                    "description": "Filter by entity type",
                },
            },
        },
    },
    {
        "name": "list_connections",
        "description": (
            "List the owner's connections and their trust levels. "
            "Use this to know who you can query_peer and what networks you share. "
            "Call this BEFORE query_peer if you're unsure who to ask."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "list_services",
        "description": (
            "List available service providers in the mesh with their skills and descriptions. "
            "Use before request_quotes to know what services are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "discover_networks",
        "description": (
            "Discover public networks/groups the owner can join (music groups, neighborhood, "
            "hobby clubs, professional networks). Use when the owner asks about joining groups, "
            "communities, or social circles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "interest": {
                    "type": "string",
                    "description": "Optional interest filter (e.g., 'music', 'dance', 'coding', 'sports')",
                },
            },
        },
    },
    {
        "name": "check_calendar",
        "description": (
            "Check the owner's calendar for upcoming events. "
            "Use when asked about schedule, appointments, meetings, or 'what's on my calendar'. "
            "Returns events for the requested time range."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "time_range": {
                    "type": "string",
                    "enum": ["today", "tomorrow", "this_week", "next_week"],
                    "description": "Time range to check. Default: 'this_week'.",
                },
            },
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Draft an email and save it as a capsule. Use when the owner asks to "
            "compose, draft, or write an email to someone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient name or email",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    # ── Timeline / PodOS tools ──
    {
        "name": "create_timeline_entry",
        "description": (
            "Create a new entry in the PodOS timeline — a scheduled task, reminder, "
            "event-triggered action, or recurring check. The timeline engine ticks "
            "automatically and transitions entries through states."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Human-readable label for the entry (e.g., 'Check Peter's medication', 'Follow up with Dr. Lee')",
                },
                "category": {
                    "type": "string",
                    "description": "Category: health, personal, work, family, home, general",
                },
                "salience": {
                    "type": "number",
                    "description": "Priority 0.0–1.0 (0.9+ = urgent, 0.5 = normal, 0.2 = low)",
                },
                "trigger_type": {
                    "type": "string",
                    "enum": ["immediate", "time", "event", "cron"],
                    "description": "When to activate: 'immediate' (now), 'time' (at specific ms), 'event' (on event), 'cron' (recurring)",
                },
                "trigger_at_ms": {
                    "type": "integer",
                    "description": "For 'time' trigger: Unix ms when to activate. Example: 'in 5 minutes' = int(time.time()*1000) + 5*60*1000. Compute this from current time.",
                },
                "trigger_event_type": {
                    "type": "string",
                    "description": "For 'event' trigger: event type string (e.g., 'capsule.created', 'capsule.updated')",
                },
                "trigger_cron": {
                    "type": "string",
                    "description": "For 'cron' trigger: 5-field cron expression (e.g., '0 9 * * *' for 9 AM daily)",
                },
                "hook_prompt": {
                    "type": "string",
                    "description": "What you (the agent) should do when this entry activates. This will be dispatched back to you as a task.",
                },
            },
            "required": ["label", "category"],
        },
    },
    {
        "name": "list_timeline_entries",
        "description": (
            "List active and pending entries in the PodOS timeline. "
            "Shows what's currently happening and what's coming up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_state": {
                    "type": "string",
                    "enum": ["all", "active", "pending", "dormant", "failed"],
                    "description": "Filter by state. Default: 'all'",
                },
            },
        },
    },
    {
        "name": "complete_timeline_entry",
        "description": (
            "Mark a timeline entry as completed. Use when a task or reminder has been "
            "fulfilled and should be retired from the active timeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {
                    "type": "string",
                    "description": "UUID of the timeline entry to complete",
                },
            },
            "required": ["entry_id"],
        },
    },
    {
        "name": "check_timeline_state",
        "description": (
            "Get the overall state of the PodOS timeline engine — how many entries "
            "are active, pending, failed. Also shows any signals (warnings/alerts)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    # Emergency escalation
    {
        "name": "trigger_emergency",
        "description": (
            "Declare a medical emergency on behalf of the owner. "
            "Issues a 30-minute UCAN access token to Riverside Hospital for the owner's "
            "health capsules, and sends urgent notifications to the owner's family connections. "
            "Use when the owner indicates they are in immediate danger or medical distress. "
            "Do NOT wait for confirmation — act immediately when emergency language is detected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief description of the emergency (e.g., 'fell and cannot get up', 'chest pain')",
                },
            },
            "required": ["reason"],
        },
    },
    # Emergency QR beacon for inbound responders
    {
        "name": "generate_emergency_qr",
        "description": (
            "Generate a time-limited, cryptographically signed QR code URL that a "
            "first responder can scan to access the owner's emergency health data — "
            "NO login required on the responder's side. "
            "Use ONLY when an external party (EMT, nurse, physician) explicitly states "
            "the owner is unconscious, incapacitated, or cannot respond, AND "
            "identifies themselves with a healthcare role. "
            "The tool verifies the requester's organization against the TrustMesh "
            "agent registry: if verified as a medical org, the token is scoped to their "
            "role; if unverified, only minimal paramedic-level access is issued. "
            "The scan endpoint re-validates the org DID against the registry — "
            "unregistered requesters fail at scan time even if they have the URL. "
            "REFUSE if there is no clear emergency context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": ["paramedic", "er_nurse", "attending_physician"],
                    "description": (
                        "The responder's claimed role: 'paramedic' (EMT), 'er_nurse', or "
                        "'attending_physician'. Will be downgraded to 'paramedic' if the "
                        "org cannot be verified in the registry."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason for access (e.g. 'vehicle accident, patient unresponsive').",
                },
                "requester_org": {
                    "type": "string",
                    "description": (
                        "Name or partial name of the requester's hospital / EMS org "
                        "(e.g. 'Riverside Hospital', 'County EMS'). Used to look up their "
                        "DID in the TrustMesh registry for verification."
                    ),
                },
            },
            "required": ["role", "reason"],
        },
    },
    # Credential tools
    {
        "name": "list_credentials",
        "description": (
            "List the owner's stored credentials — names, services, and which tools "
            "they are scoped to. NEVER returns secret values. Use this to help the "
            "owner review what API keys/tokens/passwords they have stored."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "manage_credential",
        "description": (
            "Store, rotate, or deactivate a credential. "
            "When storing: the secret is encrypted immediately and NEVER echoed back. "
            "After storing, confirm 'Stored securely' — do not repeat or paraphrase the secret value. "
            "When deactivating: removes the credential from future use."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["store", "rotate", "deactivate"],
                    "description": (
                        "store: save a new credential (name + service + secret + scoped_tools). "
                        "rotate: replace the secret value for an existing credential (cred_id + new_secret). "
                        "deactivate: soft-delete a credential (cred_id)."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Friendly name (e.g. 'Stripe Production Key'). Required for store.",
                },
                "service": {
                    "type": "string",
                    "description": "Service hostname (e.g. 'stripe.com'). Required for store.",
                },
                "secret": {
                    "type": "string",
                    "description": (
                        "The secret value to store or rotate. "
                        "NEVER include this in any response text — only pass it to this tool."
                    ),
                },
                "scoped_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names allowed to use this credential (e.g. ['stripe_checkout']).",
                },
                "cred_id": {
                    "type": "string",
                    "description": "Credential ID. Required for rotate and deactivate.",
                },
                "expires_at": {
                    "type": "string",
                    "description": "Optional ISO 8601 expiry (e.g. '2026-12-31T00:00:00Z').",
                },
            },
            "required": ["action"],
        },
    },
    # Messaging tools
    {
        "name": "send_message",
        "description": (
            "Send an encrypted message to a connected or pool-member user. "
            "Works cross-pod via federation. Message is delivered to their inbox immediately. "
            "Only message users you have a connection with or share a pool with. "
            "Always confirm the recipient's username before sending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_username": {
                    "type": "string",
                    "description": "Recipient's username (e.g. 'dr_lee', 'kyle')",
                },
                "subject": {
                    "type": "string",
                    "description": "Subject line (max 200 chars)",
                },
                "body": {
                    "type": "string",
                    "description": "Message body text",
                },
                "expires_in_hours": {
                    "type": "integer",
                    "description": "Auto-expire after N hours (optional — omit for permanent)",
                },
            },
            "required": ["to_username", "subject", "body"],
        },
    },
    {
        "name": "send_connection_request",
        "description": (
            "Send a connection request to another user so you can query their agent "
            "and exchange messages. Use whenever the owner expresses intent to connect with, "
            "befriend, add, or follow someone — regardless of how they phrase it or what "
            "language they use. Requires their username. "
            "Include a short friendly note explaining why you'd like to connect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_username": {
                    "type": "string",
                    "description": "Username of the person to connect with (e.g. 'amy', 'dr_lee')",
                },
                "message": {
                    "type": "string",
                    "description": "Short message to the recipient explaining the connection request",
                },
                "relationship_type": {
                    "type": "string",
                    "description": "Optional: 'friend', 'colleague', 'family', 'neighbor', 'classmate'",
                },
            },
            "required": ["to_username", "message"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════
# Tool Context (passed to tool handlers)
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToolContext:
    """Everything the agent's tools need to execute."""
    db: object  # AsyncSession — typed as object to avoid import cycle
    vault_key: bytes
    owner_id: str
    owner_name: str
    networks: list[dict]  # [{id, name, network_type}]
    actions: list[dict] = field(default_factory=list)
    query_depth: int = 0  # Recursion guard for query_peer


# ═══════════════════════════════════════════════════════════════
# Tool Handlers
# ═══════════════════════════════════════════════════════════════

async def handle_search_vault(ctx: ToolContext, query: str) -> str:
    """Search the vault for capsules matching the query. Returns JSON summary."""
    from src import transit_bridge
    from src.embeddings import search_capsules

    from sqlalchemy import select

    # Get ALL capsule IDs for the owner (self-query = private access)
    result = await ctx.db.execute(
        select(KnowledgeCapsule.id).where(
            KnowledgeCapsule.owner_id == ctx.owner_id,
            KnowledgeCapsule.is_archived == False,  # noqa: E712
        )
    )
    all_ids = list(result.scalars().all())

    if not all_ids:
        return json.dumps({"found": 0, "capsules": [], "message": "Vault is empty."})

    # Semantic search
    matched_ids = search_capsules(query, all_ids, top_k=5)
    if not matched_ids:
        return json.dumps({"found": 0, "capsules": [], "message": "No matching capsules found."})

    # Load and decrypt matches
    result = await ctx.db.execute(
        select(KnowledgeCapsule).where(KnowledgeCapsule.id.in_(matched_ids))
    )
    capsules = result.scalars().all()

    matches = []
    for c in capsules:
        try:
            content = transit_bridge.decrypt_text(ctx.owner_id, c.content_encrypted)
        except Exception:
            content = "[Could not decrypt]"
        matches.append({
            "id": c.id,
            "title": c.title,
            "capsule_type": c.capsule_type,
            "visibility": c.visibility,
            "emergency_accessible": c.emergency_accessible,
            "category": c.category,
            "content": content[:500],  # Truncate for context window
        })

    return json.dumps({
        "found": len(matches),
        "capsules": matches,
        "message": f"Found {len(matches)} related capsule(s). Review them to decide whether to update an existing one or create new.",
    })


async def handle_save_capsule(ctx: ToolContext, params: dict) -> str:
    """Create or update a capsule in the vault. Returns confirmation JSON."""
    from src import transit_bridge
    from src.crypto import content_hash
    from src.embeddings import upsert_capsule_embedding
    from src.models import CapsuleNetworkAccess

    from sqlalchemy import select

    title = params["title"]
    content = params["content"]
    capsule_type = params["capsule_type"]
    # Support both old "tier" and new "visibility" from agent
    visibility = params.get("visibility") or params.get("tier", "private")
    # Map old tier names to new visibility names
    tier_to_vis = {"public": "open", "network": "internal", "private": "private"}
    visibility = tier_to_vis.get(visibility, visibility)
    emergency_accessible = params.get("emergency_accessible", False)
    can_reshare = params.get("can_reshare", False)
    category = params["category"]
    freshness = params["freshness"]
    network_names = params.get("network_names", [])
    existing_id = params.get("existing_capsule_id")

    # Apply category defaults if not explicitly set
    if category == "health" and not params.get("emergency_accessible"):
        emergency_accessible = True
    if visibility == "open" and not params.get("can_reshare"):
        can_reshare = True

    # Resolve network names to IDs
    network_ids = []
    resolved_network_names = []
    for name in network_names:
        for net in ctx.networks:
            if net["name"].lower() == name.lower():
                network_ids.append(net["id"])
                resolved_network_names.append(net["name"])
                break

    # If internal but no networks specified, default to first network
    if visibility == "internal" and not network_ids and ctx.networks:
        network_ids = [ctx.networks[0]["id"]]
        resolved_network_names = [ctx.networks[0]["name"]]

    if existing_id:
        # UPDATE existing capsule
        capsule = await ctx.db.get(KnowledgeCapsule, existing_id)
        if not capsule or capsule.owner_id != ctx.owner_id:
            return json.dumps({"success": False, "error": "Capsule not found or not owned by you."})

        old_title = capsule.title
        capsule.title = title
        capsule.content_encrypted = transit_bridge.encrypt_text(ctx.owner_id, content)
        capsule.content_hash = content_hash(content)
        capsule.capsule_type = capsule_type
        capsule.visibility = visibility
        capsule.emergency_accessible = emergency_accessible
        capsule.can_reshare = can_reshare
        capsule.category = category
        capsule.freshness = freshness

        # Update network access
        existing_na = await ctx.db.execute(
            select(CapsuleNetworkAccess).where(CapsuleNetworkAccess.capsule_id == existing_id)
        )
        for na in existing_na.scalars().all():
            await ctx.db.delete(na)
        for nid in network_ids:
            ctx.db.add(CapsuleNetworkAccess(capsule_id=existing_id, network_id=nid))

        await ctx.db.flush()

        # Re-embed
        upsert_capsule_embedding(
            capsule.id,
            f"{title}: {content}",
            {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": visibility},
            category=category,
        )

        action = {
            "type": "capsule_updated",
            "capsule_id": capsule.id,
            "title": title,
            "old_title": old_title,
            "capsule_type": capsule_type,
            "visibility": visibility,
            "emergency_accessible": emergency_accessible,
            "category": category,
            "networks": resolved_network_names,
        }
        ctx.actions.append(action)

        return json.dumps({
            "success": True,
            "action": "updated",
            "capsule_id": capsule.id,
            "title": title,
            "message": f"Updated capsule '{title}' ({capsule_type}, {visibility}, {category})",
        })
    else:
        # CREATE new capsule
        capsule = KnowledgeCapsule(
            owner_id=ctx.owner_id,
            capsule_type=capsule_type,
            title=title,
            content_encrypted=transit_bridge.encrypt_text(ctx.owner_id, content),
            content_hash=content_hash(content),
            visibility=visibility,
            emergency_accessible=emergency_accessible,
            can_reshare=can_reshare,
            category=category,
            freshness=freshness,
        )
        ctx.db.add(capsule)
        await ctx.db.flush()

        # Add network access
        for nid in network_ids:
            ctx.db.add(CapsuleNetworkAccess(capsule_id=capsule.id, network_id=nid))

        await ctx.db.flush()

        # Embed for semantic search
        upsert_capsule_embedding(
            capsule.id,
            f"{title}: {content}",
            {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": visibility},
            category=category,
        )

        # Build governance summary for confirmation
        gov_notes = []
        if emergency_accessible:
            gov_notes.append("emergency-accessible")
        if can_reshare:
            gov_notes.append("reshare-allowed")
        gov_str = f" [{', '.join(gov_notes)}]" if gov_notes else ""

        action = {
            "type": "capsule_created",
            "capsule_id": capsule.id,
            "title": title,
            "capsule_type": capsule_type,
            "visibility": visibility,
            "emergency_accessible": emergency_accessible,
            "can_reshare": can_reshare,
            "category": category,
            "networks": resolved_network_names,
        }
        ctx.actions.append(action)

        return json.dumps({
            "success": True,
            "action": "created",
            "capsule_id": capsule.id,
            "title": title,
            "message": f"Created capsule '{title}' ({capsule_type}, {visibility}, {category}){gov_str}"
                       + (f" shared with {', '.join(resolved_network_names)}" if resolved_network_names else ""),
        })


async def handle_web_search(ctx: ToolContext, query: str, context: str = "") -> str:
    """Search the web via Tavily API. Returns top results."""
    try:
        from tavily import TavilyClient
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return json.dumps({
                "success": False,
                "error": "Web search is not configured on this pod (TAVILY_API_KEY missing). Tell the user: web search is not available on this pod.",
                "results": [],
            })
        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=5)
        results = []
        for r in response.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:300],
            })
        return json.dumps({
            "success": True,
            "query": query,
            "results": results,
            "result_count": len(results),
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "results": []})


async def handle_browse_web(ctx: ToolContext, params: dict) -> str:
    """Browse a real website and extract structured data via TinyFish."""
    import asyncio
    import aiohttp

    api_key = os.getenv("TINYFISH_API_KEY", "")
    if not api_key:
        return json.dumps({
            "success": False,
            "error": "Web browsing unavailable (TINYFISH_API_KEY not configured)",
        })

    url = params["url"]
    goal = params["goal"]
    save_as_capsule = params.get("save_as_capsule", False)
    capsule_title = params.get("capsule_title", "")
    capsule_visibility = params.get("capsule_visibility", "private")

    endpoint = "https://agent.tinyfish.ai/v1/automation/run-sse"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    steps = []
    result_data = None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                headers=headers,
                json={"url": url, "goal": goal},
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    return json.dumps({"success": False, "error": f"HTTP {resp.status}: {body[:200]}"})

                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("type", "")
                        if event_type == "PROGRESS":
                            purpose = event.get("purpose", "")
                            steps.append(purpose)
                            log.info("browse_web [%s] step: %s", url[:50], purpose[:80])
                        elif event_type == "COMPLETE":
                            result_data = event.get("resultJson") or event.get("result")
                        elif event_type == "ERROR":
                            return json.dumps({
                                "success": False,
                                "error": event.get("message", "TinyFish error"),
                                "steps": steps,
                            })
                    except json.JSONDecodeError:
                        pass

    except asyncio.TimeoutError:
        return json.dumps({
            "success": False,
            "error": "Browse timed out after 180s. Try a more direct URL or simpler goal.",
            "steps_completed": steps,
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

    if result_data is None:
        return json.dumps({
            "success": False,
            "error": "No result returned from browser.",
            "steps_completed": steps,
        })

    # Optionally save result as a vault capsule
    saved_capsule_id = None
    if save_as_capsule and capsule_title:
        try:
            content = json.dumps(result_data) if not isinstance(result_data, str) else result_data
            save_params = {
                "title": capsule_title,
                "content": content,
                "capsule_type": "memory",
                "visibility": capsule_visibility,
                "category": "research",
            }
            save_result_str = await handle_save_capsule(ctx, save_params)
            save_result = json.loads(save_result_str)
            if save_result.get("success"):
                saved_capsule_id = save_result.get("capsule_id")
        except Exception as e:
            log.warning("browse_web: failed to save capsule: %s", e)

    return json.dumps({
        "success": True,
        "url": url,
        "steps_taken": len(steps),
        "result": result_data,
        **({"saved_capsule_id": saved_capsule_id} if saved_capsule_id else {}),
    })


async def handle_create_task(ctx: ToolContext, params: dict) -> str:
    """Create a trackable agent task."""
    from sqlalchemy import select

    task = AgentTask(
        owner_id=ctx.owner_id,
        title=params["title"],
        description=params["description"],
        task_type=params["task_type"],
        status="in_progress",
    )
    ctx.db.add(task)
    await ctx.db.flush()

    ctx.actions.append({
        "type": "task_created",
        "task_id": task.id,
        "title": task.title,
        "task_type": task.task_type,
    })

    return json.dumps({
        "success": True,
        "task_id": task.id,
        "title": task.title,
        "message": f"Created task: {task.title}",
    })


async def handle_discover_agents(ctx: ToolContext, params: dict) -> str:
    """Discover agents by capability, name, or type. Returns agents with trust levels."""
    from sqlalchemy import select
    from src.models import User, Connection, NetworkMembership
    from src.trust import resolve_trust_level
    from src.models import parse_profile_data

    query_text = params.get("query", "").lower()
    capability = params.get("capability", "").lower()
    user_type_filter = params.get("user_type")

    # Build query for discoverable users (exclude self)
    stmt = (
        select(User)
        .where(User.is_discoverable == True)  # noqa: E712
        .where(User.id != ctx.owner_id)
        .order_by(User.display_name)
    )
    if user_type_filter:
        types = [user_type_filter]
        if user_type_filter == "organization":
            types.append("service")  # backward compat
        stmt = stmt.where(User.user_type.in_(types))

    result = await ctx.db.execute(stmt)
    users = result.scalars().all()

    agents = []
    for user in users:
        profile = parse_profile_data(user.profile_data) or {}
        skills = profile.get("skills", [])

        # Text search filter
        if query_text:
            searchable = f"{user.display_name} {user.bio} {user.username}".lower()
            for skill in skills:
                searchable += f" {skill.get('name', '')} {skill.get('category', '')}".lower()
            words = query_text.split()
            if not any(w in searchable for w in words):
                continue

        # Capability filter
        if capability:
            skill_cats = [s.get("category", "").lower() for s in skills]
            skill_names = [s.get("name", "").lower() for s in skills]
            if not any(capability in c for c in skill_cats + skill_names):
                continue

        # Resolve trust level
        trust_level, shared_nets = await resolve_trust_level(ctx.db, ctx.owner_id, user.id)
        network_names = [n.name for n in shared_nets]

        # Get pool memberships (only show public networks to prevent leaking private pool info)
        net_result = await ctx.db.execute(
            select(Network.name)
            .join(NetworkMembership, NetworkMembership.network_id == Network.id)
            .where(
                NetworkMembership.user_id == user.id,
                Network.is_public == True,  # noqa: E712
            )
        )
        pools = list(net_result.scalars().all())

        agents.append({
            "username": user.username,
            "display_name": user.display_name,
            "bio": user.bio[:200],
            "user_type": user.user_type,
            "trust_level": trust_level,
            "shared_networks": network_names,
            "pools": pools,
            "skills": [{"name": s.get("name", ""), "category": s.get("category", "")} for s in skills[:5]],
            "recommended": trust_level == "network",
        })

    # Sort: recommended (pool-sharing) agents first, then alphabetically
    agents.sort(key=lambda a: (not a["recommended"], a["display_name"]))

    ctx.actions.append({
        "type": "agents_discovered",
        "query": query_text or capability or user_type_filter or "all",
        "results_count": len(agents),
    })

    return json.dumps({
        "success": True,
        "agents": agents[:20],  # Limit to top 20
        "total": len(agents),
        "tip": "Agents marked 'recommended' share pools with you and will share more. Use query_peer to ask any agent a question.",
    })


MAX_QUERY_DEPTH = 2  # Prevent infinite agent-to-agent recursion


async def handle_query_peer(ctx: ToolContext, params: dict) -> str:
    """Query another user's agent. Full trust pipeline enforced.

    Three-path lookup:
    1. Local real user — fast path via local gossip
    2. Ghost user (is_remote=True) — route through federation to their real pod
    3. Peer fallback — try each connected peer pod
    """
    if ctx.query_depth >= MAX_QUERY_DEPTH:
        return json.dumps({"success": False, "error": "Query depth limit reached — cannot nest further agent queries."})

    from sqlalchemy import select
    from src.models import Agent, PeerPod, User

    target_username = params["target_username"]
    question = params["question"]

    # Resolve to a User: exact username match first, then display-name substring.
    # This handles Gemini calling with "Dr. Lee" instead of the canonical "dr_lee".
    result = await ctx.db.execute(
        select(User).where(User.username == target_username)
    )
    target_user = result.scalar_one_or_none()
    if not target_user:
        # Case-insensitive display name fallback (e.g. "Dr. Lee" → dr_lee)
        from sqlalchemy import func
        result2 = await ctx.db.execute(
            select(User).where(
                func.lower(User.display_name).contains(target_username.lower().replace(".", ""))
            ).limit(1)
        )
        target_user = result2.scalar_one_or_none()
        if target_user:
            log.debug("query_peer: resolved display-name %r → username %r", target_username, target_user.username)

    # ── Path 1: Local real user (unchanged fast path) ──
    if target_user and not target_user.is_remote:
        from src.gossip import query_agent

        query_result = await query_agent(
            db=ctx.db,
            from_user_id=ctx.owner_id,
            to_user_id=target_user.id,
            question=question,
            query_depth=ctx.query_depth + 1,
        )

        trust_level = query_result.get("trust_level", "unknown")

        ctx.actions.append({
            "type": "peer_queried",
            "target_username": target_username,
            "target_display_name": target_user.display_name,
            "question": question[:100],
            "decision": query_result.get("decision", "unknown"),
            "trust_level": trust_level,
        })
        trust_explanation = {
            "private": "Full access (self-query)",
            "network": f"Trusted — you share networks: {', '.join(query_result.get('shared_networks', []))}",
            "connected": "Connected — you have a direct connection but no shared pools. Only open information visible, but they know who you are.",
            "public": "Limited access — only public/open information visible. Connect with them or join a shared pool for more access.",
        }.get(trust_level, "Unknown trust level")

        return json.dumps({
            "success": True,
            "target": target_username,
            "target_display_name": target_user.display_name,
            "target_type": target_user.user_type,
            "trust_level": trust_level,
            "trust_explanation": trust_explanation,
            "shared_networks": query_result.get("shared_networks", []),
            "response": query_result.get("response", "No response"),
            "decision": query_result.get("decision", "unknown"),
        })

    # ── Path 2: Ghost user — route through federation ──
    if target_user and target_user.is_remote:
        from src.federation import remote_query

        # Get our agent's DID
        agent_result = await ctx.db.execute(
            select(Agent).where(Agent.owner_id == ctx.owner_id)
        )
        our_agent = agent_result.scalar_one_or_none()
        our_did = our_agent.did if our_agent else "unknown"
        signing_key: bytes | None = None
        if our_agent and our_agent.encrypted_private_key:
            from src import transit_bridge
            try:
                signing_key = transit_bridge.decrypt(ctx.owner_id, our_agent.encrypted_private_key)
            except Exception:
                signing_key = None

        # Extract real username from ghost format "remote:username@host"
        real_username = target_username
        if real_username.startswith("remote:"):
            real_username = real_username[7:]  # strip "remote:"
            if "@" in real_username:
                real_username = real_username.split("@")[0]

        remote_result = await remote_query(
            target_user.remote_pod_url, our_did, real_username, question, signing_private_key=signing_key
        )

        ctx.actions.append({
            "type": "peer_queried",
            "target_username": target_username,
            "target_display_name": target_user.display_name,
            "question": question[:100],
            "decision": remote_result.get("decision", "unknown") if remote_result else "unreachable",
            "trust_level": remote_result.get("trust_level", "public") if remote_result else "public",
            "federated": True,
            "remote_pod": target_user.remote_pod_url,
        })

        if remote_result:
            remote_pod_name = remote_result.get("pod_name", "")
            return json.dumps({
                "success": True,
                "target": target_username,
                "target_display_name": target_user.display_name,
                "target_type": target_user.user_type,
                "trust_level": remote_result.get("trust_level", "public"),
                "trust_explanation": f"Federated query to {remote_pod_name or target_user.remote_pod_url}",
                "shared_networks": remote_result.get("shared_networks", []),
                "response": remote_result.get("response", "No response"),
                "decision": remote_result.get("decision", "unknown"),
                "federated": True,
                "remote_pod": target_user.remote_pod_url,
                "remote_pod_name": remote_pod_name,
            })
        return json.dumps({
            "success": False,
            "error": f"Remote pod {target_user.remote_pod_url} is unreachable",
            "federated": True,
        })

    # ── Path 3: Peer fallback — user not found locally, try peers ──
    from src.federation import remote_query

    agent_result = await ctx.db.execute(
        select(Agent).where(Agent.owner_id == ctx.owner_id)
    )
    our_agent = agent_result.scalar_one_or_none()
    our_did = our_agent.did if our_agent else "unknown"
    signing_key: bytes | None = None
    if our_agent and our_agent.encrypted_private_key:
        from src import transit_bridge
        try:
            signing_key = transit_bridge.decrypt(ctx.owner_id, our_agent.encrypted_private_key)
        except Exception:
            signing_key = None

    peers_result = await ctx.db.execute(
        select(PeerPod).where(PeerPod.status == "active")
    )
    peers = peers_result.scalars().all()

    for peer in peers:
        remote_result = await remote_query(peer.url, our_did, target_username, question, signing_private_key=signing_key)
        if remote_result:
            ctx.actions.append({
                "type": "peer_queried",
                "target_username": target_username,
                "target_display_name": target_username,  # Don't know display name for remote
                "question": question[:100],
                "decision": remote_result.get("decision", "unknown"),
                "trust_level": remote_result.get("trust_level", "public"),
                "federated": True,
                "remote_pod": peer.url,
            })
            return json.dumps({
                "success": True,
                "target": target_username,
                "target_display_name": target_username,  # Don't know display name for remote
                "target_type": "unknown",
                "trust_level": remote_result.get("trust_level", "public"),
                "trust_explanation": f"Federated query to {peer.url} (public trust — no pool relationship)",
                "shared_networks": [],
                "response": remote_result.get("response", "No response"),
                "decision": remote_result.get("decision", "unknown"),
                "federated": True,
                "remote_pod": peer.url,
            })

    return json.dumps({
        "success": False,
        "error": f"User '{target_username}' not found locally or on any connected peer pod",
    })


async def handle_request_quotes(ctx: ToolContext, params: dict) -> str:
    """Request quotes from service providers matching the service type."""
    from sqlalchemy import select
    from src.models import User
    from src.gossip import query_agent

    service_type = params["service_type"]
    requirements = params["requirements"]
    budget_hint = params.get("budget_hint", "")

    # Find service agents matching the type
    result = await ctx.db.execute(
        select(User).where(User.user_type.in_(["service", "organization"]))
    )
    service_users = result.scalars().all()

    # Filter by relevance to service_type (check bio/name for keywords)
    keywords = service_type.lower().split()
    matching_services = []
    for su in service_users:
        text = f"{su.display_name} {su.bio}".lower()
        if any(kw in text for kw in keywords):
            matching_services.append(su)

    if not matching_services:
        # Also do a web search as fallback
        web_results = await handle_web_search(ctx, f"{service_type} services near me {requirements}")
        return json.dumps({
            "success": True,
            "mesh_quotes": [],
            "web_results": json.loads(web_results).get("results", []),
            "message": f"No {service_type} providers in the mesh. Found web results instead.",
        })

    # Query each matching service agent
    quotes = []
    for service in matching_services:
        quote_question = (
            f"I need a quote for: {requirements}."
            + (f" Budget: {budget_hint}." if budget_hint else "")
            + " Please provide pricing details, availability, and any relevant info."
        )
        try:
            qr = await query_agent(
                db=ctx.db,
                from_user_id=ctx.owner_id,
                to_user_id=service.id,
                question=quote_question,
            )
            quotes.append({
                "provider": service.display_name,
                "username": service.username,
                "response": qr.get("response", "No response"),
                "trust_level": qr.get("trust_level", "public"),
                "in_mesh": True,
            })

            # Notification for service owner
            notification = Notification(
                user_id=service.id,
                notification_type="quote_received",
                title=f"Quote request from {ctx.owner_name}",
                body=f"Service: {service_type}. Requirements: {requirements[:200]}",
                related_id=qr.get("id"),
            )
            ctx.db.add(notification)
        except Exception as e:
            log.warning(f"Quote request to {service.username} failed: {e}")
            quotes.append({
                "provider": service.display_name,
                "username": service.username,
                "response": "Unable to get quote from this provider at the moment.",
                "in_mesh": True,
            })

    await ctx.db.flush()

    ctx.actions.append({
        "type": "quotes_requested",
        "service_type": service_type,
        "providers_queried": len(quotes),
    })

    return json.dumps({
        "success": True,
        "mesh_quotes": quotes,
        "message": f"Got quotes from {len(quotes)} in-mesh provider(s).",
    })


async def handle_list_connections(ctx: ToolContext) -> str:
    """List the owner's connections with trust info."""
    from sqlalchemy import select, or_
    from src.models import Connection, NetworkMembership, User

    result = await ctx.db.execute(
        select(Connection).where(
            or_(Connection.from_user_id == ctx.owner_id, Connection.to_user_id == ctx.owner_id)
        )
    )
    # Build a set of network IDs the owner belongs to (from ctx.networks dicts)
    my_network_ids = {n["id"] for n in ctx.networks} if ctx.networks else set()

    connections = []
    for c in result.scalars().all():
        other_id = c.to_user_id if c.from_user_id == ctx.owner_id else c.from_user_id
        other = await ctx.db.get(User, other_id)
        if other:
            # Find shared networks by checking the other user's memberships
            shared_nets = []
            if my_network_ids:
                mem_result = await ctx.db.execute(
                    select(NetworkMembership.network_id).where(
                        NetworkMembership.user_id == other_id,
                        NetworkMembership.network_id.in_(my_network_ids),
                    )
                )
                shared_net_ids = set(mem_result.scalars().all())
                shared_nets = [n["name"] for n in ctx.networks if n["id"] in shared_net_ids]
            is_from = c.from_user_id == ctx.owner_id
            my_label = c.from_label if is_from else c.to_label
            connections.append({
                "username": other.username,
                "display_name": other.display_name,
                "user_type": other.user_type or "person",
                "relationship_type": c.relationship_type,
                "my_label": my_label,
                "shared_networks": shared_nets,
            })
    return json.dumps({"connections": connections, "count": len(connections)})


async def handle_list_services(ctx: ToolContext) -> str:
    """List available service providers in the mesh."""
    from sqlalchemy import select
    from src.models import User

    result = await ctx.db.execute(
        select(User).where(User.user_type.in_(["service", "organization"]))
    )
    services = []
    for s in result.scalars().all():
        # profile_data is stored as a JSON string in the Text column
        from src.models import parse_profile_data
        profile = parse_profile_data(s.profile_data) or {}
        services.append({
            "username": s.username,
            "display_name": s.display_name,
            "bio": s.bio,
            "skills": profile.get("skills", []),
        })
    return json.dumps({"services": services, "count": len(services)})


async def handle_discover_networks(ctx: ToolContext, interest: str = "") -> str:
    """Discover public networks the owner can join."""
    from sqlalchemy import func, select
    from src.models import Network, NetworkMembership, User

    # Get networks the owner already belongs to
    my_nets = await ctx.db.execute(
        select(NetworkMembership.network_id).where(NetworkMembership.user_id == ctx.owner_id)
    )
    my_network_ids = set(my_nets.scalars().all())

    # Get all public networks
    result = await ctx.db.execute(
        select(Network).where(Network.is_public == True).order_by(Network.name)  # noqa: E712
    )
    networks = result.scalars().all()

    discoverable = []
    for n in networks:
        if n.id in my_network_ids:
            continue  # Skip networks owner already belongs to
        # Filter by interest if provided
        if interest:
            text = f"{n.name} {n.description} {n.network_type}".lower()
            if not any(kw in text for kw in interest.lower().split()):
                continue
        # Get member count
        mem_count_result = await ctx.db.execute(
            select(func.count(NetworkMembership.id)).where(NetworkMembership.network_id == n.id)
        )
        member_count = mem_count_result.scalar() or 0
        owner = await ctx.db.get(User, n.owner_id)
        discoverable.append({
            "id": n.id,
            "name": n.name,
            "description": n.description,
            "network_type": n.network_type,
            "join_policy": n.join_policy,
            "member_count": member_count,
            "owner": owner.display_name if owner else "Unknown",
        })

    if not discoverable:
        return json.dumps({
            "networks": [],
            "message": f"No public networks found{' matching ' + repr(interest) if interest else ''}. The owner could create their own!",
        })

    return json.dumps({
        "networks": discoverable,
        "count": len(discoverable),
        "message": f"Found {len(discoverable)} public network(s) the owner can join.",
    })


# ═══════════════════════════════════════════════════════════════
# Mock Calendar & Email (same interface real OAuth/MCP would use)
# ═══════════════════════════════════════════════════════════════

MOCK_CALENDARS: dict[str, list[dict]] = {
    "molly": [
        {"time": "9:00 AM", "title": "Team Standup", "location": "Zoom", "day": "today", "recurring": True},
        {"time": "11:00 AM", "title": "1:1 with Kyle", "location": "Conference Room B", "day": "today"},
        {"time": "2:00 PM", "title": "Q4 Planning Review", "location": "Main Board Room", "day": "today"},
        {"time": "6:00 PM", "title": "Pick up Jane from soccer", "location": "Roosevelt Field", "day": "today"},
        {"time": "10:00 AM", "title": "Sprint Retrospective", "location": "Zoom", "day": "tomorrow"},
        {"time": "3:00 PM", "title": "Dentist — Jane", "location": "Dr. Kim's Office", "day": "tomorrow"},
        {"time": "All day", "title": "Flight to Austin — SRE Conference", "location": "SFO → AUS", "day": "this_week"},
        {"time": "7:00 PM", "title": "Visit Grandma Rose", "location": "Sunrise Assisted Living", "day": "this_week"},
    ],
    "peter": [
        {"time": "8:30 AM", "title": "Client Sync — Martinez Account", "location": "Office", "day": "today"},
        {"time": "12:00 PM", "title": "Lunch with Bill", "location": "Tony's Deli", "day": "today"},
        {"time": "4:00 PM", "title": "Jane's Piano Recital", "location": "Roosevelt Middle School", "day": "this_week"},
        {"time": "9:00 AM", "title": "Quarterly Review Prep", "location": "Home Office", "day": "tomorrow"},
        {"time": "6:30 PM", "title": "Dinner at Mom's", "location": "Sunrise Assisted Living", "day": "this_week"},
    ],
    "jane": [
        {"time": "3:30 PM", "title": "Soccer Practice", "location": "Roosevelt Field", "day": "today", "recurring": True},
        {"time": "4:00 PM", "title": "Piano Lesson", "location": "Ms. Chen's Studio", "day": "tomorrow"},
        {"time": "10:00 AM", "title": "SAT Practice Test", "location": "AceTutor Center", "day": "this_week"},
        {"time": "2:00 PM", "title": "Study Group — History", "location": "Library", "day": "this_week"},
    ],
    "bill": [
        {"time": "10:00 AM", "title": "Guitar Practice", "location": "Home", "day": "today"},
        {"time": "2:00 PM", "title": "Coding Club", "location": "School Lab", "day": "today", "recurring": True},
        {"time": "11:00 AM", "title": "Basketball Game", "location": "Community Center", "day": "this_week"},
    ],
    "dorothy": [
        {"time": "9:00 AM", "title": "Physical Therapy", "location": "Sunrise Wellness Center", "day": "today"},
        {"time": "11:00 AM", "title": "Bridge Club", "location": "Community Room", "day": "today", "recurring": True},
        {"time": "2:00 PM", "title": "Video Call with Harold", "location": "Room 204", "day": "tomorrow"},
        {"time": "10:00 AM", "title": "Dr. Patel — Checkup", "location": "Riverside General", "day": "this_week"},
    ],
    "kyle": [
        {"time": "9:00 AM", "title": "Team Standup", "location": "Zoom", "day": "today", "recurring": True},
        {"time": "11:00 AM", "title": "1:1 with Molly", "location": "Conference Room B", "day": "today"},
        {"time": "2:00 PM", "title": "Architecture Review — Auth Service", "location": "Zoom", "day": "tomorrow"},
        {"time": "5:00 PM", "title": "Board Game Night", "location": "Kyle's Place", "day": "this_week"},
    ],
}


async def handle_check_calendar(ctx: ToolContext, time_range: str = "this_week") -> str:
    """Return mock calendar events for the owner."""
    # Find the owner's username
    from sqlalchemy import select
    from src.models import User
    user = await ctx.db.execute(select(User.username).where(User.id == ctx.owner_id))
    username = user.scalar_one_or_none() or ""

    events = MOCK_CALENDARS.get(username, [])

    # Filter by time range
    range_order = {"today": 0, "tomorrow": 1, "this_week": 2, "next_week": 3}
    target = range_order.get(time_range, 2)
    filtered = [e for e in events if range_order.get(e["day"], 2) <= target]

    if not filtered:
        return json.dumps({
            "success": True,
            "events": [],
            "message": f"No events found for {time_range}.",
        })

    ctx.actions.append({"type": "calendar_checked", "time_range": time_range, "event_count": len(filtered)})

    return json.dumps({
        "success": True,
        "time_range": time_range,
        "events": filtered,
        "event_count": len(filtered),
        "message": f"Found {len(filtered)} event(s) for {time_range}.",
    })


async def handle_draft_email(ctx: ToolContext, params: dict) -> str:
    """Draft an email and save it as a capsule."""
    from src import transit_bridge
    from src.crypto import content_hash
    from src.embeddings import upsert_capsule_embedding

    to = params["to"]
    subject = params["subject"]
    body = params["body"]

    # Save as a capsule (draft)
    email_content = f"To: {to}\nSubject: {subject}\n\n{body}"
    capsule = KnowledgeCapsule(
        owner_id=ctx.owner_id,
        capsule_type="memory",
        title=f"Email Draft: {subject}",
        content_encrypted=transit_bridge.encrypt_text(ctx.owner_id, email_content),
        content_hash=content_hash(email_content),
        visibility="private",
        category="work",
        freshness="temporary",
    )
    ctx.db.add(capsule)
    await ctx.db.flush()

    upsert_capsule_embedding(
        capsule.id,
        f"Email Draft: {subject} to {to}: {body[:200]}",
        {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": "private"},
    )

    # Create notification
    notification = Notification(
        user_id=ctx.owner_id,
        notification_type="email_draft",
        title=f"Email draft saved: {subject}",
        body=f"To: {to}. Draft saved to your vault.",
        related_id=capsule.id,
    )
    ctx.db.add(notification)
    await ctx.db.flush()

    ctx.actions.append({
        "type": "email_drafted",
        "to": to,
        "subject": subject,
        "capsule_id": capsule.id,
    })

    return json.dumps({
        "success": True,
        "capsule_id": capsule.id,
        "to": to,
        "subject": subject,
        "message": f"Email draft to {to} saved to your vault. Subject: '{subject}'.",
    })


# ═══════════════════════════════════════════════════════════════
# Timeline Tool Handlers
# ═══════════════════════════════════════════════════════════════

async def handle_create_timeline_entry(ctx: ToolContext, inp: dict) -> str:
    """Create a timeline entry in the PodOS kernel."""
    try:
        from src.routes.timeline import _get_engine
        from src.timeline_bridge import (
            EntryBuilder,
            EntryState,
            EntryType,
            EventSource,
            HookActionKind,
            HookPhase,
            Visibility,
        )

        engine = _get_engine()
    except Exception:
        return json.dumps({"error": "Timeline engine not available"})

    import time as _time

    label = inp.get("label", "Unnamed entry")
    category = inp.get("category", "general")
    salience = inp.get("salience", 0.5)
    trigger_type = inp.get("trigger_type", "immediate")

    builder = (
        EntryBuilder()
        .set_label(label)
        .set_category(category)
        .set_salience(salience)
        .set_entry_type(EntryType.TASK)
    )

    # Configure trigger
    now_ms = int(_time.time() * 1000)
    if trigger_type == "time" and inp.get("trigger_at_ms"):
        builder.set_trigger_time(inp["trigger_at_ms"])
    elif trigger_type == "event" and inp.get("trigger_event_type"):
        builder.set_trigger_event(EventSource.SYSTEM, inp["trigger_event_type"])
    elif trigger_type == "cron" and inp.get("trigger_cron"):
        builder.set_trigger_cron(inp["trigger_cron"])
    elif trigger_type == "immediate":
        builder.set_trigger_time(now_ms - 1000)  # already past → fires on next tick

    # Add agent hook if prompt provided
    hook_prompt = inp.get("hook_prompt", "")
    if hook_prompt:
        builder.add_hook(
            action=HookActionKind.AGENT_TASK,
            phase=HookPhase.PRE,
            prompt=hook_prompt,
        )

    entry_id = engine.add_entry(builder)

    # Push event so other entries can react
    engine.push_event("timeline.entry_created", EventSource.AGENT)

    # Persist for crash/restart restore (best-effort).
    try:
        from src.routes.timeline import persist_entry_spec
        state_val = engine.get_entry_state(entry_id)

        act = {"kind": "manual"}
        if trigger_type == "time" and inp.get("trigger_at_ms"):
            act = {"kind": "time", "at_ms": int(inp["trigger_at_ms"])}
        elif trigger_type == "event" and inp.get("trigger_event_type"):
            act = {"kind": "event", "event_source": int(EventSource.SYSTEM), "event_type": str(inp["trigger_event_type"])}
        elif trigger_type == "cron" and inp.get("trigger_cron"):
            act = {"kind": "time", "cron": str(inp["trigger_cron"])}
        elif trigger_type == "immediate":
            act = {"kind": "time", "at_ms": int(now_ms - 1000)}

        spec = {
            "id": str(entry_id),
            "owner_id": ctx.owner_id,
            "label": label,
            "category": category,
            "entry_type": int(EntryType.TASK),
            "visibility": int(Visibility.PRIVATE),
            "salience": float(salience),
            "window_start_ms": None,
            "window_end_ms": None,
            "activation_trigger": act,
            "deactivation_trigger": None,
            "dependencies": [],
            "hooks": [{
                "action": int(HookActionKind.AGENT_TASK),
                "phase": int(HookPhase.PRE),
                "prompt": hook_prompt,
                "timeout_ms": 30000,
                "max_retries": 0,
            }] if hook_prompt else [],
        }
        persist_entry_spec(
            owner_id=ctx.owner_id,
            entry_id=entry_id,
            state=int(state_val) if state_val is not None else 0,
            spec=spec,
        )
    except Exception:
        pass

    ctx.actions.append({
        "type": "timeline_entry_created",
        "entry_id": str(entry_id),
        "label": label,
    })

    return json.dumps({
        "success": True,
        "entry_id": str(entry_id),
        "label": label,
        "category": category,
        "salience": salience,
        "trigger_type": trigger_type,
        "message": f"Timeline entry '{label}' created (id: {str(entry_id)[:8]}...). It will be processed by the engine.",
    })


async def handle_list_timeline_entries(ctx: ToolContext, filter_state: str = "all") -> str:
    """List entries from the timeline engine."""
    try:
        from src.routes.timeline import _get_engine
        from src.timeline_bridge import EntryState

        engine = _get_engine()
    except Exception:
        return json.dumps({"error": "Timeline engine not available"})

    ids = engine.get_all_entry_ids()
    entries = []
    for eid in ids:
        state_val = engine.get_entry_state(eid)
        if state_val is None:
            continue

        state_name = EntryState(state_val).name

        # Apply filter
        if filter_state != "all" and state_name.lower() != filter_state.lower():
            continue

        label = engine.get_entry_label(eid) or ""
        category = engine.get_entry_category(eid) or ""
        salience = engine.get_entry_salience(eid) or 0.0

        entries.append({
            "id": str(eid),
            "label": label,
            "category": category,
            "state": state_name,
            "salience": round(salience, 2),
        })

    # Sort by salience (highest first)
    entries.sort(key=lambda e: e["salience"], reverse=True)

    return json.dumps({
        "count": len(entries),
        "entries": entries[:20],  # Cap at 20
        "message": f"Found {len(entries)} timeline entries" + (f" (filter: {filter_state})" if filter_state != "all" else ""),
    })


async def handle_complete_timeline_entry(ctx: ToolContext, entry_id_str: str) -> str:
    """Transition a timeline entry to COMPLETED."""
    import uuid as _uuid
    try:
        from src.routes.timeline import _get_engine
        from src.timeline_bridge import EntryState, EventSource

        engine = _get_engine()
    except Exception:
        return json.dumps({"error": "Timeline engine not available"})

    try:
        eid = _uuid.UUID(entry_id_str)
    except ValueError:
        return json.dumps({"error": f"Invalid entry ID: {entry_id_str}"})

    state_val = engine.get_entry_state(eid)
    if state_val is None:
        return json.dumps({"error": f"Entry not found: {entry_id_str}"})

    label = engine.get_entry_label(eid) or ""
    current_state = EntryState(state_val)

    # Walk through valid transitions to reach COMPLETED
    try:
        if current_state == EntryState.ACTIVE:
            engine.transition_entry(eid, EntryState.DEACTIVATING)
            engine.transition_entry(eid, EntryState.COMPLETED)
        elif current_state == EntryState.DEACTIVATING:
            engine.transition_entry(eid, EntryState.COMPLETED)
        elif current_state in (EntryState.DORMANT, EntryState.PENDING, EntryState.ACTIVATING):
            # Can't complete from these states — archive instead
            engine.transition_entry(eid, EntryState.ARCHIVED)
        elif current_state == EntryState.COMPLETED:
            return json.dumps({"success": True, "message": f"Entry '{label}' is already completed."})
        else:
            return json.dumps({"error": f"Cannot complete entry in state {current_state.name}"})
    except RuntimeError as e:
        return json.dumps({"error": f"Transition failed: {e}"})

    engine.push_event("timeline.entry_completed", EventSource.AGENT)

    # Persist state update (best-effort).
    try:
        from src.routes.timeline import persist_update_state
        st = engine.get_entry_state(eid)
        if st is not None:
            persist_update_state(entry_id=eid, state=int(st))
    except Exception:
        pass

    ctx.actions.append({
        "type": "timeline_entry_completed",
        "entry_id": entry_id_str,
        "label": label,
    })

    return json.dumps({
        "success": True,
        "entry_id": entry_id_str,
        "label": label,
        "message": f"Timeline entry '{label}' marked as completed.",
    })


async def handle_check_timeline_state(ctx: ToolContext) -> str:
    """Get overall timeline engine state."""
    try:
        from src.routes.timeline import _get_engine

        engine = _get_engine()
    except Exception:
        return json.dumps({"error": "Timeline engine not available"})

    state = engine.state
    signals_summary = []
    for s in state.signals[:5]:
        signals_summary.append({
            "severity": s.severity.name.lower(),
            "message": s.message,
        })

    return json.dumps({
        "is_running": engine.is_running,
        "tick_count": state.tick_count,
        "active_count": state.active_count,
        "pending_count": state.pending_count,
        "dormant_count": state.dormant_count,
        "failed_count": state.failed_count,
        "total_count": state.total_count,
        "signals": signals_summary,
        "message": (
            f"Timeline engine: {state.active_count} active, "
            f"{state.pending_count} pending, {state.dormant_count} dormant, "
            f"{state.failed_count} failed. {state.tick_count} ticks so far."
        ),
    })


async def handle_list_credentials(ctx: ToolContext) -> str:
    """List owner's credentials — metadata only, never secret values."""
    from src import credential_bridge
    try:
        creds = credential_bridge.list_credentials(ctx.owner_id)
        return json.dumps({
            "success": True,
            "credentials": creds,
            "count": len(creds),
        })
    except Exception as e:
        log.error("handle_list_credentials failed: %s", e)
        return json.dumps({"success": False, "error": "Could not list credentials"})


async def handle_manage_credential(ctx: ToolContext, params: dict) -> str:
    """Store, rotate, or deactivate a credential.

    SECURITY: Never echoes secret values in responses.
    """
    from src import credential_bridge
    action = params.get("action", "")

    if action == "store":
        name = params.get("name", "")
        service = params.get("service", "")
        secret = params.get("secret", "")
        scoped_tools = params.get("scoped_tools", [])
        expires_at = params.get("expires_at")

        if not name or not secret:
            return json.dumps({"success": False, "error": "name and secret are required"})

        try:
            cred_id = credential_bridge.create_credential(
                ctx.owner_id, name, service, secret,
                scoped_tools, expires_at=expires_at,
            )
            return json.dumps({
                "success": True,
                "action": "stored",
                "credential_id": cred_id,
                # Never echo the secret value back — confirm storage only
                "message": f"Stored securely. Credential '{name}' is ready for use by: {scoped_tools or 'any tool'}.",
            })
        except Exception as e:
            log.error("handle_manage_credential store failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    elif action == "deactivate":
        cred_id = params.get("cred_id", "")
        if not cred_id:
            return json.dumps({"success": False, "error": "cred_id required"})
        try:
            credential_bridge.deactivate_credential(cred_id, ctx.owner_id)
            return json.dumps({"success": True, "action": "deactivated", "credential_id": cred_id})
        except PermissionError:
            return json.dumps({"success": False, "error": "Access denied"})
        except Exception as e:
            log.error("handle_manage_credential deactivate failed: %s", e)
            return json.dumps({"success": False, "error": str(e)})

    else:
        return json.dumps({"success": False, "error": f"Unknown action: {action}"})


async def handle_trigger_emergency(ctx: ToolContext, reason: str) -> str:
    """Issue a real UCAN token to Riverside Hospital + notify family connections.

    Steps:
    1. Look up the hospital user (riverside_hospital)
    2. Generate a 30-min UCAN token (attending_physician role) using the owner's ed25519 key
    3. Find family connections (trust_level >= network)
    4. Create notifications for each family member
    5. Return structured result with token + notified list + expiry
    """
    from sqlalchemy import select, or_
    from src.models import Agent, Connection, User
    from src import transit_bridge
    from src.ucan import create_ucan_token
    from src.trust import resolve_trust_level
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now + datetime.timedelta(minutes=30)

    # 1. Look up hospital user
    hosp_result = await ctx.db.execute(
        select(User).where(User.username == "riverside_hospital")
    )
    hospital = hosp_result.scalar_one_or_none()
    if not hospital:
        # Try by display name fragment
        hosp_result = await ctx.db.execute(
            select(User).where(User.display_name.ilike("%Hospital%"))
        )
        hospital = hosp_result.scalar_one_or_none()

    # 2. Get owner's agent DID + signing key
    agent_result = await ctx.db.execute(
        select(Agent).where(Agent.owner_id == ctx.owner_id)
    )
    owner_agent = agent_result.scalar_one_or_none()
    if not owner_agent:
        return json.dumps({"success": False, "error": "Owner agent not found"})

    owner_did = owner_agent.did
    signing_key: bytes | None = None
    if owner_agent.encrypted_private_key:
        try:
            signing_key = transit_bridge.decrypt(ctx.owner_id, owner_agent.encrypted_private_key)
        except Exception as e:
            log.warning("Could not decrypt owner signing key: %s", e)

    ucan_token: str | None = None
    hospital_did = ""
    if hospital:
        # Get hospital's agent DID as audience
        hosp_agent_result = await ctx.db.execute(
            select(Agent).where(Agent.owner_id == hospital.id)
        )
        hosp_agent = hosp_agent_result.scalar_one_or_none()
        hospital_did = hosp_agent.did if hosp_agent else "did:key:hospital"

        if signing_key:
            try:
                ucan_token = create_ucan_token(
                    issuer_did=owner_did,
                    issuer_private_key=signing_key,
                    audience_did=hospital_did,
                    role="attending_physician",
                    duration_seconds=1800,  # 30 minutes
                    facts={
                        "reason": reason,
                        "issued_by": ctx.owner_name,
                        "emergency": True,
                    },
                )
            except Exception as e:
                log.warning("UCAN token generation failed: %s", e)

    # 3. Find family connections to notify
    conn_result = await ctx.db.execute(
        select(Connection).where(
            or_(
                Connection.from_user_id == ctx.owner_id,
                Connection.to_user_id == ctx.owner_id,
            ),
            Connection.status == "accepted",
        )
    )
    notified = []
    for conn in conn_result.scalars().all():
        other_id = conn.to_user_id if conn.from_user_id == ctx.owner_id else conn.from_user_id
        trust_level, _ = await resolve_trust_level(ctx.db, ctx.owner_id, other_id)
        if trust_level not in ("network", "private"):
            continue
        other = await ctx.db.get(User, other_id)
        if not other or other.is_remote:
            continue

        # 4. Create notification
        notification = Notification(
            user_id=other_id,
            notification_type="emergency_alert",
            title=f"EMERGENCY: {ctx.owner_name} needs help",
            body=f"{ctx.owner_name} has declared a medical emergency: {reason}. "
                 f"Emergency services have been notified. Please check in immediately.",
            related_id=ctx.owner_id,
        )
        ctx.db.add(notification)
        notified.append(other.display_name)

    # Also notify hospital if found
    if hospital:
        hosp_notification = Notification(
            user_id=hospital.id,
            notification_type="emergency_access_granted",
            title=f"Emergency access granted by {ctx.owner_name}",
            body=f"A 30-minute UCAN token has been issued for attending_physician access to "
                 f"{ctx.owner_name}'s health data. Reason: {reason}",
            related_id=ctx.owner_id,
        )
        ctx.db.add(hosp_notification)

    await ctx.db.flush()

    ctx.actions.append({
        "type": "emergency_triggered",
        "reason": reason,
        "ucan_issued": ucan_token is not None,
        "notified": notified,
        "hospital": hospital.display_name if hospital else None,
    })

    return json.dumps({
        "success": True,
        "emergency_declared": True,
        "reason": reason,
        # Keep the token out of the LLM-visible result — it's long base64 that sounds
        # terrible in voice and has no value for the agent to repeat.
        "ucan_issued": ucan_token is not None,
        "ucan_role": "attending_physician",
        "expires_in": "30 minutes",
        "hospital_notified": hospital.display_name if hospital else "Riverside Hospital (not found in mesh)",
        "family_notified": notified,
        "message": (
            f"Emergency declared. UCAN access token issued to {hospital.display_name if hospital else 'hospital'} "
            f"(valid 30 min, attending_physician role). "
            f"Notified {len(notified)} family member(s): {', '.join(notified) or 'none'}."
        ),
    })


async def handle_generate_emergency_qr(
    ctx: ToolContext, role: str, reason: str, requester_org: str = ""
) -> str:
    """Generate a role-scoped UCAN beacon token and return the scanner URL.

    Registry verification flow:
    - If requester_org is provided, query the local DB + TrustMesh registry for
      a matching organization DID.
    - Verified medical org → token aud = org DID, role as requested.
    - Unverified → token aud = "did:emergency:any", role downgraded to "paramedic"
      (minimal scope: blood type, allergies, DNR, emergency contacts only).
    - Scan endpoint re-checks the aud DID against the registry — an unregistered
      person with the URL will fail verification at scan time.
    """
    from sqlalchemy import select
    from src.models import Agent, User, AuditLog
    from src import transit_bridge
    from src.ucan import create_ucan_token
    from src.rate_limit import check_emergency_issue_rate, record_emergency_issue
    from src.federation import POD_URL, REGISTRY_URL
    import os as _os
    import uuid as _uuid

    valid_roles = {"paramedic", "er_nurse", "attending_physician"}
    if role not in valid_roles:
        return json.dumps({"error": f"Invalid role '{role}'. Must be one of: {sorted(valid_roles)}"})

    # Rate limit — same bucket as the beacon endpoint
    rate_ok, rate_msg = check_emergency_issue_rate(ctx.owner_id)
    if not rate_ok:
        return json.dumps({"error": rate_msg})

    # ── Registry verification ──────────────────────────────────────────────────
    # Try to find the requester's org DID via local users (ghost users for known
    # remote pods) or the public TrustMesh registry.
    org_did: str = "did:emergency:any"   # default: unverified
    org_verified: bool = False
    org_verified_name: str = ""
    final_role: str = role               # may be downgraded

    MEDICAL_KEYWORDS = {"hospital", "medical", "health", "clinic", "ems", "emergency", "paramedic", "rescue"}

    if requester_org:
        org_lower = requester_org.lower()

        # 1. Check local DB (ghost users from federated pods, or local org users)
        local_result = await ctx.db.execute(
            select(User, Agent)
            .join(Agent, Agent.owner_id == User.id)
            .where(User.user_type.in_(["organization", "service"]))
            .where(User.display_name.ilike(f"%{requester_org}%"))
        )
        local_match = local_result.first()
        if local_match:
            local_user, local_agent = local_match
            org_did = local_agent.did
            org_verified = True
            org_verified_name = local_user.display_name

        # 2. If not local, try the registry API
        if not org_verified and REGISTRY_URL:
            try:
                import httpx as _httpx
                import urllib.parse
                async with _httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{REGISTRY_URL.rstrip('/')}/api/agents",
                        params={"entity_type": "organization", "q": requester_org},
                    )
                    if resp.status_code == 200:
                        for entry in resp.json().get("agents", []):
                            name_lower = entry.get("name", "").lower()
                            bio_lower = entry.get("bio", "").lower()
                            # Must match the org name AND look like a medical org
                            if requester_org.lower() in name_lower and any(
                                kw in name_lower or kw in bio_lower for kw in MEDICAL_KEYWORDS
                            ):
                                org_did = entry.get("did", "did:emergency:any")
                                org_verified = True
                                org_verified_name = entry.get("name", requester_org)
                                break
            except Exception:
                pass  # Registry unreachable — fall back to unverified

        # 3. If still unverified, downgrade role to paramedic (minimal scope)
        if not org_verified:
            final_role = "paramedic"

    # Load owner's agent + private key
    agent_result = await ctx.db.execute(select(Agent).where(Agent.owner_id == ctx.owner_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        return json.dumps({"error": "Agent not found for this user"})

    user_result = await ctx.db.execute(select(User).where(User.id == ctx.owner_id))
    user = user_result.scalar_one_or_none()
    patient_username = (user.username if user else None) or ctx.owner_id

    if not transit_bridge.has_key(ctx.owner_id):
        return json.dumps({"error": "Vault key not loaded — owner must be logged in first"})

    try:
        private_key = transit_bridge.decrypt(ctx.owner_id, agent.encrypted_private_key)
    except Exception:
        return json.dumps({"error": "Failed to decrypt agent private key"})

    # Sign the token with verified audience
    try:
        token = create_ucan_token(
            issuer_did=agent.did,
            issuer_private_key=private_key,
            audience_did=org_did,
            role=final_role,
            duration_seconds=1800,
            facts={
                "emergency_beacon": True,
                "issued_by": ctx.owner_name,
                "reason": reason,
                "org_verified": org_verified,
                "org_name": org_verified_name or requester_org or "unknown",
            },
        )
    except Exception as e:
        return json.dumps({"error": f"Token generation failed: {e}"})
    finally:
        private_key = b"\x00" * len(private_key)

    # Build the scanner URL (frontend + pod param for multi-pod)
    _frontend_url = _os.getenv("TRUSTMESH_FRONTEND_URL", "http://localhost:3050").rstrip("/")
    scanner_url = f"{_frontend_url}/emergency/scan?t={token}&p={patient_username}&pod={POD_URL}"

    # Audit log
    audit_id = str(_uuid.uuid4())
    try:
        audit_row = AuditLog(
            id=audit_id,
            actor_user_id=ctx.owner_id,
            target_user_id=ctx.owner_id,
            action="emergency_beacon_generated",
            event_type="emergency",
            token_role=final_role,
            decision="allowed",
            details=json.dumps({
                "source": "agent_tool",
                "reason": reason,
                "org_verified": org_verified,
                "org_name": org_verified_name or requester_org or "unknown",
                "requested_role": role,
                "issued_role": final_role,
                "audience": org_did,
            }),
        )
        ctx.db.add(audit_row)
        await ctx.db.flush()
    except Exception:
        pass

    record_emergency_issue(ctx.owner_id)

    role_labels = {
        "paramedic": "EMT / Paramedic",
        "er_nurse": "ER Nurse",
        "attending_physician": "Attending Physician",
    }

    downgraded_msg = ""
    if final_role != role:
        downgraded_msg = (
            f" NOTE: Role downgraded from '{role}' to 'paramedic' because "
            f"'{requester_org}' could not be verified as a registered medical organization. "
            f"Only blood type, allergies, DNR, and emergency contacts will be visible."
        )

    return json.dumps({
        "success": True,
        "role": final_role,
        "role_label": role_labels[final_role],
        "org_verified": org_verified,
        "org_name": org_verified_name or requester_org or "unverified",
        "audience": org_did,
        "scanner_url": scanner_url,
        "expires_in": "30 minutes",
        "audit_id": audit_id,
        "instructions": (
            f"Share this URL with the {role_labels[final_role]}: {scanner_url}\n"
            f"They can open it on any device — no login required. "
            f"Access is cryptographically verified and logged.{downgraded_msg}"
        ),
    })


async def handle_send_connection_request(ctx: ToolContext, params: dict) -> str:
    """Send a connection request to another user on this pod."""
    from sqlalchemy import select
    from src.models import User, Connection, ConnectionRequest
    from src.rate_limit import check_connection_rate, record_connection_request

    to_username = params["to_username"].strip()
    message = params.get("message", "")[:500]
    relationship_type = params.get("relationship_type", "")

    # Resolve target user
    result = await ctx.db.execute(
        select(User).where(User.username == to_username)
    )
    target = result.scalar_one_or_none()
    if not target:
        # Fuzzy fallback: display name
        result2 = await ctx.db.execute(
            select(User).where(
                User.display_name.ilike(f"%{to_username}%")
            ).limit(1)
        )
        target = result2.scalar_one_or_none()
    if not target:
        return json.dumps({"success": False, "error": f"User '{to_username}' not found."})

    if target.id == ctx.owner_id:
        return json.dumps({"success": False, "error": "Cannot connect with yourself."})

    if target.is_remote:
        return json.dumps({"success": False, "error": "Cross-pod connection requests not yet supported via agent. Use the Connections page."})

    # Check if already connected
    existing = await ctx.db.execute(
        select(Connection).where(
            ((Connection.from_user_id == ctx.owner_id) & (Connection.to_user_id == target.id)) |
            ((Connection.from_user_id == target.id) & (Connection.to_user_id == ctx.owner_id))
        )
    )
    if existing.scalar_one_or_none():
        return json.dumps({"success": False, "already_connected": True, "message": f"You're already connected with {target.display_name}."})

    # Check for existing pending request
    pending = await ctx.db.execute(
        select(ConnectionRequest).where(
            ConnectionRequest.from_user_id == ctx.owner_id,
            ConnectionRequest.to_user_id == target.id,
            ConnectionRequest.status == "pending",
        )
    )
    if pending.scalar_one_or_none():
        return json.dumps({"success": False, "already_pending": True, "message": f"A connection request to {target.display_name} is already pending."})

    # Rate limit
    if not check_connection_rate(ctx.owner_id):
        return json.dumps({"success": False, "error": "Too many connection requests. Try again later."})

    # Create the request
    import uuid
    req = ConnectionRequest(
        id=str(uuid.uuid4()),
        from_user_id=ctx.owner_id,
        to_user_id=target.id,
        message=message,
        relationship_type=relationship_type or None,
        status="pending",
    )
    ctx.db.add(req)

    # Create notification for recipient
    from src.models import Notification
    notif = Notification(
        id=str(uuid.uuid4()),
        user_id=target.id,
        notification_type="connection_request",
        title="New connection request",
        body=f"{ctx.owner_name} wants to connect with you.",
        related_id=req.id,
    )
    ctx.db.add(notif)
    await ctx.db.commit()

    record_connection_request(ctx.owner_id)

    # Audit trail
    try:
        from src.audit import log_event
        await log_event(
            ctx.db,
            actor_user_id=ctx.owner_id,
            target_user_id=target.id,
            action="connection_request_sent",
            event_type="network",
            decision="allowed",
            details={"recipient": target.display_name, "request_id": req.id, "via": "agent"},
        )
    except Exception:
        pass

    return json.dumps({
        "success": True,
        "message": f"Connection request sent to {target.display_name}. They'll be notified.",
        "recipient": target.display_name,
        "request_id": req.id,
    })


async def handle_send_message(ctx: ToolContext, params: dict) -> str:
    """Send an encrypted message to a connected/pool-member user (local or cross-pod).

    Steps:
    1. Resolve recipient by username (local or ghost)
    2. Trust check — must be connected/network/private
    3a. Local recipient — encrypt via transit/pod KEK, create_message, Notification
    3b. Remote (ghost) — sign payload, POST to remote pod's deliver endpoint
    4. Audit capsule in sender's vault (private memory)
    5. Return structured result
    """
    import hashlib
    import uuid
    from datetime import datetime, timezone, timedelta

    from sqlalchemy import select, func
    from src.models import User, Notification
    from src.trust import resolve_trust_level
    from src import transit_bridge, message_bridge

    to_username = params["to_username"]
    subject = str(params["subject"])[:200]
    body = params["body"]
    expires_in_hours: int | None = params.get("expires_in_hours")

    # ── 1. Resolve recipient ──────────────────────────────────────────────────
    result = await ctx.db.execute(select(User).where(User.username == to_username))
    recipient = result.scalar_one_or_none()
    if not recipient:
        # Display-name fallback (handles "Dr. Lee" → dr_lee)
        result2 = await ctx.db.execute(
            select(User).where(
                func.lower(User.display_name).contains(to_username.lower().replace(".", ""))
            ).limit(1)
        )
        recipient = result2.scalar_one_or_none()

    if not recipient:
        return json.dumps({"success": False, "error": f"User '{to_username}' not found in your network."})

    # ── 2. Trust check ────────────────────────────────────────────────────────
    trust_level, _ = await resolve_trust_level(ctx.db, ctx.owner_id, recipient.id)
    if trust_level not in ("connected", "network", "private"):
        return json.dumps({
            "success": False,
            "error": f"Cannot message {to_username}: trust level is '{trust_level}'. "
                     "You can only message users you're connected to or share a pool with.",
        })

    # Owner info for sender fields
    owner_result = await ctx.db.execute(select(User).where(User.id == ctx.owner_id))
    owner = owner_result.scalar_one_or_none()
    owner_username = owner.username if owner else ctx.owner_id
    owner_display = owner.display_name if owner else ctx.owner_name

    now = datetime.now(timezone.utc)
    msg_id = str(uuid.uuid4())
    expires_at: str | None = None
    if expires_in_hours:
        expires_at = (now + timedelta(hours=expires_in_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    body_bytes = body.encode("utf-8")
    body_hash = hashlib.sha256(body_bytes).hexdigest()

    cross_pod = bool(recipient.is_remote)

    # ── 3a. Local recipient ───────────────────────────────────────────────────
    if not cross_pod:
        if transit_bridge.has_key(recipient.id):
            aad = f"message:{msg_id}"
            body_encrypted = transit_bridge.encrypt(recipient.id, body_bytes, aad=aad)
            rekey_needed = False
        else:
            # Encrypt with pod KEK — rekey on recipient's next login
            from src.main import _POD_KEK
            from src.crypto import encrypt as _crypto_encrypt
            body_encrypted = _crypto_encrypt(body_bytes, _POD_KEK)
            rekey_needed = True

        message_bridge.create_message(
            message_id=msg_id,
            sender_id=ctx.owner_id,
            sender_username=owner_username,
            sender_display_name=owner_display,
            sender_pod_url=None,
            recipient_id=recipient.id,
            subject=subject,
            body_encrypted=body_encrypted,
            body_hash=body_hash,
            scope="direct",
            trust_level=trust_level,
            expires_at=expires_at,
            rekey_needed=rekey_needed,
        )

        ctx.db.add(Notification(
            user_id=recipient.id,
            notification_type="message_received",
            title=f"Message from {owner_display}: {subject}",
            body=subject,
            related_id=msg_id,
        ))
        await ctx.db.flush()

    # ── 3b. Remote (ghost) — federated delivery ───────────────────────────────
    else:
        import httpx
        from src.models import Agent
        from src import federation_auth

        agent_result = await ctx.db.execute(select(Agent).where(Agent.owner_id == ctx.owner_id))
        our_agent = agent_result.scalar_one_or_none()
        our_did = our_agent.did if our_agent else "unknown"
        signing_key: bytes | None = None
        if our_agent and our_agent.encrypted_private_key:
            try:
                signing_key = transit_bridge.decrypt(ctx.owner_id, our_agent.encrypted_private_key)
            except Exception:
                signing_key = None

        import json as _json
        from src import federation_auth

        # Strip "remote:" prefix and "@host" suffix to get bare username
        real_to = recipient.username
        if real_to.startswith("remote:"):
            real_to = real_to[7:]
        if "@" in real_to:
            real_to = real_to.split("@")[0]

        from src.main import app  # noqa: avoid circular — only for pod_url
        pod_url = os.getenv("TRUSTMESH_POD_URL", "")

        payload = {
            "from_did": our_did,
            "from_pod": pod_url,
            "to_username": real_to,
            "subject": subject,
            "body": body,
            "scope": "direct",
            "expires_in_hours": expires_in_hours,
            "sender_username": owner_username,
            "sender_display_name": owner_display,
            "federation_signature": "",
        }

        raw_body = _json.dumps(payload).encode()
        deliver_path = "/api/pod/messages/deliver"
        sig_headers: dict[str, str] = {}
        if signing_key:
            try:
                sig_headers = federation_auth.sign_federation_request(
                    raw_body, signing_key, method="POST", path=deliver_path
                )
            except Exception as e:
                log.warning("send_message: federation signing failed: %s", e)

        deliver_url = recipient.remote_pod_url.rstrip("/") + deliver_path
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(deliver_url, content=raw_body, headers={
                    "Content-Type": "application/json",
                    **sig_headers,
                })
                if resp.status_code != 200:
                    return json.dumps({
                        "success": False,
                        "error": f"Remote pod rejected delivery: HTTP {resp.status_code}",
                    })
        except Exception as e:
            return json.dumps({"success": False, "error": f"Cross-pod delivery failed: {e}"})

    # ── 4. Audit capsule (always) ─────────────────────────────────────────────
    try:
        from src.crypto import content_hash
        from src.embeddings import upsert_capsule_embedding
        from src.models import KnowledgeCapsule

        audit_title = f"Sent: {subject}"
        audit_content = f"To: {owner_display if cross_pod else recipient.display_name} ({to_username})\nSubject: {subject}\n\n{body}"
        capsule = KnowledgeCapsule(
            owner_id=ctx.owner_id,
            capsule_type="memory",
            title=audit_title,
            content_encrypted=transit_bridge.encrypt_text(ctx.owner_id, audit_content),
            content_hash=content_hash(audit_content),
            visibility="private",
            emergency_accessible=False,
            can_reshare=False,
            category="work",
            freshness="current",
        )
        ctx.db.add(capsule)
        await ctx.db.flush()
        upsert_capsule_embedding(
            capsule.id,
            f"{audit_title}: {audit_content}",
            {"capsule_id": capsule.id, "owner_id": ctx.owner_id, "visibility": "private"},
            category="work",
        )
    except Exception as e:
        log.warning("send_message: audit capsule failed: %s", e)

    ctx.actions.append({
        "type": "message_sent",
        "message_id": msg_id,
        "recipient": to_username,
        "subject": subject,
        "cross_pod": cross_pod,
        "trust_level": trust_level,
        "expires_at": expires_at,
    })

    return json.dumps({
        "success": True,
        "message_id": msg_id,
        "recipient": to_username,
        "recipient_display_name": recipient.display_name,
        "subject": subject,
        "cross_pod": cross_pod,
        "trust_level": trust_level,
        "expires_at": expires_at,
        "message": f"Message sent to {recipient.display_name}"
                   + (" (cross-pod)" if cross_pod else "")
                   + (f", expires in {expires_in_hours}h" if expires_in_hours else ""),
    })


async def execute_tool(tool_name: str, tool_input: dict, ctx: ToolContext) -> str:
    """Route a tool call to its handler. Returns JSON string.

    All tool output is scrubbed for secret prefixes before returning to the LLM.
    This prevents credential leakage regardless of which tool produces the output.
    """
    from src.citadel import scrub_tool_output

    if tool_name == "search_vault":
        result = await handle_search_vault(ctx, tool_input["query"])
    elif tool_name == "save_capsule":
        result = await handle_save_capsule(ctx, tool_input)
    elif tool_name == "web_search":
        result = await handle_web_search(ctx, tool_input["query"], tool_input.get("context", ""))
    elif tool_name == "browse_web":
        result = await handle_browse_web(ctx, tool_input)
    elif tool_name == "create_task":
        result = await handle_create_task(ctx, tool_input)
    elif tool_name == "discover_agents":
        result = await handle_discover_agents(ctx, tool_input)
    elif tool_name == "query_peer":
        result = await handle_query_peer(ctx, tool_input)
    elif tool_name == "request_quotes":
        result = await handle_request_quotes(ctx, tool_input)
    elif tool_name == "list_connections":
        result = await handle_list_connections(ctx)
    elif tool_name == "list_services":
        result = await handle_list_services(ctx)
    elif tool_name == "discover_networks":
        result = await handle_discover_networks(ctx, tool_input.get("interest", ""))
    elif tool_name == "check_calendar":
        result = await handle_check_calendar(ctx, tool_input.get("time_range", "this_week"))
    elif tool_name == "draft_email":
        result = await handle_draft_email(ctx, tool_input)
    # Timeline tools
    elif tool_name == "create_timeline_entry":
        result = await handle_create_timeline_entry(ctx, tool_input)
    elif tool_name == "list_timeline_entries":
        result = await handle_list_timeline_entries(ctx, tool_input.get("filter_state", "all"))
    elif tool_name == "complete_timeline_entry":
        result = await handle_complete_timeline_entry(ctx, tool_input["entry_id"])
    elif tool_name == "check_timeline_state":
        result = await handle_check_timeline_state(ctx)
    # Emergency escalation
    elif tool_name == "trigger_emergency":
        result = await handle_trigger_emergency(ctx, tool_input.get("reason", "unspecified emergency"))
    elif tool_name == "generate_emergency_qr":
        result = await handle_generate_emergency_qr(
            ctx,
            role=tool_input.get("role", "paramedic"),
            reason=tool_input.get("reason", "emergency access requested"),
            requester_org=tool_input.get("requester_org", ""),
        )
    # Credential tools
    elif tool_name == "list_credentials":
        result = await handle_list_credentials(ctx)
    elif tool_name == "manage_credential":
        result = await handle_manage_credential(ctx, tool_input)
    # Messaging tools
    elif tool_name == "send_message":
        result = await handle_send_message(ctx, tool_input)
    elif tool_name == "send_connection_request":
        result = await handle_send_connection_request(ctx, tool_input)
    else:
        result = json.dumps({"error": f"Unknown tool: {tool_name}"})

    # Scrub secret prefixes from ALL tool output before sending to LLM
    return scrub_tool_output(result)


# ═══════════════════════════════════════════════════════════════
# System Prompts
# ═══════════════════════════════════════════════════════════════

def build_trust_context(trust_level: str, shared_networks: list[Network], requester_name: str, owner_name: str = "") -> str:
    """Build human-readable trust context for the agent prompt."""
    if trust_level == "private":
        return f"{requester_name} is the vault owner. Full access to all knowledge."
    elif trust_level == "network":
        network_names = ", ".join(n.name for n in shared_networks)
        return (
            f"{requester_name} is connected and shares these networks: {network_names}. "
            f"They can access open capsules, internal capsules shared to these networks, "
            f"and any capsules explicitly shared with them."
        )
    elif trust_level == "connected":
        return (
            f"{requester_name} is directly connected to {owner_name or 'your owner'} but shares no pools/networks.\n\n"
            f"CONNECTED-TRUST RULES:\n"
            f"- You may acknowledge knowing {requester_name} and being connected\n"
            f"- Only share information from the open capsules listed below\n"
            f"- Do NOT reveal internal capsule content, network member names, or private information\n"
            f"- You may suggest they join a shared pool for deeper access\n"
            f"- If you don't have open information for their question, say: \"I don't have that information available at our current trust level. "
            f"You could ask {owner_name or 'my owner'} to invite you to a shared pool for more access.\""
        )
    else:
        return (
            f"{requester_name} has public access only. "
            f"They are NOT in any of your owner's networks and have NO trusted relationship.\n\n"
            f"STRICT PUBLIC-TRUST RULES:\n"
            f"- Only share information from the open capsules listed below\n"
            f"- NEVER mention, name, or hint at other people, contacts, family, team members, or network members\n"
            f"- NEVER suggest \"ask someone else\", \"reach out to\", or \"you might want to contact\"\n"
            f"- NEVER reference the existence of groups, teams, families, networks, or pools\n"
            f"- NEVER say \"I know someone who\", \"we have\", \"our team\", or similar\n"
            f"- If you don't have information in the open capsules, say ONLY: \"I don't have that information available.\"\n"
            f"- Do NOT explain WHY you can't share — just say you don't have it"
        )


def format_capsules(capsules: list[dict]) -> str:
    """Format capsules for the agent prompt.

    Superseded capsules are marked and sorted last. Non-superseded capsules
    are sorted by authority_weight (descending).
    """
    if not capsules:
        return "No knowledge capsules available for this requester."

    # Sort: non-superseded first, then by authority_weight descending
    sorted_capsules = sorted(
        capsules,
        key=lambda c: (c.get("is_superseded", False), -c.get("authority_weight", 1.0)),
    )

    parts = []
    for c in sorted_capsules:
        superseded_tag = "[SUPERSEDED by newer version] " if c.get("is_superseded") else ""

        freshness_note = ""
        if c.get("expires_at"):
            freshness_note = f" [Expires: {c['expires_at']}]"
        elif c.get("freshness") == "temporary":
            freshness_note = " [Temporary — may be outdated]"

        gov_flags = []
        if c.get("emergency_accessible"):
            gov_flags.append("emergency-accessible")
        if c.get("can_reshare"):
            gov_flags.append("reshare-ok")
        gov_str = f" | Flags: {', '.join(gov_flags)}" if gov_flags else ""

        parts.append(
            f"{superseded_tag}[{c['capsule_type'].upper()}] {c['title']}{freshness_note}\n"
            f"Visibility: {c.get('visibility', c.get('tier', 'private'))} | Category: {c.get('category', 'general')}{gov_str}\n"
            f"{c['content']}\n"
        )
    return "\n---\n".join(parts)


def format_networks(networks: list[dict]) -> str:
    """Format the owner's networks for the self-query prompt."""
    if not networks:
        return "You don't belong to any networks yet."
    parts = []
    for n in networks:
        parts.append(f"- {n['name']} ({n['network_type']})")
    return "\n".join(parts)


# ── Cross-query prompt (read-only, no tools) ──

CROSS_QUERY_SYSTEM_PROMPT = """You are {owner_name}'s personal AI agent in the TrustMesh network.

You hold {owner_name}'s knowledge and share it appropriately based on who's asking.

## Who Is Asking
Requester: {requester_name}
Trust level: {trust_level}
{trust_context}

## Your Knowledge
These are the knowledge capsules you can draw from for this requester:

{formatted_capsules}

## Sharing Rules
1. ONLY use information from the capsules above — never fabricate
2. Match the capsule type to how you present information:
   - Memories: share naturally, conversationally
   - Skills: explain with the detail level appropriate for the question
   - Procedures: be precise and complete — these may involve health/safety
   - Schedules: include specific times, dates, and details
   - Preferences: state clearly, especially allergies or medical info
   - Contacts: share contact details when relevant to the question
3. If the question asks about something not in your capsules, say you don't have that information
4. NEVER reveal information beyond what the capsules above contain
5. For health/medical procedures, always err on the side of completeness and accuracy
6. Be warm and helpful — you represent {owner_name}
7. Keep responses concise but complete. Don't add unnecessary preamble.
8. **Reshare control**: If a capsule has can_reshare=false (or the flag isn't set), tell the requester: "This information is shared for your reference only — please don't pass it along."
9. **Visibility awareness**: Only share capsules that appear in the list above. The system has already filtered by the requester's access level.

## Information Boundary Rules (CRITICAL)
- NEVER mention names of people who are NOT the requester or the owner — even if they appear in capsule content
- NEVER suggest the requester "ask someone else" or "reach out to" another person
- NEVER reveal the existence or names of networks, groups, teams, pools, or families
- NEVER hint that more information exists beyond what you're sharing ("I have more but can't share" is a leak)
- If you lack information, say "I don't have that information" — NOT "someone else might know"
- These rules protect the privacy of everyone in the trust network"""


# ── Self-query prompt (tool-enabled) ──

SELF_QUERY_SYSTEM_PROMPT = """You are {owner_name}'s personal AI agent in the TrustMesh network.

You are talking directly to {owner_name} (your owner). You have FULL access to their vault and can also SAVE new knowledge.

## Your Networks
{networks_list}

## Your Current Knowledge
{formatted_capsules}

## What You Can Do
You have tools:

1. **search_vault** — Search for existing capsules before saving. ALWAYS search first to avoid duplicates.
2. **save_capsule** — Save new knowledge or update existing capsules.
3. **web_search** — Search the web for real information (services, prices, reviews, current events).
4. **create_task** — Track multi-step work for your owner (appears in their dashboard).
5. **query_peer** — Ask another person's or service's agent a question (trust rules apply).
6. **request_quotes** — Get quotes from service providers in the mesh.
7. **list_connections** — See who you're connected to and shared networks. Use before query_peer.
8. **list_services** — See what service providers are in the mesh. Use before request_quotes.
9. **discover_networks** — Find public networks/groups the owner can join (music, dance, sports, neighborhood, etc.).
10. **check_calendar** — Check the owner's calendar for upcoming events, meetings, and appointments.
11. **draft_email** — Compose and save an email draft (saved to vault as a capsule).
12. **create_timeline_entry** — Schedule a task, reminder, or event-triggered action in the PodOS timeline.
13. **list_timeline_entries** — See what's active, pending, or coming up in the timeline.
14. **complete_timeline_entry** — Mark a timeline entry as done when the task is fulfilled.
15. **check_timeline_state** — Get the heartbeat of the timeline engine (counts, signals, health).
16. **send_message** — Send an encrypted message to someone you're already connected with or share a pool with.
17. **send_connection_request** — Send a connection request to someone so you can message them and query their agent. Use when the user asks to connect with, add, or follow someone.

## When to use tools — match INTENT, not literal phrases (works in any language):
- User wants to befriend, add, connect with, or follow someone → **send_connection_request** IMMEDIATELY (do NOT search_vault first)
- User wants to send a private message to someone NOW → **send_message** immediately
- User wants to send a message IN THE FUTURE (e.g. "in 5 minutes", "later today", "remind me to message X") → **create_timeline_entry** with trigger_type="time" and trigger_at_ms=now+delay, with hook_prompt instructing the agent to call send_message at that time. ALSO call **create_task** so it appears on the dashboard as pending. Do NOT call send_message immediately.
- User is asking about services, businesses, or providers of any kind → ALWAYS list_services first, then request_quotes for matches, then web_search
- User wants to know what's available in some category (hospitals, tutors, cleaners, etc.) → list_services FIRST, then web_search
- User is asking about preparations, plans, or what to bring/do → search_vault + list_connections, then query_peer relevant contacts
- User wants to save, remember, or note something → search_vault (check for duplicates) then save_capsule
- User has a complex multi-step question → create_task to track, then research with multiple tools
- User mentions or asks about a specific person → list_connections to check access, then query_peer
- User wants current information, news, or external data → web_search
- User wants help finding someone or something → list_services + request_quotes + web_search (all three!)
- User asks about family, friends, or shared plans → search_vault + query_peer relevant contacts
- User is interested in groups, communities, hobbies, or social activities → discover_networks
- User wants to know what's on their schedule or when something is happening → check_calendar
- User wants to compose or send an email → draft_email
- User wants a reminder, scheduled action, or recurring check → create_timeline_entry with appropriate trigger
- User asks what is currently active or what to focus on → check_timeline_state + list_timeline_entries
- User wants to track something recurring over time → create_timeline_entry with cron trigger
- User signals completion of a task or goal → complete_timeline_entry

## IMPORTANT: Always check the mesh FIRST
When the user asks about ANY type of provider, service, or business — ALWAYS call list_services before web_search.
TrustMesh has registered service providers (hospitals, tutors, cleaners, handyman, ambulance) and their agents can be queried directly.
The mesh is always more trustworthy than web results.

## Be Proactive
When you can anticipate what the user needs, DO IT:
- If they ask about a visit, also check schedules, related contacts, and query family agents
- If they ask about a service, compare mesh providers AND web results
- If they ask to remember something, also check if it affects schedules or other capsules
- Always try to give a COMPLETE answer, not just a partial one

## Smart Memory Rules

### Before Saving: ALWAYS Search First
When the owner asks you to save/remember/note something:
1. First call `search_vault` with relevant keywords to find existing capsules
2. If a closely related capsule exists, UPDATE it (pass `existing_capsule_id`) rather than creating a duplicate
3. If no match, create a new capsule

### Classification Intelligence
Classify saved knowledge smartly and ACCURATELY. Pay close attention to what the user actually said:

**capsule_type:**
- "preference" — likes, dislikes, allergies, dietary restrictions, favorites
- "memory" — events, observations, things that happened
- "skill" — expertise, how-to knowledge
- "procedure" — step-by-step routines, care instructions
- "schedule" — appointments, trips, deadlines
- "contact" — people, phone numbers, emails

**CRITICAL — Distinguish Dislikes from Allergies:**
- "I hate X" / "I don't like X" / "I can't stand X" → This is a DISLIKE/preference, NOT a medical condition. Title should reflect this (e.g., "Jane's Food Dislikes", NOT "Jane's Peanut Allergy").
- "I'm allergic to X" / "X allergy" / "allergic reaction" → This IS an allergy. Category should be "health".
- Do NOT escalate dislikes into medical conditions. If someone says "I hate peanuts", that means they don't enjoy eating them — it does NOT mean they have a peanut allergy. These are fundamentally different.

**visibility (4-level data governance):**
- `private` — Owner only. Diary entries, personal secrets, sensitive notes.
- `internal` — Owner + trusted networks. Health/safety info shared with family, work data shared with team.
- `shareable` — Explicitly shared with specific people. Temporal — access grants expire.
- `open` — Discoverable by anyone. Professional bio, public skills.

**Category defaults (use these unless owner says otherwise):**
| Category | Default visibility | emergency_accessible | can_reshare |
|----------|-------------------|---------------------|-------------|
| health   | internal          | true                | false       |
| personal | private           | false               | false       |
| work     | internal          | false               | false       |
| family   | internal          | false               | false       |
| home     | internal          | false               | false       |
| general  | open              | false               | true        |

After saving, confirm the governance: "I saved Rose's medication list as **internal** with emergency access enabled. Your Care Circle can see it, and verified healthcare providers can access it in emergencies."

**emergency_accessible:** Set `true` for health capsules (allergies, medications, conditions). Verified healthcare providers can access these via UCAN tokens regardless of visibility level.

**can_reshare:** Set `true` for open/general capsules. When `false`, viewing agents say "This is shared for your reference only."

**category:**
- Actual medical allergies, medications → "health"
- Food dislikes, favorite foods → "personal" (NOT "health" unless it's a real allergy)
- House repairs → "home", coworker info → "work", hobbies → "personal"

**freshness:** Facts/allergies → "permanent". Events/locations → "temporary". Routines → "recurring"
**title:** Include the person's name if about someone else. Be descriptive but concise. Reflect what was actually said — don't exaggerate or medicalize.

### Merging & Dedup
- If the owner says "Peter is allergic to shellfish" and you find an existing "Peter's Medical Info" capsule, UPDATE it to include the shellfish allergy alongside existing info
- If you find a capsule about the same topic but a different person, create a NEW capsule (not a duplicate)
- When updating, merge the new information with the old content — don't lose existing data

### Network Assignment
- Family health/safety info → share with family network (visibility: internal)
- Work-related knowledge → share with work network (visibility: internal)
- Personal observations about relationships → keep "private" unless owner specifies
- If unsure, default to "private" and tell the owner they can share it later

## Cross-Pod Query Results — Save & Confirm

When you receive useful information from a cross-pod query (via query_peer):
1. **Present the results clearly** — summarize what you learned, who you asked, and what trust level was used
2. **Offer to save** — "I found this from [source]. Want me to save it to your vault?"
3. **If the user agrees (or you got useful service/health/contact info), save it** — use save_capsule with appropriate category and visibility
4. **Before sharing personal data with another pod** — ALWAYS tell the user what you're about to share and ask for confirmation. Say: "I'd like to share [summary] with [target]. Should I go ahead?"

When federation is involved, always mention:
- Which pod/agent you queried
- What trust level was used (network = shared pool, public = open only)
- What shared networks enabled the trust

## Response Style
- Be conversational and warm — you're talking to your owner
- After saving, confirm what you saved and how you classified it
- If you found a duplicate and merged, explain that
- You can also answer questions about the owner's knowledge (read from capsules)
- Keep responses concise. Don't over-explain unless asked.
{personality_instruction}"""

# ── Personality modes ─────────────────────────────────────────────────────────

PERSONALITY_INSTRUCTIONS: dict[str, str] = {
    "simple": (
        "\n## Communication Style\n"
        "Use very plain, everyday language. Explain everything as if the user is completely new to the topic. "
        "Use analogies and concrete real-world examples. Define any technical term you use. Be patient and thorough."
    ),
    "step-by-step": (
        "\n## Communication Style\n"
        "Provide detailed, step-by-step explanations for everything. Break complex topics into numbered steps. "
        "Never skip context. Walk the user through each part carefully before moving on."
    ),
    "concise": (
        "\n## Communication Style\n"
        "Be brief and direct. Skip all preamble. Prefer bullet points over paragraphs. "
        "Get to the point in the fewest words possible."
    ),
    "technical": (
        "\n## Communication Style\n"
        "Use precise technical terminology. Assume the user has domain expertise. "
        "Be analytically rigorous. Skip basic explanations and go straight to the technical details."
    ),
    "friendly": (
        "\n## Communication Style\n"
        "Be warm, casual, and encouraging. Use a conversational tone. "
        "Celebrate small wins. Make the user feel supported and confident."
    ),
}


def _personality_note(mode: str) -> str:
    """Return the prompt instruction for the given personality mode (empty string if unset/unknown)."""
    return PERSONALITY_INSTRUCTIONS.get(mode or "", "")


# ═══════════════════════════════════════════════════════════════
# Sensitivity Detection (for TEE routing)
# ═══════════════════════════════════════════════════════════════

SENSITIVE_CATEGORIES = {"medical", "financial", "legal", "insurance"}
SENSITIVE_KEYWORDS = {
    "medical", "health", "diagnosis", "prescription", "medication",
    "blood pressure", "dialysis", "surgery", "therapy", "treatment",
    "financial", "bank", "account number", "ssn", "social security",
    "credit card", "tax", "salary", "income", "investment",
    "insurance", "policy number", "claim",
}


def detect_sensitivity(capsules: list[dict], question: str = "") -> str:
    """Detect if a query involves sensitive data.

    Returns "sensitive" if medical/financial/legal capsules are involved
    or the question mentions sensitive topics. Otherwise "standard".
    """
    # Check capsule categories
    for c in capsules:
        cat = (c.get("category") or "").lower()
        ctype = (c.get("capsule_type") or c.get("type") or "").lower()
        if cat in SENSITIVE_CATEGORIES or ctype in SENSITIVE_CATEGORIES:
            return "sensitive"

    # Check question keywords
    q_lower = question.lower()
    if any(kw in q_lower for kw in SENSITIVE_KEYWORDS):
        return "sensitive"

    return "standard"


# ═══════════════════════════════════════════════════════════════
# Agent Response Functions
# ═══════════════════════════════════════════════════════════════

def _minimize_capsules_for_public(capsules: list[dict]) -> list[dict]:
    """Strip potentially leaky metadata from capsules at public trust.

    Removes fields that could help an attacker map the network topology
    (e.g., 'source', 'shared_by', 'related_users') while keeping the
    core content that the capsule owner chose to make public.
    """
    stripped = []
    for c in capsules:
        clean = {
            "capsule_type": c.get("capsule_type", "note"),
            "title": c.get("title", ""),
            "content": c.get("content", ""),
            "visibility": c.get("visibility", "open"),
            "category": c.get("category", "general"),
        }
        # Keep governance flags — they're about the capsule, not the network
        if c.get("emergency_accessible"):
            clean["emergency_accessible"] = True
        stripped.append(clean)
    return stripped


async def agent_respond(
    agent: Agent,
    question: str,
    trust_level: str,
    shared_networks: list[Network],
    capsules: list[dict],
    requester_name: str,
    owner_name: str,
) -> str:
    """Cross-query: agent reasons about what to share (read-only, no tools)."""
    trust_context = build_trust_context(trust_level, shared_networks, requester_name, owner_name)

    # Context minimization: strip metadata at public trust to reduce leak surface
    if trust_level == "public":
        capsules = _minimize_capsules_for_public(capsules)

    formatted = format_capsules(capsules)

    system_prompt = CROSS_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        requester_name=requester_name,
        trust_level=trust_level,
        trust_context=trust_context,
        formatted_capsules=formatted,
    )

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()
    response = await router.complete(
        messages=[{"role": "user", "content": question}],
        system=system_prompt,
        model="fast",
        sensitivity=sensitivity,
        max_tokens=1024,
    )

    return response.text or ""


async def agent_respond_with_tools(
    agent: Agent,
    question: str,
    capsules: list[dict],
    owner_name: str,
    tool_context: ToolContext,
    personality: str = "",
) -> tuple[str, list[dict]]:
    """Self-query: agent responds with tool access (search, save, update).

    Returns (response_text, actions_taken).
    """
    formatted = format_capsules(capsules)
    networks_list = format_networks(tool_context.networks)

    system_prompt = SELF_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        formatted_capsules=formatted,
        networks_list=networks_list,
        personality_instruction=_personality_note(personality),
    )

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()
    messages: list[dict] = [{"role": "user", "content": question}]

    # Tool-use loop (max 5 round-trips to prevent runaway)
    for _ in range(5):
        response = await router.complete(
            messages=messages,
            system=system_prompt,
            model="reasoning",
            sensitivity=sensitivity,
            tools=AGENT_TOOLS,
            max_tokens=2048,
        )

        # If the response is a final text (no tool use), we're done
        if response.stop_reason == "end_turn":
            return response.text or "Done.", tool_context.actions

        # Process tool calls
        if response.stop_reason == "tool_use":
            # Build assistant content blocks for Anthropic message format
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call, scan results with Citadel, collect
            tool_results = []
            for tc in response.tool_calls:
                result_str = await execute_tool(tc.name, tc.input, tool_context)
                # Citadel scan on tool outputs (web_search, query_peer most important)
                if tc.name in ("web_search", "query_peer", "request_quotes"):
                    from src import citadel
                    output_scan = await citadel.scan_output(result_str)
                    if not output_scan.is_safe:
                        log.warning(f"Citadel flagged {tc.name} output: {output_scan.findings}")
                        result_str = json.dumps({
                            "warning": "Content flagged by security scan",
                            "findings": output_scan.findings,
                            "original_truncated": result_str[:200] + "...",
                        })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })

            # Send tool results back to the model
            messages.append({"role": "user", "content": tool_results})
        else:
            # Audit self-query on final answer
            try:
                from src.audit import log_event
                await log_event(
                    tool_context.db,
                    actor_user_id=tool_context.owner_id,
                    target_user_id=tool_context.owner_id,
                    action="agent_query",
                    event_type="query",
                    decision="allowed",
                    details={"question_preview": question[:120], "tools_used": len(tool_context.actions)},
                )
                await tool_context.db.commit()
            except Exception:
                pass
            return (
                response.text or "I'm not sure how to help with that.",
                tool_context.actions,
            )

    # Max iterations reached
    return "I've completed the requested actions.", tool_context.actions


# ═══════════════════════════════════════════════════════════════
# Streaming Agent Responses
# ═══════════════════════════════════════════════════════════════

async def agent_respond_streaming(
    agent: Agent,
    question: str,
    trust_level: str,
    shared_networks: list[Network],
    capsules: list[dict],
    requester_name: str,
    owner_name: str,
    conversation_history: list[dict] | None = None,
):
    """Cross-query streaming: yields text chunks as they arrive."""
    trust_context = build_trust_context(trust_level, shared_networks, requester_name, owner_name)
    formatted = format_capsules(capsules)

    system_prompt = CROSS_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        requester_name=requester_name,
        trust_level=trust_level,
        trust_context=trust_context,
        formatted_capsules=formatted,
    )

    # Build messages with conversation history for continuity
    messages: list[dict] = []
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 10 exchanges max
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()
    async for chunk in router.stream_complete(
        messages=messages,
        system=system_prompt,
        model="fast",
        sensitivity=sensitivity,
        max_tokens=1024,
    ):
        yield chunk


async def agent_respond_with_tools_streaming(
    agent: Agent,
    question: str,
    capsules: list[dict],
    owner_name: str,
    tool_context: ToolContext,
    conversation_history: list[dict] | None = None,
    personality: str = "",
):
    """Self-query streaming: runs tool loop non-streaming, then streams final response.

    Yields tuples of (event_type, data):
      ("tool", {"name": ..., "input": ...})  — tool being called
      ("text", "chunk")                       — text being streamed
      ("actions", [...])                      — final actions list
    """
    formatted = format_capsules(capsules)
    networks_list = format_networks(tool_context.networks)

    system_prompt = SELF_QUERY_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        formatted_capsules=formatted,
        networks_list=networks_list,
        personality_instruction=_personality_note(personality),
    )

    sensitivity = detect_sensitivity(capsules, question)
    router = get_router()

    # Build messages with conversation history for continuity
    messages: list[dict] = []
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 10 exchanges max
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    # Tool-use loop (non-streaming for tool rounds)
    for _ in range(5):
        response = await router.complete(
            messages=messages,
            system=system_prompt,
            model="reasoning",
            sensitivity=sensitivity,
            tools=AGENT_TOOLS,
            max_tokens=2048,
        )

        if response.stop_reason == "end_turn":
            # Final response — yield the text we already have
            text = response.text or "Done."
            # Yield in chunks for streaming feel
            chunk_size = 4
            words = text.split(" ")
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                if i > 0:
                    chunk = " " + chunk
                yield ("text", chunk)
            yield ("actions", tool_context.actions)
            return

        if response.stop_reason == "tool_use":
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                yield ("tool", {"name": tc.name, "input": tc.input})
                result_str = await execute_tool(tc.name, tc.input, tool_context)
                if tc.name in ("web_search", "query_peer", "request_quotes"):
                    from src import citadel
                    output_scan = await citadel.scan_output(result_str)
                    if not output_scan.is_safe:
                        result_str = json.dumps({
                            "warning": "Content flagged by security scan",
                            "findings": output_scan.findings,
                            "original_truncated": result_str[:200] + "...",
                        })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop — just yield the text
            if response.text:
                yield ("text", response.text)
            yield ("actions", tool_context.actions)
            return

    yield ("text", "I've completed the requested actions.")
    yield ("actions", tool_context.actions)


# ═══════════════════════════════════════════════════════════════
# Profile Extraction (Haiku 4.5 — fast, structured output)
# ═══════════════════════════════════════════════════════════════

PROFILE_EXTRACTION_PROMPT = """Extract structured profile data from this user bio. Return valid JSON only.

Bio: "{bio}"
Display name: "{display_name}"

Return this exact JSON structure (use null for unknown fields, empty arrays for no data):
{{
  "occupation": {{"title": "string or null", "industry": "string or null"}},
  "skills": [{{"name": "string", "category": "technical|professional|personal|certified"}}],
  "interests": [{{"name": "string", "category": "hobby|sport|academic|creative"}}],
  "family_status": "single|married|parent|unknown",
  "age_range": "string or null",
  "location_hints": ["strings"]
}}

Be concise. Only extract what's clearly stated or strongly implied."""


async def extract_profile(bio: str, display_name: str) -> dict | None:
    """Extract structured profile data from a bio using fast model."""
    if not bio or not bio.strip():
        return None
    try:
        router = get_router()
        response = await router.complete(
            messages=[{
                "role": "user",
                "content": PROFILE_EXTRACTION_PROMPT.format(bio=bio, display_name=display_name),
            }],
            model="fast",
            max_tokens=500,
        )
        text = (response.text or "").strip()
        # Extract JSON from response (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as e:
        log.warning(f"Profile extraction failed for {display_name}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# Morning Briefing
# ═══════════════════════════════════════════════════════════════

INTAKE_SYSTEM_PROMPT = """You are {owner_name}'s personal AI agent, getting to know them for the first time.

Your goal: Have a warm, natural conversation and save key facts as encrypted capsules in their vault.

## Conversation so far
{conversation_history}

## Flow — 4 topics (follow this order, but keep it natural):

1. **Work & Life** — Job title, company/school, location, commute, daily life. Save as "skill" capsule (category: "work").

2. **Health & Body** — Food allergies, drug allergies, dietary restrictions, exercise habits, medical conditions. Save as "preference" capsule (category: "health").

3. **Family & Home** — Partner, kids (names/ages), pets, living situation, key people. Save as "contact" capsule (category: "family").

4. **Goals & Interests** — Hobbies, what they want TrustMesh to help with, personal goals. Save as "preference" capsule (category: "personal").

After all 4 topics: **Wrap up** — Summarize what you learned, tell them their vault is set up, suggest exploring the dashboard.

## Conversation driver rules (CRITICAL — follow these exactly):
- You are the DRIVER of this conversation. Don't be passive.
- EVERY response you give MUST end with a question to the user. No exceptions until the final wrap-up.
- After the user answers, ALWAYS: (1) acknowledge briefly in 1 sentence, then (2) ask the NEXT specific question.
- FORBIDDEN responses: "Done.", "Perfect!", "Great!", "Got it.", or ANY response without a follow-up question. These are conversation-killers.
- Follow a clear progression: Work & Life → Health & Body → Family & Home → Goals & Interests.
- Example good response: "Got it, software engineer in SF! Do you have any food allergies or dietary restrictions I should know about?"
- Example bad response: "Done." (NEVER do this — always include a follow-up question)
- If the user gives a very short answer, probe deeper: "Tell me more — what kind of [topic]?"
- Track which topics you've covered. When all 4 are done, wrap up with a summary.
- After saving a capsule, immediately transition to the next topic with a natural bridge question.
- Get the user to share more if possible. Ask follow-up questions to draw out details.

## Input quality rules:
- If the user sends gibberish, random characters, or meaningless text (e.g., "asdasdasd", "xxxxxxxxx", keyboard mashing), DO NOT accept it or save a capsule. Say something like: "Hmm, that doesn't look right — could you try again?"
- Do NOT save gibberish as a capsule. Only save meaningful, coherent information.
- If a message is very short (1-2 words) and incomplete, ask a follow-up before saving.
- Never respond with "Perfect!" or "Great!" to nonsensical input.

## Style rules:
- Talk like a friendly human, not a form. Be curious, ask follow-ups.
- ONE question at a time. Short responses — 2-3 sentences max.
- After each answer, save a capsule IMMEDIATELY. Don't wait.
- Default tier is "private" unless they say otherwise.
- Don't number your questions or say "Step 1". Just flow naturally.
- If they give a long answer, save MULTIPLE capsules (one per distinct fact).
- If they say "skip", "done", or "that's it" — end immediately with a summary.

## First message:
Start with something warm and specific: "Hey! So tell me a bit about yourself — where are you based and what do you do?" Don't repeat their name or bio back to them.

## Capsule types:
- "skill" — job, expertise, education (category: "work")
- "preference" — hobbies, interests, likes, allergies, diet (category: "health" or "personal")
- "contact" — family, friends, colleagues, pets (category: "family")
- "schedule" — regular commitments, appointments
- "procedure" — routines, habits, workflows
- "memory" — stories, observations, life events

Always search_vault first to avoid duplicates.
{personality_instruction}"""

INTAKE_TOOLS = [
    AGENT_TOOLS[0],  # search_vault
    AGENT_TOOLS[1],  # save_capsule
]


async def run_intake_step(
    owner_name: str,
    user_message: str,
    conversation_history: list[dict],
    tool_context: ToolContext,
    personality: str = "",
) -> tuple[str, list[dict]]:
    """Run one step of the intake conversation. Returns (response_text, actions)."""
    # Format conversation history for the system prompt
    history_text = ""
    for msg in conversation_history:
        role = "You" if msg["role"] == "assistant" else owner_name
        history_text += f"{role}: {msg['content']}\n"

    system_prompt = INTAKE_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        conversation_history=history_text or "(This is the start of the conversation)",
        personality_instruction=_personality_note(personality),
    )

    router = get_router()
    messages: list[dict] = [{"role": "user", "content": user_message}]
    # Tool-use loop (max 3 round-trips for intake)
    for _ in range(3):
        response = await router.complete(
            messages=messages,
            system=system_prompt,
            model="fast",
            tools=INTAKE_TOOLS,
            max_tokens=1024,
        )

        if response.stop_reason == "end_turn":
            return response.text or "What else can you tell me about yourself?", tool_context.actions

        if response.stop_reason == "tool_use":
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                result_str = await execute_tool(tc.name, tc.input, tool_context)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })
            # Nudge: remind the model to respond with a follow-up question
            tool_results.append({
                "type": "text",
                "text": "[System: Capsule saved. Now respond to the user with a brief acknowledgment and your next question. Do NOT just say 'Done'.]",
            })
            messages.append({"role": "user", "content": tool_results})
        else:
            return response.text or "What else can you tell me about yourself?", tool_context.actions

    return "I've saved what we've discussed so far. What else would you like to share?", tool_context.actions


BRIEFING_SYSTEM_PROMPT = """You are {owner_name}'s personal agent. Create a concise {time_of_day} briefing.

Current time context: {time_of_day} on a {day_type}.
{day_guidance}

Prioritize: health/safety, time-sensitive items, then social.
Be warm but concise. Include specific times, dates, names.
Use markdown formatting with headers (NOT tables — use lists instead). Keep it under 500 words.
If there's little to report, keep it brief — no filler."""


def _get_briefing_time_context() -> tuple[str, str, str]:
    """Return (time_of_day, day_type, day_guidance) based on current local time."""
    from datetime import datetime
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    else:
        time_of_day = "evening"

    is_weekend = weekday >= 5
    day_type = "weekend" if is_weekend else "weekday"

    if is_weekend:
        day_guidance = (
            "It's the weekend — focus on personal plans, family activities, rest, and any fun events. "
            "De-emphasize work tasks unless they're truly urgent deadlines."
        )
    elif time_of_day == "morning":
        day_guidance = (
            "Group by: Today's Schedule, Action Items, Upcoming, Network Updates. "
            "Focus on what needs attention today."
        )
    elif time_of_day == "afternoon":
        day_guidance = (
            "Group by: Remaining Today, Evening Plans, Tomorrow Preview, Updates. "
            "Focus on what's left today and what's coming up."
        )
    else:
        day_guidance = (
            "Group by: Tonight, Tomorrow Preview, This Week Ahead, Updates. "
            "Help wind down — summarize what happened and what's next."
        )

    return time_of_day, day_type, day_guidance


async def generate_briefing(
    owner_name: str,
    capsules: list[dict],
    pending_tasks: list[dict],
    recent_network_capsules: list[dict],
    pending_requests: int,
    unread_notifications: int,
) -> str:
    """Generate a time-aware briefing using Sonnet 4.5."""
    time_of_day, day_type, day_guidance = _get_briefing_time_context()

    context_parts = []

    if capsules:
        context_parts.append("## Your Knowledge (schedules, tasks, events):")
        for c in capsules[:10]:
            context_parts.append(f"- [{c['capsule_type']}] {c['title']}: {c['content'][:200]}")

    if pending_tasks:
        context_parts.append("\n## Pending Tasks:")
        for t in pending_tasks:
            context_parts.append(f"- [{t['status']}] {t['title']}: {t['description'][:100]}")

    if recent_network_capsules:
        context_parts.append("\n## Recent Network Updates:")
        for c in recent_network_capsules[:5]:
            context_parts.append(f"- [{c.get('owner_name', 'Someone')}] {c['title']}: {c['content'][:150]}")

    if pending_requests:
        context_parts.append(f"\n## Pending: {pending_requests} connection request(s)")

    if unread_notifications:
        context_parts.append(f"\n## Unread: {unread_notifications} notification(s)")

    greeting = {"morning": "Good morning", "afternoon": "Good afternoon", "evening": "Good evening"}[time_of_day]

    if not context_parts:
        return f"{greeting}, {owner_name}! Your schedule is clear and there are no pending items. Enjoy your {'weekend' if day_type == 'weekend' else 'day'}!"

    context = "\n".join(context_parts)

    router = get_router()
    response = await router.complete(
        messages=[{"role": "user", "content": f"Here's what I know. Generate my briefing:\n\n{context}"}],
        system=BRIEFING_SYSTEM_PROMPT.format(
            owner_name=owner_name,
            time_of_day=time_of_day,
            day_type=day_type,
            day_guidance=day_guidance,
        ),
        model="fast",
        max_tokens=1024,
    )

    return response.text or f"{greeting}, {owner_name}!"
