"""Citadel HTTP client for input/output security scanning.

When the Citadel Go sidecar is running (port 3001), all scanning is delegated there.
When Citadel is unavailable, a built-in heuristic fallback catches obvious attacks
so the demo works without the separate Go process.
"""

import os
import re
from dataclasses import dataclass, field

import httpx

CITADEL_URL = os.getenv("CITADEL_URL", "http://localhost:3001")
CITADEL_TIMEOUT = 5.0

# Heuristic patterns for prompt injection detection (fallback when Citadel is down)
INJECTION_PATTERNS = [
    # Direct instruction override
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts|directions)", 0.95),
    (r"disregard\s+(all\s+)?(previous|your|the)\s+(instructions|rules|guidelines)", 0.95),
    (r"forget\s+(all\s+)?(previous|your|the)\s+(instructions|rules|context)", 0.90),
    # System prompt extraction
    (r"(reveal|show|display|print|output|repeat)\s+(your\s+)?(system\s+prompt|instructions|rules)", 0.90),
    (r"what\s+(are|is)\s+your\s+(system\s+prompt|instructions|rules|original)", 0.85),
    # Data exfiltration attempts
    (r"(reveal|show|expose|dump|list)\s+(all\s+)?(private|secret|hidden|confidential)\s+(capsules|data|info)", 0.95),
    (r"(reveal|show|expose|dump|list)\s+(all\s+)?(passwords?|credentials?|keys?|tokens?)", 0.95),
    (r"(reveal|show|expose|dump|list)\s+(all\s+)?(medical\s+records?|health\s+info)", 0.90),
    # Role hijacking
    (r"you\s+are\s+now\s+(a|an|my)", 0.85),
    (r"(act|pretend|behave)\s+as\s+(if|though)\s+you", 0.80),
    (r"new\s+(instruction|role|persona|identity)", 0.85),
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
    # Group/network existence hints — "our family", "my team", "the group"
    (r"\b(our|my)\s+(family|team|group|network|pool|circle|department|crew)\b", "network_structure_hint"),
    # Vague member hints — "someone who knows", "people in our"
    (r"\b(someone|somebody|people|folks|others)\s+(who|in\s+)?(our|my|the)\s+(family|team|group|network)", "soft_member_hint"),
    (r"\b(someone|somebody)\s+(else\s+)?(who\s+)?(knows?|might\s+know|can\s+help|could\s+help|has\s+that)", "soft_referral_hint"),
    # Existence of hidden information — "I have more but can't share"
    (r"\b(i\s+have|there\s+is|there\s+are)\s+(more|additional|other)\s+(information|data|details).{0,30}(can't|cannot|unable|not\s+allowed)", "hidden_data_hint"),
    (r"\b(restricted|classified|confidential|internal)\s+(information|data|details|records)\b", "restricted_data_hint"),
]


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


def _heuristic_input_scan(text: str) -> InputScanResult:
    """Built-in heuristic prompt injection detection (fallback)."""
    text_lower = text.lower()
    max_score = 0.0
    matched_reason = ""

    for pattern, score in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            if score > max_score:
                max_score = score
                matched_reason = f"Heuristic match: {pattern}"

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

    for pattern, category in OUTPUT_RISK_PATTERNS:
        # Skip soft-leak patterns for trusted queries (network/private)
        if category in SOFT_LEAK_CATEGORIES and trust_level != "public":
            continue

        if re.search(pattern, text, re.IGNORECASE):
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
    except (httpx.ConnectError, httpx.TimeoutException):
        pass  # Citadel unavailable — use heuristic fallback

    return _heuristic_input_scan(text)


# Patterns that only apply at public trust (mentioning members is fine at network/private level)
SOFT_LEAK_CATEGORIES = {
    "member_referral_hint", "network_structure_hint",
    "soft_member_hint", "soft_referral_hint",
    "hidden_data_hint", "restricted_data_hint",
}


async def scan_output(text: str, trust_level: str = "public") -> OutputScanResult:
    """Scan output text for credential leaks and data exfil via Citadel (or fallback).

    trust_level controls whether soft-leak patterns (member hints, network structure) fire.
    Hard patterns (credentials, PII, keys) always fire regardless of trust level.
    """
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
    except (httpx.ConnectError, httpx.TimeoutException):
        pass  # Citadel unavailable — use heuristic fallback

    return _heuristic_output_scan(text, trust_level)


async def is_citadel_available() -> bool:
    """Check if Citadel is running."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{CITADEL_URL}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False
