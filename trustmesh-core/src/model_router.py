"""Model router — routes to Gemini, Anthropic, or TEE providers based on sensitivity.

Routing priority (first available wins):
  sensitive  → TEE (Tinfoil / Redpill)   — opaque execution, can't see plaintext
  standard   → Gemini (via OpenAI-compat) — if GOOGLE_API_KEY is set
  standard   → Anthropic                  — fallback when no GOOGLE_API_KEY

All providers use Anthropic-format messages as the internal canonical format.
The router converts to whatever each provider expects and normalises responses
back to a unified ModelResponse before returning.

Usage:
    router = get_router()
    response = await router.complete(
        messages=[{"role": "user", "content": "..."}],
        system="You are a helpful agent.",
        model="default",          # "default", "fast", or "reasoning"
        sensitivity="standard",   # "standard" or "sensitive"
        tools=None,               # Anthropic-format tool defs (input_schema key)
        max_tokens=1024,
    )
    # response is always a ModelResponse — same shape regardless of provider.
"""

import json
import logging
import os
from dataclasses import dataclass, field

import anthropic

log = logging.getLogger(__name__)


# ── Response types (unified across providers) ──────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ModelResponse:
    """Unified response from any provider."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" or "tool_use"
    raw: object = None  # Original response for debugging


# ── Provider config ────────────────────────────────────────────

# Anthropic models
ANTHROPIC_MODELS = {
    "default": "claude-sonnet-4-5-20250929",
    "reasoning": "claude-sonnet-4-5-20250929",
    "fast": "claude-haiku-4-5-20251001",
}

# Gemini models via OpenAI-compatible endpoint
# https://generativelanguage.googleapis.com/v1beta/openai/
GEMINI_MODELS = {
    "default": "gemini-2.5-flash",
    "reasoning": "gemini-2.5-pro",
    "fast": "gemini-2.5-flash",
    "vision": "gemini-2.5-flash",
}
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# TEE models — all run inside Trusted Execution Environments (TDX/GPU enclaves).
# Provider literally cannot see your plaintext. Use for medical, financial, private data.
#
# Available TEE models (Redpill catalog):
#   moonshotai/kimi-k2.5          262K  $0.60/$3.00  chutes   — best general + tool calling
#   moonshotai/kimi-k2-thinking   262K  $2.00/$2.00  tinfoil  — reasoning model
#   deepseek/deepseek-v3.2        164K  $0.27/$0.40  chutes   — cheap + capable
#   deepseek/deepseek-r1-0528     164K  $2.00/$2.00  tinfoil  — reasoning
#   z-ai/glm-5                    203K  $1.20/$3.50  phala    — new, strong general
#   z-ai/glm-4.7-flash            203K  $0.10/$0.43  phala    — ultra-cheap fast
#   qwen/qwen3-coder-480b-a35b    262K  $2.00/$2.00  tinfoil  — code/tool specialist
#   minimax/minimax-m2.1           197K  $0.30/$1.20  chutes   — balanced
#   meta-llama/llama-3.3-70b      131K  $2.00/$2.00  tinfoil  — open-source standard
#   openai/gpt-oss-120b           131K  $0.10/$0.49  phala    — open-weight GPT

TINFOIL_MODELS = {
    "default": "kimi-k2.5",
    "reasoning": "kimi-k2-thinking",
    "fast": "llama3-3-70b",
}

REDPILL_MODELS = {
    "default": "z-ai/glm-5",                             # 203K ctx, strong tool calling, $1.20/$3.50
    "reasoning": "moonshotai/kimi-k2-thinking",           # 262K ctx, reasoning + tools, $2.00/$2.00
    "fast": "z-ai/glm-4.7-flash",                        # 203K ctx, ultra-cheap, $0.10/$0.43
    "vision": "qwen/qwen3-vl-30b-a3b-instruct",         # 128K ctx, multimodal, $0.20/$0.70
    "code": "openai/gpt-oss-120b",                       # 131K ctx, $0.10/$0.49, open-weight GPT
}


# ── Format converters (Anthropic <-> OpenAI/Gemini) ───────────
#
# Gemini's OpenAI-compatible endpoint accepts the same wire format as OpenAI,
# so we reuse the same converters for both — no separate Gemini converter needed.

def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool format to OpenAI/Gemini function-calling format.

    Anthropic:  {"name": ..., "description": ..., "input_schema": {...}}
    OpenAI/Gemini: {"type": "function", "function": {"name": ..., "parameters": {...}}}
    """
    openai_tools = []
    for t in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        })
    return openai_tools


def _anthropic_messages_to_openai(messages: list[dict], system: str = "") -> list[dict]:
    """Convert Anthropic message format to OpenAI/Gemini format.

    Handles tool_use and tool_result blocks in multi-turn tool loops.
    """
    openai_msgs = []
    if system:
        openai_msgs.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content")

        # Simple string content
        if isinstance(content, str):
            openai_msgs.append({"role": role, "content": content})
            continue

        # Anthropic content blocks (list)
        if isinstance(content, list):
            # tool_result blocks (user turn after tool calls)
            if content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                for block in content:
                    openai_msgs.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    })
                continue

            # Assistant content blocks (mix of text + tool_use)
            if role == "assistant":
                text_parts = []
                tool_calls = []
                for block in content:
                    if hasattr(block, "type"):
                        # Anthropic SDK objects
                        if block.type == "text":
                            text_parts.append(block.text)
                        elif block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": json.dumps(block.input),
                                },
                            })
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            })

                assistant_msg: dict = {"role": "assistant"}
                # Some providers reject null content when tool_calls are present;
                # use empty string instead.
                assistant_msg["content"] = "\n".join(text_parts) if text_parts else ""
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                openai_msgs.append(assistant_msg)
                continue

        # Fallback
        openai_msgs.append({"role": role, "content": str(content) if content else ""})

    return openai_msgs


def _openai_response_to_model_response(response) -> ModelResponse:
    """Convert an OpenAI/Gemini chat completion response to our unified ModelResponse."""
    choice = response.choices[0]
    message = choice.message

    tool_calls = []
    if message.tool_calls:
        for tc in message.tool_calls:
            tool_calls.append(ToolCall(
                id=tc.id,
                name=tc.function.name,
                input=json.loads(tc.function.arguments),
            ))

    return ModelResponse(
        text=message.content,
        tool_calls=tool_calls,
        stop_reason="tool_use" if tool_calls else "end_turn",
        raw=response,
    )


def _anthropic_response_to_model_response(response) -> ModelResponse:
    """Convert an Anthropic response to our unified ModelResponse."""
    text_parts = [b.text for b in response.content if b.type == "text"]
    tool_calls = []
    for b in response.content:
        if b.type == "tool_use":
            tool_calls.append(ToolCall(id=b.id, name=b.name, input=b.input))

    return ModelResponse(
        text="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls,
        stop_reason="tool_use" if response.stop_reason == "tool_use" else "end_turn",
        raw=response,
    )


# ── Router ─────────────────────────────────────────────────────

class ModelRouter:
    """Routes LLM calls to Gemini, Anthropic, or TEE providers.

    Routing:
      sensitive  → TEE provider  (Tinfoil or Redpill, if configured)
      standard   → Gemini        (if GOOGLE_API_KEY set)
      standard   → Anthropic     (fallback)
    """

    def __init__(self):
        self._anthropic: anthropic.AsyncAnthropic | None = None
        self._gemini_client = None   # AsyncOpenAI → Gemini compat endpoint
        self._gemini_models: dict = {}
        self._tee_client = None      # AsyncOpenAI → TEE provider
        self._tee_provider: str | None = None
        self._tee_models: dict = {}
        self._init_clients()

    def _init_clients(self):
        """Initialize available clients from env vars."""
        # Anthropic (fallback — always try)
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            self._anthropic = anthropic.AsyncAnthropic(api_key=api_key)

        # Gemini (standard path — preferred over Anthropic when key is set)
        self._init_gemini()

        # TEE provider (sensitive path — Tinfoil or Redpill)
        self._init_tee()

    def _init_gemini(self):
        """Initialize Gemini via its OpenAI-compatible endpoint."""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return
        try:
            from openai import AsyncOpenAI
            self._gemini_client = AsyncOpenAI(
                api_key=api_key,
                base_url=GEMINI_BASE_URL,
            )
            self._gemini_models = GEMINI_MODELS
            log.info("Gemini provider initialized (OpenAI-compat endpoint)")
        except ImportError:
            log.warning("openai package not installed — Gemini unavailable")

    def _init_tee(self):
        """Initialize TEE provider (Tinfoil or Redpill)."""
        primary = os.getenv("TEE_PRIMARY_PROVIDER", "tinfoil")
        providers = {
            "tinfoil": {
                "key_env": "TINFOIL_API_KEY",
                "base_url": os.getenv("TINFOIL_BASE_URL", "https://inference.tinfoil.sh/v1"),
                "models": TINFOIL_MODELS,
            },
            "redpill": {
                "key_env": "REDPILL_API_KEY",
                "base_url": os.getenv("REDPILL_BASE_URL", "https://api.redpill.ai/v1"),
                "models": REDPILL_MODELS,
            },
        }

        for provider_name in [primary, "redpill" if primary == "tinfoil" else "tinfoil"]:
            cfg = providers.get(provider_name)
            if not cfg:
                continue
            api_key = os.getenv(cfg["key_env"])
            if api_key:
                try:
                    from openai import AsyncOpenAI
                    self._tee_client = AsyncOpenAI(
                        api_key=api_key,
                        base_url=cfg["base_url"],
                    )
                    self._tee_provider = provider_name
                    self._tee_models = cfg["models"]
                    log.info(f"TEE provider initialized: {provider_name} at {cfg['base_url']}")
                    break
                except ImportError:
                    log.warning("openai package not installed — TEE providers unavailable")
                    break

    @property
    def has_gemini(self) -> bool:
        return self._gemini_client is not None

    @property
    def has_tee(self) -> bool:
        return self._tee_client is not None

    @property
    def tee_provider_name(self) -> str | None:
        return self._tee_provider

    # ── Public interface ───────────────────────────────────────

    async def complete(
        self,
        messages: list[dict],
        system: str = "",
        model: str = "default",
        sensitivity: str = "standard",
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
    ) -> ModelResponse:
        """Route a completion to the appropriate provider.

        Args:
            messages: Anthropic-format messages (internal canonical format).
            system: System prompt string.
            model: "default", "fast", or "reasoning".
            sensitivity: "standard" (Gemini/Anthropic) or "sensitive" (TEE).
            tools: Anthropic-format tool definitions (input_schema key).
            max_tokens: Max output tokens.

        Returns:
            Unified ModelResponse — same shape regardless of provider.
        """
        if sensitivity == "sensitive" and self._tee_client:
            tee_model = self._tee_models.get(model, self._tee_models.get("default", model))
            log.warning(f"[ROUTING] sensitivity={sensitivity} → TEE ({self._tee_provider}, {tee_model})")
            return await self._tee_complete(messages, system, model, tools, max_tokens)

        if self._gemini_client:
            gemini_model = self._gemini_models.get(model, self._gemini_models.get("default", model))
            log.warning(f"[ROUTING] → Gemini ({gemini_model})")
            return await self._gemini_complete(messages, system, model, tools, max_tokens)

        anthro_model = ANTHROPIC_MODELS.get(model, model)
        log.warning(f"[ROUTING] → Anthropic ({anthro_model})")
        return await self._anthropic_complete(messages, system, model, tools, max_tokens)

    async def stream_complete(
        self,
        messages: list[dict],
        system: str = "",
        model: str = "default",
        sensitivity: str = "standard",
        max_tokens: int = 1024,
    ):
        """Stream a completion, yielding text chunks as they arrive.

        Only supports final text responses (no tool use). For tool loops,
        use complete() for tool rounds and stream_complete() for the final round.

        Yields:
            str chunks of the response text.
        """
        if sensitivity == "sensitive" and self._tee_client:
            async for chunk in self._tee_stream(messages, system, model, max_tokens):
                yield chunk
        elif self._gemini_client:
            async for chunk in self._gemini_stream(messages, system, model, max_tokens):
                yield chunk
        else:
            async for chunk in self._anthropic_stream(messages, system, model, max_tokens):
                yield chunk

    # ── Provider implementations ───────────────────────────────

    async def _gemini_complete(self, messages, system, model, tools, max_tokens) -> ModelResponse:
        """Call Gemini via OpenAI-compatible endpoint.

        Reuses all existing Anthropic→OpenAI converters since Gemini's compat
        endpoint accepts the same wire format as OpenAI.
        """
        model_id = self._gemini_models.get(model, self._gemini_models.get("default", model))
        openai_messages = _anthropic_messages_to_openai(messages, system)

        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if tools:
            kwargs["tools"] = _anthropic_tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        response = await self._gemini_client.chat.completions.create(**kwargs)
        return _openai_response_to_model_response(response)

    async def _gemini_stream(self, messages, system, model, max_tokens):
        """Stream from Gemini via OpenAI-compatible endpoint."""
        model_id = self._gemini_models.get(model, self._gemini_models.get("default", model))
        openai_messages = _anthropic_messages_to_openai(messages, system)

        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": openai_messages,
            "stream": True,
        }

        stream = await self._gemini_client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def _anthropic_complete(self, messages, system, model, tools, max_tokens) -> ModelResponse:
        """Call Anthropic API."""
        if not self._anthropic:
            raise RuntimeError("No LLM provider configured. Set GOOGLE_API_KEY or ANTHROPIC_API_KEY.")

        model_id = ANTHROPIC_MODELS.get(model, model)
        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        response = await self._anthropic.messages.create(**kwargs)
        return _anthropic_response_to_model_response(response)

    async def _anthropic_stream(self, messages, system, model, max_tokens):
        """Stream from Anthropic API."""
        if not self._anthropic:
            raise RuntimeError("No LLM provider configured. Set GOOGLE_API_KEY or ANTHROPIC_API_KEY.")

        model_id = ANTHROPIC_MODELS.get(model, model)
        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        async with self._anthropic.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def _tee_complete(self, messages, system, model, tools, max_tokens) -> ModelResponse:
        """Call TEE provider (OpenAI-compatible API)."""
        model_id = self._tee_models.get(model, self._tee_models.get("default", model))
        openai_messages = _anthropic_messages_to_openai(messages, system)

        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": openai_messages,
        }
        if tools:
            kwargs["tools"] = _anthropic_tools_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        response = await self._tee_client.chat.completions.create(**kwargs)
        return _openai_response_to_model_response(response)

    async def _tee_stream(self, messages, system, model, max_tokens):
        """Stream from TEE provider (OpenAI-compatible API)."""
        model_id = self._tee_models.get(model, self._tee_models.get("default", model))
        openai_messages = _anthropic_messages_to_openai(messages, system)

        kwargs: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "messages": openai_messages,
            "stream": True,
        }

        stream = await self._tee_client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


# ── Singleton ──────────────────────────────────────────────────

_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    """Get or create the singleton ModelRouter."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
