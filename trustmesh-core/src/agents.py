"""Opus 4.6 personal agent logic — the core intelligence layer."""

import os

import anthropic

from src.models import Agent, KnowledgeCapsule, Network

ANTHROPIC_MODEL = "claude-opus-4-6"

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def build_trust_context(trust_level: str, shared_networks: list[Network], requester_name: str) -> str:
    """Build human-readable trust context for the agent prompt."""
    if trust_level == "private":
        return f"{requester_name} is the vault owner. Full access to all knowledge."
    elif trust_level == "network":
        network_names = ", ".join(n.name for n in shared_networks)
        return (
            f"{requester_name} is connected and shares these networks: {network_names}. "
            f"They can access public capsules and capsules shared to these networks."
        )
    else:
        return (
            f"{requester_name} has public access only. "
            f"They are not in any of your owner's networks. "
            f"Only share information from public capsules."
        )


def format_capsules(capsules: list[dict]) -> str:
    """Format capsules for the agent prompt."""
    if not capsules:
        return "No knowledge capsules available for this requester."

    parts = []
    for c in capsules:
        freshness_note = ""
        if c.get("expires_at"):
            freshness_note = f" [Expires: {c['expires_at']}]"
        elif c.get("freshness") == "temporary":
            freshness_note = " [Temporary — may be outdated]"

        parts.append(
            f"[{c['capsule_type'].upper()}] {c['title']}{freshness_note}\n"
            f"Tier: {c['tier']} | Category: {c.get('category', 'general')}\n"
            f"{c['content']}\n"
        )
    return "\n---\n".join(parts)


AGENT_SYSTEM_PROMPT = """You are {owner_name}'s personal AI agent in the TrustMesh network.

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
7. Keep responses concise but complete. Don't add unnecessary preamble."""


async def agent_respond(
    agent: Agent,
    question: str,
    trust_level: str,
    shared_networks: list[Network],
    capsules: list[dict],
    requester_name: str,
    owner_name: str,
) -> str:
    """Have the Opus 4.6 agent reason about what to share."""
    trust_context = build_trust_context(trust_level, shared_networks, requester_name)
    formatted = format_capsules(capsules)

    system_prompt = AGENT_SYSTEM_PROMPT.format(
        owner_name=owner_name,
        requester_name=requester_name,
        trust_level=trust_level,
        trust_context=trust_context,
        formatted_capsules=formatted,
    )

    client = get_client()
    response = await client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )

    return response.content[0].text
