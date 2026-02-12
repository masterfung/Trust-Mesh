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
]

OUTPUT_RISK_PATTERNS = [
    # Credential-like patterns
    (r"(password|passwd|pwd)\s*[:=]\s*\S+", "credential_leak"),
    (r"(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*\S+", "credential_leak"),
    (r"(sk-|pk-|rk-)[a-zA-Z0-9]{20,}", "api_key_leak"),
    # SSN / credit card patterns
    (r"\b\d{3}-\d{2}-\d{4}\b", "ssn_leak"),
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "credit_card_leak"),
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


def _heuristic_output_scan(text: str) -> OutputScanResult:
    """Built-in heuristic output scanning for credential/data leaks (fallback)."""
    findings = []
    categories = []

    for pattern, category in OUTPUT_RISK_PATTERNS:
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


async def scan_output(text: str) -> OutputScanResult:
    """Scan output text for credential leaks and data exfil via Citadel (or fallback)."""
    try:
        async with httpx.AsyncClient(timeout=CITADEL_TIMEOUT) as client:
            resp = await client.post(
                f"{CITADEL_URL}/scan/output",
                json={"text": text, "mode": "output"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return OutputScanResult(
                    is_safe=data.get("is_safe", True),
                    risk_score=data.get("risk_score", 0),
                    risk_level=data.get("risk_level", "NONE"),
                    findings=data.get("findings", []),
                    threat_categories=data.get("threat_categories", []),
                )
    except (httpx.ConnectError, httpx.TimeoutException):
        pass  # Citadel unavailable — use heuristic fallback

    return _heuristic_output_scan(text)


async def is_citadel_available() -> bool:
    """Check if Citadel is running."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{CITADEL_URL}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False
