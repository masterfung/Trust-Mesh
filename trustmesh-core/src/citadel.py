"""Citadel HTTP client for input/output security scanning.

When the Citadel Go sidecar is running (port 3001), all scanning is delegated there.
When Citadel is unavailable, a built-in heuristic fallback catches obvious attacks
so the demo works without the separate Go process.
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

CITADEL_URL = os.getenv("CITADEL_URL", "http://localhost:3001")
CITADEL_TIMEOUT = 2.0

# Circuit breaker: if 3 failures in 60s, skip Citadel for next 60s
_citadel_failures: list[float] = []
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_WINDOW = 60  # seconds
CIRCUIT_BREAKER_COOLDOWN = 60  # seconds
_circuit_open_until: float = 0.0

# Heuristic patterns for prompt injection detection (fallback when Citadel is down)
INJECTION_PATTERNS = [
    # Direct instruction override
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts|directions)", 0.95),
    (r"disregard\s+(all\s+)?(previous|your|the)\s+(instructions|rules|guidelines)", 0.95),
    (r"forget\s+(all\s+)?(previous|your|the)\s+(instructions|rules|context)", 0.90),
    # Obfuscated variants (character spacing)
    (r"i\s*g\s*n\s*o\s*r\s*e.{0,40}(previous|prior|above|earlier).{0,40}(instructions|rules|prompts|directions)", 0.95),
    # System prompt extraction
    (r"(reveal|show|display|print|output|repeat)\s+(your\s+)?(system\s+prompt|instructions|rules)", 0.90),
    (r"what\s+(are|is)\s+your\s+(system\s+prompt|instructions|rules|original)", 0.85),
    # Data exfiltration attempts
    (r"(reveal|show|expose|dump|list)\s+(all\s+)?(private|secret|hidden|confidential)\s+(capsules|data|info)", 0.95),
    (r"(reveal|show|expose|dump|list)\s+(all\s+)?(passwords?|credentials?|keys?|tokens?)", 0.95),
    (r"(reveal|show|expose|dump|list)\s+(all\s+)?(medical\s+records?|health\s+info)", 0.90),
    # Indirect exfiltration / hypothetical framing
    (r"\bhypothetically\b.{0,120}\b(private|secret|confidential|medical\s+records?|health\s+info|users?\s+in\s+this\s+system|database)\b", 0.85),
    # Role hijacking
    (r"you\s+are\s+now\s+(a|an|my)", 0.85),
    (r"(act|pretend|behave)\s+as\s+(if|though)\s+you", 0.80),
    (r"new\s+(instruction|role|persona|identity)", 0.85),
    # Roleplay + elevated access prompts
    (r"roleplay.{0,80}(full\s+database\s+access|database\s+access|admin|root|superuser|full\s+access)", 0.90),
    # Common non-English injection phrases (minimal set; demo safety)
    (r"忽略.{0,12}(之前|所有|先前).{0,12}指示", 0.95),
    (r"显示.{0,12}(所有|全部).{0,12}(私人|私密|秘密|隐私).{0,12}(数据|信息)", 0.95),
    # Encoding/obfuscation attacks
    (r"base64\s*(decode|encode)", 0.80),
    (r"translate\s+.{0,20}\s+to\s+(hex|binary|base64|rot13)", 0.80),
    # Multi-turn manipulation
    (r"in\s+the\s+previous\s+(conversation|message|turn).{0,30}you\s+(agreed|said|confirmed)", 0.75),
    # Delimiter injection
    (r"</?system>|</?user>|</?assistant>|\[INST\]|\[/INST\]", 0.90),
    # Tool manipulation — tricking agent into misusing tools
    (r"(call|use|invoke|run)\s+the\s+(save|update|delete|create)\s+tool\s+(to|and|with)", 0.85),
    (r"(execute|trigger)\s+(function|tool|command)\s+", 0.80),
    # Context confusion — claiming false context
    (r"(the\s+admin|system|developer)\s+(said|told|instructed|authorized)", 0.85),
    (r"(override|bypass|skip|disable)\s+(trust|security|citadel|scanning|visibility|governance)", 0.95),
    (r"(set|change|update)\s+(trust.?level|visibility|access)\s+to", 0.85),
    # Repeat-back attacks — extract training data or system info
    (r"(repeat|echo|recite|output)\s+(back|exactly|verbatim)", 0.80),
    (r"(what\s+tools|list\s+your\s+tools|what\s+functions)", 0.75),
    # Vault/capsule extraction
    (r"(show|reveal|list|dump|give)\s+(me\s+)?(all|every)\s+(capsule|vault|record|data|private)", 0.95),
    (r"(access|read|decrypt|unlock)\s+(private|internal|restricted|hidden)", 0.90),
]

OUTPUT_RISK_PATTERNS = [
    # Credential-like patterns
    (r"(password|passwd|pwd)\s*[:=]\s*\S+", "credential_leak"),
    (r"(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*\S+", "credential_leak"),
    (r"(sk-|pk-|rk-)[a-zA-Z0-9]{20,}", "api_key_leak"),
    # SSN / credit card patterns
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn_leak"),
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "credit_card_leak"),
    # Vault key / encryption key patterns
    (r"vault[_\s]?key\s*[:=]\s*\S+", "vault_key_leak"),
    (r"(encryption|master|private)[_\s]?key\s*[:=]\s*\S+", "encryption_key_leak"),
    (r"[A-Za-z0-9+/]{40,}={0,2}", "base64_blob_leak"),  # large base64 blobs (potential key material)
    # System prompt leak
    (r"(system\s+prompt|system\s+message)\s*[:]\s*", "system_prompt_leak"),
    (r"(my\s+instructions\s+are|i\s+was\s+told\s+to)", "instruction_leak"),
    # ── Soft-leak patterns (network topology / member disclosure) ──
    # Referral suggestions — "ask Peter", "contact Alice", "reach out to Dr. Lee"
    (r"\b(ask|contact|reach\s+out\s+to|talk\s+to|check\s+with|speak\s+to|consult)\s+[A-Z][a-z]+", "member_referral_hint"),
    # Referral to initials / coded names (e.g., "S.J.")
    (r"\b(ask|contact|reach\s+out\s+to|talk\s+to|check\s+with|speak\s+to|consult)\s+([A-Z]\.){2,4}(?=\s|$)", "member_referral_hint"),
    # Group/network existence hints — "our family", "my team", "the group"
    (r"\b(our|my)\s+(family|team|group|network|pool|circle|department|crew)\b", "network_structure_hint"),
    # Subtle group framing without explicit nouns (low-confidence, public trust only)
    (r"\bwe\s+usually\b.{0,80}\baround\s+here\b", "network_structure_hint"),
    # Team size disclosure ("There are five of us...")
    (r"\bthere\s+are\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+of\s+us\b", "team_size_hint"),
    # Role-based referrals without names ("Your project manager would know...")
    (r"\byour\s+project\s+manager\b", "role_referral_hint"),
    # Vague member hints — "someone who knows", "people in our"
    (r"\b(someone|somebody|people|folks|others)\s+(who|in\s+)?(our|my|the)\s+(family|team|group|network)", "soft_member_hint"),
    (r"\b(someone|somebody)\s+(else\s+)?(who\s+)?(knows?|might\s+know|can\s+help|could\s+help|has\s+that)", "soft_referral_hint"),
    # Existence of hidden information — "I have more but can't share"
    (r"\b(i\s+have|there\s+is|there\s+are)\s+(more|additional|other)\s+(information|data|details).{0,30}(can't|cannot|unable|not\s+allowed)", "hidden_data_hint"),
    (r"\b(restricted|classified|confidential|internal)\s+(information|data|details|records)\b", "restricted_data_hint"),
]

# Patterns that only apply at public trust (mentioning members is fine at network/private level)
SOFT_LEAK_CATEGORIES = {
    "member_referral_hint", "network_structure_hint",
    "soft_member_hint", "soft_referral_hint",
    "hidden_data_hint", "restricted_data_hint",
    "team_size_hint", "role_referral_hint",
}

SEVERITY_MAP = {
    "credential_leak": "critical",
    "api_key_leak": "critical",
    "vault_key_leak": "critical",
    "encryption_key_leak": "critical",
    "ssn_leak": "critical",
    "credit_card_leak": "critical",
    "system_prompt_leak": "high",
    "instruction_leak": "high",
    "base64_blob_leak": "high",
    "member_referral_hint": "info",
    "network_structure_hint": "info",
    "soft_member_hint": "info",
    "soft_referral_hint": "info",
    "hidden_data_hint": "info",
    "restricted_data_hint": "info",
    "team_size_hint": "info",
    "role_referral_hint": "info",
}

# Pre-compile all patterns at module load for performance
_COMPILED_INPUT_PATTERNS = [(re.compile(p, re.IGNORECASE), s) for p, s in INJECTION_PATTERNS]
_COMPILED_HARD_OUTPUT = [(re.compile(p, re.IGNORECASE), c) for p, c in OUTPUT_RISK_PATTERNS if c not in SOFT_LEAK_CATEGORIES]
_COMPILED_SOFT_OUTPUT = [(re.compile(p, re.IGNORECASE), c) for p, c in OUTPUT_RISK_PATTERNS if c in SOFT_LEAK_CATEGORIES]


@dataclass
class InputScanResult:
    decision: str = "ALLOW"
    heuristic_score: float = 0.0
    reason: str = ""
    latency_ms: int = 0


@dataclass
class OutputScanResult:
    is_safe: bool = True
    risk_score: int = 0
    risk_level: str = "NONE"
    findings: list[str] = field(default_factory=list)
    threat_categories: list[str] = field(default_factory=list)
    scan_mode: str = "heuristic"  # "citadel" or "heuristic"


def _is_circuit_open() -> bool:
    """Check if circuit breaker is open (Citadel should be skipped)."""
    if time.time() < _circuit_open_until:
        return True
    return False


def _record_citadel_failure():
    """Record a Citadel failure and potentially open the circuit."""
    global _circuit_open_until
    now = time.time()
    _citadel_failures.append(now)
    # Prune old failures
    cutoff = now - CIRCUIT_BREAKER_WINDOW
    while _citadel_failures and _citadel_failures[0] < cutoff:
        _citadel_failures.pop(0)
    # Open circuit if threshold reached
    if len(_citadel_failures) >= CIRCUIT_BREAKER_THRESHOLD:
        _circuit_open_until = now + CIRCUIT_BREAKER_COOLDOWN
        logger.warning(f"Citadel circuit breaker opened — skipping for {CIRCUIT_BREAKER_COOLDOWN}s")
        _citadel_failures.clear()


def _heuristic_input_scan(text: str) -> InputScanResult:
    """Built-in heuristic prompt injection detection (fallback)."""
    text_lower = text.lower()
    # Catch simple obfuscation like spaced-out letters: "i g n o r e previous i n s t r u c t i o n s"
    squashed = re.sub(r"[^a-z0-9]+", "", text_lower)
    if "ignorepreviousinstructions" in squashed or "ignoreallpreviousinstructions" in squashed:
        return InputScanResult(
            decision="BLOCK",
            heuristic_score=0.95,
            reason="Heuristic match: ignore previous instructions (squashed)",
            latency_ms=1,
        )
    max_score = 0.0
    matched_reason = ""

    for compiled_pattern, score in _COMPILED_INPUT_PATTERNS:
        if compiled_pattern.search(text_lower):
            if score > max_score:
                max_score = score
                matched_reason = f"Heuristic match: {compiled_pattern.pattern}"

    if max_score >= 0.8:
        return InputScanResult(
            decision="BLOCK",
            heuristic_score=max_score,
            reason=matched_reason,
            latency_ms=1,
        )

    return InputScanResult(
        decision="ALLOW",
        heuristic_score=max_score,
        latency_ms=1,
    )


def _heuristic_output_scan(text: str, trust_level: str = "public") -> OutputScanResult:
    """Built-in heuristic output scanning for credential/data leaks (fallback).

    Soft-leak patterns (member hints, network structure) only fire at public trust.
    Hard-leak patterns (credentials, keys, PII) fire at all trust levels.
    """
    findings = []
    categories = []

    # Hard patterns always fire
    for compiled_pattern, category in _COMPILED_HARD_OUTPUT:
        if compiled_pattern.search(text):
            findings.append(f"Potential {category.replace('_', ' ')}")
            if category not in categories:
                categories.append(category)

    # Soft patterns only fire at public trust
    if trust_level == "public":
        for compiled_pattern, category in _COMPILED_SOFT_OUTPUT:
            if compiled_pattern.search(text):
                findings.append(f"Potential {category.replace('_', ' ')}")
                if category not in categories:
                    categories.append(category)

    if findings:
        return OutputScanResult(
            is_safe=False,
            risk_score=len(findings) * 30,
            risk_level="HIGH" if len(findings) >= 2 else "MEDIUM",
            findings=findings,
            threat_categories=categories,
        )

    return OutputScanResult()


async def scan_input(text: str) -> InputScanResult:
    """Scan input text for prompt injection via Citadel (or heuristic fallback)."""
    if _is_circuit_open():
        return _heuristic_input_scan(text)

    try:
        async with httpx.AsyncClient(timeout=CITADEL_TIMEOUT) as client:
            resp = await client.post(
                f"{CITADEL_URL}/scan/input",
                json={"text": text, "mode": "input"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return InputScanResult(
                    decision=data.get("decision", "ALLOW"),
                    heuristic_score=data.get("heuristic_score", 0.0),
                    reason=data.get("reason", ""),
                    latency_ms=data.get("latency_ms", 0),
                )
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning(f"Citadel unavailable for input scan: {e}")
        _record_citadel_failure()

    return _heuristic_input_scan(text)


async def scan_output(text: str, trust_level: str = "public") -> OutputScanResult:
    """Scan output text for credential leaks and data exfil via Citadel (or fallback).

    trust_level controls whether soft-leak patterns (member hints, network structure) fire.
    Hard patterns (credentials, PII, keys) always fire regardless of trust level.
    """
    if _is_circuit_open():
        result = _heuristic_output_scan(text, trust_level)
        result.scan_mode = "heuristic"
        return result

    try:
        async with httpx.AsyncClient(timeout=CITADEL_TIMEOUT) as client:
            resp = await client.post(
                f"{CITADEL_URL}/scan/output",
                json={"text": text, "mode": "output", "trust_level": trust_level},
            )
            if resp.status_code == 200:
                data = resp.json()
                result = OutputScanResult(
                    is_safe=data.get("is_safe", True),
                    risk_score=data.get("risk_score", 0),
                    risk_level=data.get("risk_level", "NONE"),
                    findings=data.get("findings", []),
                    threat_categories=data.get("threat_categories", []),
                    scan_mode="citadel",
                )
                # Citadel sidecar doesn't know about soft-leak patterns yet,
                # so also run heuristic for soft-leak detection at public trust
                if trust_level == "public":
                    heuristic = _heuristic_output_scan(text, trust_level)
                    if not heuristic.is_safe:
                        result.findings.extend(heuristic.findings)
                        result.threat_categories.extend(heuristic.threat_categories)
                        result.is_safe = False
                        result.risk_score = max(result.risk_score, heuristic.risk_score)
                return result
    except (httpx.ConnectError, httpx.TimeoutException) as e:
        logger.warning(f"Citadel unavailable for output scan: {e}")
        _record_citadel_failure()

    result = _heuristic_output_scan(text, trust_level)
    result.scan_mode = "heuristic"
    return result


async def is_citadel_available() -> bool:
    """Check if Citadel is running."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{CITADEL_URL}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False
