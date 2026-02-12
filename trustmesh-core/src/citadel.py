"""Citadel HTTP client for input/output security scanning."""

import os
from dataclasses import dataclass, field

import httpx

CITADEL_URL = os.getenv("CITADEL_URL", "http://localhost:3001")
CITADEL_TIMEOUT = 5.0


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


async def scan_input(text: str) -> InputScanResult:
    """Scan input text for prompt injection via Citadel."""
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
        pass  # Citadel unavailable — fail open for hackathon
    return InputScanResult()


async def scan_output(text: str) -> OutputScanResult:
    """Scan output text for credential leaks and data exfil via Citadel."""
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
        pass  # Citadel unavailable — fail open for hackathon
    return OutputScanResult()


async def is_citadel_available() -> bool:
    """Check if Citadel is running."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{CITADEL_URL}/health")
            return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False
