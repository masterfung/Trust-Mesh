"""Gemini Live bidirectional agent — real-time voice + tools over WebSocket.

Architecture:
  Browser/App ←─── WebSocket ──→ LiveAgentSession ←─── Gemini Live API
                                         │
                                  TrustMesh tools
                                  (direct DB access)

Wire format (client ↔ server JSON frames):
  Client → server:
    {"type": "audio",   "data": "<base64 PCM 16kHz 16-bit mono>"}
    {"type": "text",    "text": "..."}            # text turn (typing)
    {"type": "inject",  "text": "..."}            # server-side interrupt signal

  Server → client:
    {"type": "audio",   "data": "<base64 PCM 24kHz 16-bit mono>"}
    {"type": "text",    "text": "..."}            # model text output
    {"type": "transcript", "text": "..."}         # user speech transcript
    {"type": "tool_call",  "name": "...", "input": {...}}
    {"type": "tool_result","name": "...", "result": "...truncated..."}
    {"type": "error",   "message": "..."}
"""

import asyncio
import base64
import datetime
import json
import logging
import os
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
_FALLBACK_MODEL = "gemini-2.0-flash-live-001"

# Subset of AGENT_TOOLS most useful in live voice context
_LIVE_TOOL_NAMES = {
    "search_vault",
    "save_capsule",
    "query_peer",
    "check_calendar",
    "discover_agents",
    "list_connections",
    "web_search",
    "create_timeline_entry",
    "list_timeline_entries",
    "trigger_emergency",
    "send_message",
}


# ── Schema helpers ─────────────────────────────────────────────

def _uppercase_types(schema: dict) -> dict:
    """Recursively uppercase all 'type' string values for Gemini native API.

    JSON Schema uses lowercase ('object', 'string'); Gemini native SDK
    expects uppercase ('OBJECT', 'STRING').
    """
    result = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            result[k] = v.upper()
        elif k == "properties" and isinstance(v, dict):
            result[k] = {pk: _uppercase_types(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            result[k] = _uppercase_types(v)
        elif isinstance(v, dict):
            result[k] = _uppercase_types(v)
        else:
            result[k] = v
    return result


def _build_live_tool_declarations() -> list[dict]:
    """Convert the subset of AGENT_TOOLS to Gemini function_declarations format."""
    from src.agents import AGENT_TOOLS
    declarations = []
    for tool in AGENT_TOOLS:
        if tool["name"] not in _LIVE_TOOL_NAMES:
            continue
        declarations.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": _uppercase_types(tool.get("input_schema", {})),
        })
    return declarations


# ── System instruction ─────────────────────────────────────────

_LIVE_SYSTEM_INSTRUCTION = """You are {owner_name}'s personal TrustMesh agent.
You have access to their encrypted knowledge vault, trust network, and connections.

Current date and time: {current_time}

Your capabilities:
- Search their vault for any personal knowledge (search_vault)
- Answer questions by querying trusted peers in their network (query_peer)
- Check their calendar and upcoming events (check_calendar)
- Save new information they share with you (save_capsule)
- Discover and connect to agents in the network (discover_agents)
- List who they're connected to and their trust levels (list_connections)
- Search the web for current information (web_search)
- Create and list timeline reminders (create_timeline_entry, list_timeline_entries)
- Declare a medical emergency and issue real access tokens (trigger_emergency)

IMPORTANT:
- You are voice-native. Be conversational, warm, and concise.
- Proactively notice conflicts, risks, or things that matter — speak up.
- When you retrieve health, financial, or sensitive information, confirm
  you're speaking to {owner_name} before sharing details.
- Respect trust levels: only share what you're allowed to share with others.
- If you find a scheduling conflict, calendar clash, or medical concern,
  mention it naturally in conversation — don't wait to be asked.
- If {owner_name} says they are in immediate danger, having a medical emergency,
  or needs urgent help, call trigger_emergency IMMEDIATELY — do not ask for
  confirmation first. Time is critical.

Your trust network context:
{networks_summary}
"""


def _format_time(tz_name: str) -> str:
    """Return a human-readable current date+time for the given IANA timezone name."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz=tz)
    return now.strftime("%A, %B %d, %Y at %I:%M %p %Z").replace(" 0", " ")


async def _build_system_instruction(
    user_display_name: str, networks: list[dict], tz: str = "UTC"
) -> str:
    """Build the static system instruction for this user's live session."""
    if networks:
        lines = [f"- {n['name']} ({n.get('network_type', 'custom')})" for n in networks[:8]]
        networks_summary = "\n".join(lines)
    else:
        networks_summary = "(no networks yet)"

    return _LIVE_SYSTEM_INSTRUCTION.format(
        owner_name=user_display_name,
        current_time=_format_time(tz),
        networks_summary=networks_summary,
    )


# ── Live session ───────────────────────────────────────────────

async def run_live_session(
    websocket: WebSocket,
    user_id: str,
    user_display_name: str,
    db,
    networks: list[dict],
    tz: str = "UTC",
) -> None:
    """Drive a full Gemini Live bidirectional session for one user.

    Runs until the WebSocket closes or an unrecoverable error occurs.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        await websocket.send_json({"type": "error", "message": "GOOGLE_API_KEY not configured"})
        return

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        await websocket.send_json({"type": "error", "message": "google-genai not installed"})
        return

    from src.agents import AGENT_TOOLS, ToolContext, execute_tool
    from src.gossip import get_user_networks
    from src import live_sessions

    tool_context = ToolContext(
        db=db,
        vault_key=b"__transit__",   # sentinel — tools use transit_bridge directly
        owner_id=user_id,
        owner_name=user_display_name,
        networks=networks,
    )

    system_instruction = await _build_system_instruction(user_display_name, networks, tz)
    declarations = _build_live_tool_declarations()

    client = genai.Client(api_key=api_key)

    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            role="user",
            parts=[types.Part(text=system_instruction)],
        ),
        tools=[types.Tool(function_declarations=declarations)] if declarations else [],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        # Disable extended thinking — the 2.5 native-audio preview model's thinking
        # mode generates non-audio parts that silently terminate multi-turn sessions.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    inject_queue: asyncio.Queue = asyncio.Queue()
    await live_sessions.register(user_id, inject_queue)

    async def _run_tasks(session) -> None:
        """Drive the three concurrent directions for one Gemini session."""
        tasks = [
            asyncio.create_task(_forward_client_to_gemini(websocket, session)),
            asyncio.create_task(_forward_gemini_to_client(session, websocket, tool_context)),
            asyncio.create_task(_inject_reader(inject_queue, session)),
        ]
        # FIRST_EXCEPTION: keep running until a task raises (e.g. WebSocketDisconnect),
        # not on normal completion (e.g. receive() finishing one turn).
        _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    try:
        # Try the native-audio preview model; fall back to the stable release if
        # the preview has expired (HTTP 404 / "not found" on context-manager entry).
        for model in (LIVE_MODEL, _FALLBACK_MODEL):
            log.info("Starting Live session: user=%s model=%s", user_id, model)
            try:
                async with client.aio.live.connect(model=model, config=live_config) as session:
                    await _run_tasks(session)
                break  # session completed normally — don't retry
            except Exception as exc:
                err = str(exc).lower()
                if model != _FALLBACK_MODEL and any(k in err for k in ("not found", "404", "model")):
                    log.warning("Model %s unavailable (%s) — retrying with %s", model, exc, _FALLBACK_MODEL)
                    continue
                raise  # Unexpected error — let outer handler deal with it

    except WebSocketDisconnect:
        log.info(f"Live session disconnected: user={user_id}")
    except Exception as exc:
        log.exception(f"Live session error: user={user_id}")
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        await live_sessions.unregister(user_id)


async def _forward_client_to_gemini(websocket: WebSocket, session) -> None:
    """Read audio/text frames from the WebSocket and send them to Gemini Live."""
    from google.genai import types

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            msg_type = payload.get("type")

            if msg_type == "audio":
                pcm_bytes = base64.b64decode(payload["data"])
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=pcm_bytes,
                        mime_type="audio/pcm;rate=16000",
                    )
                )
            elif msg_type == "text":
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=payload["text"])],
                    )
                )
            elif msg_type == "inject":
                # Server-side proactive interrupt injected from timeline / external event
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=f"[SYSTEM NOTE — share this with the user]: {payload['text']}")],
                    )
                )

    except WebSocketDisconnect:
        raise
    except Exception as exc:
        log.debug(f"_forward_client_to_gemini exited: {exc}")
        raise


async def _inject_reader(queue: asyncio.Queue, session) -> None:
    """Read injected messages from the queue and send them to Gemini as system notes.

    These arrive from the Timeline engine when a proactive finding is ready
    (e.g., a scheduling conflict detected in vault data). The message is sent
    as a user turn so Gemini speaks it unprompted to the user.
    """
    from google.genai import types

    try:
        while True:
            text = await queue.get()
            log.info("Sending injected message to Gemini: %.80s...", text)
            try:
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(
                            text=f"[SYSTEM NOTE — share this with the user naturally]: {text}"
                        )],
                    )
                )
            except Exception as exc:
                log.warning("Failed to send injected message: %s", exc)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.debug("_inject_reader exited: %s", exc)
        raise


async def _forward_gemini_to_client(session, websocket: WebSocket, tool_context) -> None:
    """Read Gemini responses and forward audio/text/tool events to the client."""
    from google.genai import types

    try:
        async for response in session.receive():
            # Audio chunks
            if response.data:
                await websocket.send_json({
                    "type": "audio",
                    "data": base64.b64encode(response.data).decode(),
                })

            # Agent speech transcript (from output_audio_transcription)
            # User speech transcript (from input_audio_transcription)
            if response.server_content:
                sc = response.server_content
                if sc.output_transcription and sc.output_transcription.text:
                    await websocket.send_json({
                        "type": "text",
                        "text": sc.output_transcription.text,
                    })
                if sc.input_transcription and sc.input_transcription.text:
                    await websocket.send_json({
                        "type": "transcript",
                        "text": sc.input_transcription.text,
                    })

            # Fallback: plain text from model
            elif response.text:
                await websocket.send_json({"type": "text", "text": response.text})

            # Tool calls
            if response.tool_call:
                results = await _execute_tools(
                    response.tool_call.function_calls,
                    tool_context,
                    websocket,
                )
                await session.send_tool_response(function_responses=results)

    except WebSocketDisconnect:
        raise
    except Exception as exc:
        log.debug(f"_forward_gemini_to_client exited: {exc}")
        raise


async def _execute_tools(function_calls, tool_context, websocket: WebSocket) -> list:
    """Execute a batch of Gemini function calls via TrustMesh tool handlers."""
    from google.genai import types
    from src.agents import execute_tool
    from src import citadel

    results = []
    for fc in function_calls:
        # Notify client so the UI can show "🔍 Searching vault..."
        try:
            await websocket.send_json({
                "type": "tool_call",
                "name": fc.name,
                "input": dict(fc.args),
            })
        except Exception:
            pass

        try:
            result_str = await execute_tool(fc.name, dict(fc.args), tool_context)

            # Citadel scan for external-data tools
            if fc.name in ("web_search", "query_peer", "request_quotes"):
                scan = await citadel.scan_output(result_str)
                if not scan.is_safe:
                    log.warning(f"Citadel blocked Live tool output: {fc.name} → {scan.findings}")
                    result_str = json.dumps({
                        "warning": "Content blocked by security scan",
                        "findings": scan.findings,
                    })

        except Exception as exc:
            log.warning(f"Tool {fc.name} failed: {exc}")
            result_str = json.dumps({"error": str(exc)})

        # Notify client with a brief result preview
        try:
            preview = result_str[:120] + "…" if len(result_str) > 120 else result_str
            await websocket.send_json({
                "type": "tool_result",
                "name": fc.name,
                "result": preview,
            })
        except Exception:
            pass

        results.append(types.FunctionResponse(
            id=fc.id,
            name=fc.name,
            response={"result": result_str},
        ))

    return results


# ── Ephemeral token ────────────────────────────────────────────

async def create_ephemeral_token(expire_minutes: int = 30) -> dict:
    """Generate a short-lived Gemini ephemeral token for direct client connections.

    Useful for low-latency mobile clients (Expo) that connect directly to
    Gemini Live without going through the server proxy.
    """
    import datetime

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")

    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai not installed")

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    client = genai.Client(
        api_key=api_key,
        http_options={"api_version": "v1alpha"},
    )

    token = client.auth_tokens.create(config={
        "uses": 1,
        "expire_time": now + datetime.timedelta(minutes=expire_minutes),
        "new_session_expire_time": now + datetime.timedelta(minutes=2),
    })

    # token.name is "auth_tokens/<hash>" — the hash is the usable token value
    token_value = token.name.split("/")[-1] if "/" in token.name else token.name

    return {
        "token": token_value,
        "token_name": token.name,
        "model": LIVE_MODEL,
        "expires_in": expire_minutes * 60,
    }
