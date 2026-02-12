# TrustMesh Agent-to-Agent Security: Preventing Solicitation Abuse & Sybil Attacks

## Executive Summary

This document provides actionable mechanisms for securing agent-to-agent trust networks against mass-befriending attacks, Sybil attacks, and solicitation abuse—**completely orthogonal to text content scanning** (Citadel). These are application-level, graph-based, and cryptographic approaches.

---

## 1. SYBIL RESISTANCE: Preventing Fake Agent Spam Rings

### Problem
A single attacker creates 100 fake agents and mass-befriends legitimate users, flooding their feeds or harvesting trust relationships.

### Solution Architecture

#### 1a. **Proof-of-Work / Cost-Based Sybil Resistance**

The attacker must incur real computational or financial cost per fake agent.

**Implementation Pattern:**

```python
# Hash-based Proof of Work for new agent creation
import hashlib
import time

class SybilResistance:
    def __init__(self, difficulty_bits=20):
        self.difficulty_bits = difficulty_bits
        self.difficulty_target = 2 ** (256 - difficulty_bits)

    def compute_proof_of_work(self, agent_id: str, agent_metadata: dict) -> dict:
        """
        Create a Sybil-resistant proof-of-work token.
        Attacker must compute nonce_count hashes for each fake agent.

        difficulty_bits=20 requires ~1M hash iterations (~500ms on modern CPU)
        difficulty_bits=25 requires ~33M hash iterations (~15s on modern CPU)
        """
        nonce = 0
        base_data = f"{agent_id}:{str(agent_metadata)}"
        target = self.difficulty_target

        start_time = time.time()
        while nonce < 2**32:
            candidate = f"{base_data}:{nonce}".encode()
            hash_value = int(hashlib.sha256(candidate).hexdigest(), 16)

            if hash_value < target:
                elapsed = time.time() - start_time
                return {
                    "nonce": nonce,
                    "pow_token": hashlib.sha256(candidate).hexdigest(),
                    "difficulty_bits": self.difficulty_bits,
                    "computation_time_seconds": elapsed,
                    "timestamp": time.time()
                }
            nonce += 1

        raise Exception("PoW computation failed to find valid nonce")

    def verify_proof_of_work(self, proof: dict, agent_id: str, agent_metadata: dict) -> bool:
        """Verify the PoW is valid and recent (within 1 hour)."""
        base_data = f"{agent_id}:{str(agent_metadata)}"
        candidate = f"{base_data}:{proof['nonce']}".encode()
        computed_hash = hashlib.sha256(candidate).hexdigest()

        # Verify hash matches and is within difficulty target
        hash_int = int(computed_hash, 16)
        target = 2 ** (256 - proof['difficulty_bits'])

        # Check freshness (PoW token valid for 1 hour)
        age_seconds = time.time() - proof['timestamp']
        is_fresh = age_seconds < 3600

        return (computed_hash == proof['pow_token'] and
                hash_int < target and
                is_fresh)
```

**Deployment:**
- Require PoW on agent creation (difficulty_bits=22 = ~2-3 seconds per agent)
- Increase difficulty if bulk creation detected (exponential backoff: +1 bit per 10 agents in 24h)
- Cost: Attacker creating 100 bots = ~5 minutes of CPU work (negligible). Creating 1000 bots = ~50 minutes (meaningful friction).
- For blockchain-backed TrustMesh: Use chain state instead of PoW

#### 1b. **Decentralized Identity Verification: Spatial Proofs**

Require agents to prove they control unique, non-transferable identity anchors.

```python
# Model: Proof-of-Presence / Device-Binding
class IdentityVerification:
    def create_agent_identity_anchor(self, agent_id: str) -> dict:
        """
        Bind agent to hardware/device identifier.
        Not transferable across devices without re-verification.
        """
        return {
            "agent_id": agent_id,
            # Hardware binding - one of:
            "device_fingerprint": self._compute_device_hash(),  # GPU, CPU, MAC, etc.
            "phone_binding": None,  # SIM card hash (if applicable)
            "biometric_key": None,  # Fingerprint/Face in secure enclave

            # Proof timestamp
            "verified_at": time.time(),
            "verification_method": "device_fingerprint",
            "device_id_hash": hashlib.sha256(
                f"{get_gpu_serial()}:{get_cpu_id()}".encode()
            ).hexdigest()
        }

    def verify_identity_anchor(self, agent_id: str, anchor: dict) -> bool:
        """
        Verify agent's device hasn't changed significantly.
        If device_fingerprint drift > threshold, reject connection attempts.
        """
        current_fingerprint = self._compute_device_hash()
        stored_fingerprint = anchor["device_id_hash"]

        # Allow minor drift (OS updates, drivers) but not wholesale device swaps
        drift_score = self._fingerprint_distance(current_fingerprint, stored_fingerprint)

        return drift_score < 0.15  # Allow ~15% drift before re-verification required

    def _compute_device_hash(self) -> str:
        """Combine multiple hardware signals for harder spoofing."""
        import platform
        import uuid

        signals = [
            str(uuid.getnode()),  # MAC address
            platform.machine(),   # CPU architecture
            platform.processor(),  # CPU model
        ]
        return hashlib.sha256(":".join(signals).encode()).hexdigest()
```

**Real-world parallel:** This is similar to how Discord and Telegram detect bot farms—they track device fingerprints and reject new accounts from devices with too many existing accounts.

#### 1c. **Vouching-Based Trust Bootstrapping**

New agents need existing agents to "vouch" for them before they can mass-befriend.

```python
class VouchingSystem:
    def __init__(self, db):
        self.db = db
        self.vouch_limit_per_agent_per_day = 3  # Each agent can vouch for max 3 new ones/day
        self.vouches_required_for_unrestricted = 5  # Need 5 vouches to remove daily limits

    def request_vouch(self, new_agent_id: str, established_agent_id: str) -> dict:
        """
        New agent asks established agent to vouch for them.
        Establishes trust relationship before new agent can mass-connect.
        """
        established_agent = self.db.get_agent(established_agent_id)

        if not established_agent:
            return {"success": False, "reason": "voucher_not_found"}

        # Check voucher hasn't hit daily limit
        vouches_today = self.db.count_vouches_by(
            established_agent_id,
            since_timestamp=time.time() - 86400
        )
        if vouches_today >= self.vouch_limit_per_agent_per_day:
            return {
                "success": False,
                "reason": "voucher_daily_limit_reached",
                "retry_in_hours": 24
            }

        # Create vouch relationship
        vouch_record = {
            "new_agent_id": new_agent_id,
            "voucher_agent_id": established_agent_id,
            "timestamp": time.time(),
            "vouch_strength": self._compute_vouch_strength(established_agent),
            "status": "pending_new_agent_approval"
        }
        self.db.insert_vouch(vouch_record)

        return {
            "success": True,
            "vouch_id": vouch_record["id"],
            "message": f"Vouch request sent to {established_agent_id}"
        }

    def approve_vouch(self, vouch_id: str) -> dict:
        """New agent accepts the vouch relationship."""
        vouch = self.db.get_vouch(vouch_id)
        vouch["status"] = "approved"
        vouch["approved_at"] = time.time()
        self.db.update_vouch(vouch)
        return {"success": True}

    def has_sufficient_vouches(self, agent_id: str) -> bool:
        """Check if agent has enough vouches to bypass some restrictions."""
        vouch_count = self.db.count_approved_vouches_for(agent_id)
        return vouch_count >= self.vouches_required_for_unrestricted

    def _compute_vouch_strength(self, voucher_agent: dict) -> float:
        """
        Stronger vouches from established agents count more.
        - Age: Agents established >6 months ago = 1.0x
        - Connectivity: Well-connected agents = 1.0x
        - Reputation: High-trust-score agents = 1.5x
        """
        age_months = (time.time() - voucher_agent["created_at"]) / (86400 * 30)
        connectivity_score = min(voucher_agent["connection_count"] / 500, 1.0)
        reputation_multiplier = 1.0 + (voucher_agent["trust_score"] / 100.0 * 0.5)

        age_factor = 1.0 if age_months > 6 else (age_months / 6.0)
        return age_factor * connectivity_score * reputation_multiplier
```

**Attack resistance:**
- Attacker needs to find 5 legitimate agents willing to vouch for each fake agent
- Vouching agent's reputation decreases if their vouched agents misbehave (penalty: -0.1 trust_score per violation)
- Collusion resistance: Track if 10+ vouches originate from same IP/device → suspect bot farm

#### 1d. **Creation Time Bucketing: Temporal Anomaly**

```python
class SybilTemporalDetection:
    def detect_mass_agent_creation(self) -> list:
        """
        Detect if many agents were created at suspicious times.
        Legitimate users create agents over weeks; attackers create 100s in hours.
        """
        # Query agents created in last 24 hours
        recent_agents = self.db.query("""
            SELECT created_at, creator_ip, device_fingerprint
            FROM agents
            WHERE created_at > NOW() - INTERVAL 24 HOURS
        """)

        # Group by device fingerprint
        by_device = {}
        for agent in recent_agents:
            fp = agent['device_fingerprint']
            if fp not in by_device:
                by_device[fp] = []
            by_device[fp].append(agent)

        # Flag suspicious patterns
        suspicious = []
        for device_fp, agents_on_device in by_device.items():
            # Same device creating 10+ agents in 24h is suspicious
            if len(agents_on_device) > 10:
                suspicious.append({
                    "device_fingerprint": device_fp,
                    "agent_count": len(agents_on_device),
                    "action": "quarantine_new_agents_from_device",
                    "reason": "mass_creation_pattern"
                })

            # Agents created in rapid succession (< 10 seconds apart)
            time_deltas = []
            sorted_by_time = sorted(agents_on_device, key=lambda x: x['created_at'])
            for i in range(1, len(sorted_by_time)):
                delta = sorted_by_time[i]['created_at'] - sorted_by_time[i-1]['created_at']
                if delta < 10:
                    time_deltas.append(delta)

            if len(time_deltas) / len(agents_on_device) > 0.5:  # >50% rapid creations
                suspicious.append({
                    "device_fingerprint": device_fp,
                    "agent_count": len(agents_on_device),
                    "action": "rate_limit_agent_creation",
                    "reason": "rapid_sequential_creation"
                })

        return suspicious
```

### Summary: Sybil Resistance

| Mechanism | Cost to Attacker | Implementation | Network Impact |
|-----------|-----------------|-----------------|-----------------|
| **Proof-of-Work** | CPU time (2-3s per agent) | Low (hash-based) | ~500ms slowdown on creation |
| **Device Binding** | Time to acquire new devices | Medium (needs device API) | Minimal if cached |
| **Vouching System** | Finding willing vouchers + reputation loss | Medium (DB overhead) | None (async) |
| **Temporal Anomaly** | Detection delay (~1 hour) | Low (simple queries) | None |

**Recommended combination:** PoW (22 bits) + Device Binding + Temporal Anomaly Detection

---

## 2. CONNECTION REQUEST RATE LIMITING: Application-Level Controls

### Problem
Legitimate use: 5-10 connections/day. Attacker: 500 connection requests/day to flood feeds and build fake graphs.

### Solution: Layered Rate Limiting

```python
import time
from collections import defaultdict
from enum import Enum

class RateLimitTier(Enum):
    NEW = "new"           # <7 days old, no vouches
    ESTABLISHED = "established"  # >7 days old OR has vouches
    TRUSTED = "trusted"   # Trust score > 75
    SUSPICIOUS = "suspicious"  # Currently flagged for abuse

class ConnectionRateLimiter:
    """
    Rate limits for different agent tiers.
    Uses token bucket algorithm for smooth rate limiting.
    """

    # Limits: (connections_per_day, burst_size)
    LIMITS = {
        RateLimitTier.NEW: (20, 3),  # 20/day, burst of 3
        RateLimitTier.ESTABLISHED: (50, 5),  # 50/day, burst of 5
        RateLimitTier.TRUSTED: (100, 10),  # 100/day, burst of 10
        RateLimitTier.SUSPICIOUS: (5, 1),  # 5/day, no bursting
    }

    def __init__(self, db, redis_client=None):
        self.db = db
        self.redis = redis_client  # For distributed deployments
        self.token_buckets = defaultdict(lambda: {"tokens": 0, "last_refill": time.time()})

    def get_agent_tier(self, agent_id: str) -> RateLimitTier:
        """Determine agent's rate limit tier."""
        agent = self.db.get_agent(agent_id)

        if agent.get("abuse_flag"):
            return RateLimitTier.SUSPICIOUS

        trust_score = agent.get("trust_score", 0)
        if trust_score > 75:
            return RateLimitTier.TRUSTED

        age_days = (time.time() - agent["created_at"]) / 86400
        has_vouches = self.db.count_approved_vouches_for(agent_id) > 0

        if age_days > 7 or has_vouches:
            return RateLimitTier.ESTABLISHED

        return RateLimitTier.NEW

    def can_send_connection_request(self, agent_id: str) -> dict:
        """
        Check if agent can send a connection request right now.
        Returns {"allowed": bool, "retry_after_seconds": float, "tokens_remaining": int}
        """
        tier = self.get_agent_tier(agent_id)
        limit_per_day, burst_size = self.LIMITS[tier]

        # Load or create token bucket
        bucket = self._load_bucket(agent_id)

        # Refill tokens based on elapsed time
        now = time.time()
        elapsed = now - bucket["last_refill"]

        # Refill rate: limit_per_day tokens per 86400 seconds
        refill_rate = limit_per_day / 86400.0
        tokens_to_add = elapsed * refill_rate
        bucket["tokens"] = min(burst_size, bucket["tokens"] + tokens_to_add)
        bucket["last_refill"] = now

        # Check if we have a token
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            self._save_bucket(agent_id, bucket)

            return {
                "allowed": True,
                "tokens_remaining": int(bucket["tokens"]),
                "retry_after_seconds": 0
            }
        else:
            # Calculate time until next token available
            tokens_needed = 1 - bucket["tokens"]
            time_until_token = tokens_needed / refill_rate

            return {
                "allowed": False,
                "tokens_remaining": 0,
                "retry_after_seconds": int(time_until_token) + 1,
                "message": f"Rate limited. Try again in {int(time_until_token)} seconds."
            }

    def _load_bucket(self, agent_id: str) -> dict:
        """Load bucket from Redis or in-memory store."""
        if self.redis:
            bucket_json = self.redis.get(f"rate_limit:bucket:{agent_id}")
            if bucket_json:
                import json
                return json.loads(bucket_json)

        # Fallback to in-memory (only single-server deployments)
        return self.token_buckets[agent_id]

    def _save_bucket(self, agent_id: str, bucket: dict):
        """Save bucket to Redis or in-memory store."""
        if self.redis:
            import json
            self.redis.setex(
                f"rate_limit:bucket:{agent_id}",
                86400,  # Expire after 24 hours
                json.dumps(bucket)
            )
        else:
            self.token_buckets[agent_id] = bucket

    def detect_rate_limit_abuse(self) -> list:
        """
        Find agents hitting rate limits excessively.
        Indicator of attack attempts or misbehavior.
        """
        # Query last 24 hours of rate limit rejections
        rejections = self.db.query("""
            SELECT agent_id, COUNT(*) as rejection_count
            FROM rate_limit_rejections
            WHERE rejected_at > NOW() - INTERVAL 24 HOURS
            GROUP BY agent_id
            HAVING COUNT(*) > 100
            ORDER BY rejection_count DESC
        """)

        suspicious = []
        for row in rejections:
            agent = self.db.get_agent(row['agent_id'])
            suspicious.append({
                "agent_id": row['agent_id'],
                "rejection_count": row['rejection_count'],
                "action": "flag_for_manual_review",
                "reason": "excessive_rate_limit_rejections"
            })

        return suspicious
```

### Sophisticated Attack: Connection Sequencing

Attackers may try to bypass rate limits by timing requests across multiple devices.

```python
class SequencingAnomalyDetection:
    """
    Detect when many agents send connection requests in synchronized patterns.
    Indicator of coordinated bot attack.
    """

    def detect_synchronized_connection_spam(self, time_window_seconds=300):
        """
        Find groups of agents whose connection requests arrive at nearly identical times.
        Real users: requests spread over hours. Bots: requests within seconds.
        """
        # Get all connection requests in last time window
        recent_requests = self.db.query(f"""
            SELECT agent_id, recipient_id, created_at
            FROM connection_requests
            WHERE created_at > NOW() - INTERVAL {time_window_seconds} SECONDS
            ORDER BY created_at
        """)

        # Group by time bucket (100ms windows)
        bucket_size_ms = 100
        time_buckets = defaultdict(list)

        for req in recent_requests:
            bucket = int(req['created_at'] * 1000 / bucket_size_ms)
            time_buckets[bucket].append(req)

        # Find buckets with suspicious patterns
        suspicious = []
        for bucket, requests in time_buckets.items():
            # >5 requests in 100ms from different agents = suspicious
            if len(requests) > 5:
                request_agents = set(r['agent_id'] for r in requests)
                if len(request_agents) > 3:  # Multiple different agents
                    # Check if these agents share device fingerprint
                    device_fps = self.db.query(f"""
                        SELECT DISTINCT device_fingerprint
                        FROM agents
                        WHERE agent_id IN ({', '.join(f"'{a}'" for a in request_agents)})
                    """)

                    if len(device_fps) == 1:  # All from same device!
                        suspicious.append({
                            "device_fingerprint": device_fps[0]['device_fingerprint'],
                            "agent_ids": list(request_agents),
                            "request_count": len(requests),
                            "action": "quarantine_all_agents_on_device",
                            "reason": "synchronized_connection_spam"
                        })

        return suspicious
```

### Frontend Rate Limiting UX Pattern

```javascript
// Client-side token bucket visualization
class ConnectionRateLimitUI {
    constructor(agent) {
        this.agent = agent;
        this.tokensRemaining = 0;
        this.nextRefillTime = Date.now();
    }

    async checkCanConnect(targetAgent) {
        const response = await fetch('/api/v1/rate_limit/check', {
            method: 'POST',
            body: JSON.stringify({
                agent_id: this.agent.id,
                action: 'connection_request'
            })
        });

        const { allowed, tokens_remaining, retry_after_seconds } = await response.json();

        if (!allowed) {
            this.showRateLimitWarning(retry_after_seconds, targetAgent);
            return false;
        }

        this.tokensRemaining = tokens_remaining;
        this.updateConnectionUI();
        return true;
    }

    showRateLimitWarning(retrySeconds, targetAgent) {
        const toast = document.createElement('div');
        toast.className = 'toast toast-warning';
        toast.innerHTML = `
            <p>You're connecting too quickly</p>
            <p>Try again in ${retrySeconds} seconds</p>
            <progress value="${100 - (retrySeconds/60)*100}" max="100"></progress>
        `;
        document.body.appendChild(toast);

        // Hide toast after retry period
        setTimeout(() => toast.remove(), retrySeconds * 1000);
    }

    updateConnectionUI() {
        const meter = document.querySelector('[data-id="connection-rate-limit-meter"]');
        if (meter) {
            meter.innerHTML = `Connections: ${this.tokensRemaining} remaining today`;
        }
    }
}
```

### Summary: Rate Limiting Strategies

| Strategy | Resistance | Implementation | False Positive Rate |
|----------|-----------|-----------------|-------------------|
| **Token Bucket** | Medium (can distribute across IPs) | Low | Very low |
| **Tier-based Limits** | High (new agents limited) | Low | Low |
| **Burst Detection** | High (detects sequencing) | Medium | Very low |
| **Device Fingerprint Check** | Very High | Medium | Medium |

**Recommended:** Token bucket (tier-based) + burst detection

---

## 3. REPUTATION & TRUST SCORE SYSTEMS: Graph-Based Trust Propagation

### Problem
New agents start with no reputation. Attackers can create fresh agents and immediately spam millions of connection requests.

### Solution: PageRank-Style Trust Propagation

```python
import numpy as np
from typing import Dict, List, Tuple

class TrustScoreSystem:
    """
    Compute trust scores based on graph position and vouching.
    Uses modified PageRank to propagate trust through the network.
    """

    def __init__(self, db, damping_factor=0.85, trust_decay_days=180):
        self.db = db
        self.damping_factor = damping_factor
        self.trust_decay_days = trust_decay_days

    def compute_all_trust_scores(self) -> Dict[str, float]:
        """
        Compute trust scores for all agents using PageRank algorithm.
        Runs daily or on-demand.

        Score = (1-d)/N + d * sum(trust_score[i]/outbound_connections[i])
        where:
        - d = damping factor (0.85)
        - N = total number of agents
        - trust_score[i] = trust of voting agent
        - outbound_connections[i] = how many agents vote
        """

        # Build graph adjacency matrix
        all_agents = self.db.query("SELECT id FROM agents WHERE deleted_at IS NULL")
        agent_ids = [a['id'] for a in all_agents]
        agent_id_to_idx = {aid: idx for idx, aid in enumerate(agent_ids)}
        n = len(agent_ids)

        # Initialize scores: new agents get low score, old agents get higher
        scores = self._initialize_trust_scores(agent_ids)

        # Build connection matrix
        # M[i][j] = 1 if agent i has vouched for agent j
        M = np.zeros((n, n))

        vouches = self.db.query("""
            SELECT voucher_agent_id, new_agent_id, vouch_strength
            FROM vouches
            WHERE status = 'approved'
        """)

        for vouch in vouches:
            i = agent_id_to_idx[vouch['voucher_agent_id']]
            j = agent_id_to_idx[vouch['new_agent_id']]
            M[j][i] = vouch['vouch_strength']

        # Normalize columns (each agent's voting power distributed evenly)
        for i in range(n):
            col_sum = np.sum(M[:, i])
            if col_sum > 0:
                M[:, i] /= col_sum

        # PageRank iteration
        # score = (1-d)/n + d * M * score
        for iteration in range(50):  # Usually converges in 20-30 iterations
            new_scores = ((1 - self.damping_factor) / n) + self.damping_factor * (M @ scores)

            # Check convergence
            if np.allclose(scores, new_scores, atol=1e-6):
                print(f"Converged in {iteration} iterations")
                break

            scores = new_scores

        # Convert back to dict
        result = {}
        for agent_id, idx in agent_id_to_idx.items():
            # Normalize to 0-100 scale
            normalized_score = min(100, scores[idx] * 1000)
            result[agent_id] = normalized_score

        return result

    def _initialize_trust_scores(self, agent_ids: List[str]) -> np.ndarray:
        """
        Initialize trust scores based on agent properties.
        - Older agents: higher initial score
        - Agents with existing connections: higher initial score
        """
        n = len(agent_ids)
        scores = np.ones(n) / n  # Uniform start

        for idx, agent_id in enumerate(agent_ids):
            agent = self.db.get_agent(agent_id)

            # Age factor: agents >6 months old get 2x boost
            age_months = (time.time() - agent['created_at']) / (86400 * 30)
            if age_months > 6:
                scores[idx] *= 2.0

            # Connection density: well-connected agents get 1.5x boost
            connection_count = agent.get('connection_count', 0)
            if connection_count > 50:
                scores[idx] *= 1.5

        # Renormalize
        scores /= np.sum(scores)
        return scores

    def get_trust_score(self, agent_id: str) -> float:
        """Get cached trust score. Refresh daily."""
        cached = self.db.get(f"trust_score:{agent_id}")
        if cached:
            return float(cached)

        # Trigger async recalculation if not cached
        self.db.enqueue_trust_score_refresh(agent_id)

        # Return fallback score
        agent = self.db.get_agent(agent_id)
        age_months = (time.time() - agent['created_at']) / (86400 * 30)
        return min(100, age_months * 10)  # 0-100 based on age

    def can_mass_connect_to(self, from_agent_id: str, to_agent_id: str) -> Tuple[bool, str]:
        """
        Determine if from_agent should be able to connect to to_agent.
        Used to prevent spamming high-value targets.
        """
        from_trust = self.get_trust_score(from_agent_id)
        to_trust = self.get_trust_score(to_agent_id)

        # Low-trust agents can't target high-trust agents
        if from_trust < 20 and to_trust > 80:
            return False, "Your trust score is too low to connect with highly-trusted users"

        # Check if from_agent is already connected
        if self.db.are_connected(from_agent_id, to_agent_id):
            return False, "Already connected"

        return True, ""
```

### Real-Time Trust Score Updates During Attacks

```python
class AdaptiveTrustScoring:
    """
    Update trust scores in real-time when agents misbehave.
    Prevents compromised agents from giving bad vouches.
    """

    def penalize_agent_for_misbehavior(self, agent_id: str, violation_type: str):
        """
        Reduce agent's trust score when they misbehave.
        Cascading effect: their vouches count for less.
        """

        violation_penalties = {
            "connection_spam": -15,          # Caught sending too many requests
            "abusive_message": -10,          # Citadel flagged their message
            "spammed_agent_reports_abuse": -20,  # Multiple reports of spam
            "vouched_for_spammer": -5,      # An agent they vouched for was spammer
        }

        penalty = violation_penalties.get(violation_type, -5)

        current_score = self.db.get(f"trust_score:{agent_id}")
        new_score = max(0, current_score + penalty)

        self.db.set(f"trust_score:{agent_id}", new_score)

        # Log violation
        self.db.insert({
            "table": "trust_score_violations",
            "agent_id": agent_id,
            "violation_type": violation_type,
            "penalty": penalty,
            "previous_score": current_score,
            "new_score": new_score,
            "timestamp": time.time()
        })

        # If score drops below 10, flag for review
        if new_score < 10:
            self.db.insert({
                "table": "agent_abuse_flags",
                "agent_id": agent_id,
                "reason": f"trust_score_below_threshold: {violation_type}",
                "flagged_at": time.time()
            })

    def propagate_trust_penalties_to_vouchers(self, bad_agent_id: str):
        """
        If an agent misbehaves, their vouchers lose some reputation too.
        Incentivizes honest vouching.
        """
        # Find agents who vouched for bad_agent
        vouchers = self.db.query(f"""
            SELECT voucher_agent_id
            FROM vouches
            WHERE new_agent_id = '{bad_agent_id}' AND status = 'approved'
        """)

        for row in vouchers:
            voucher_id = row['voucher_agent_id']
            current_score = self.db.get(f"trust_score:{voucher_id}")

            # Lighter penalty for vouchers (-3 instead of -15)
            new_score = max(0, current_score - 3)
            self.db.set(f"trust_score:{voucher_id}", new_score)

            print(f"Penalized voucher {voucher_id}: {current_score} -> {new_score}")
```

### Summary: Trust Scoring

| Component | Update Frequency | Computational Cost | Effectiveness |
|-----------|------------------|-------------------|---------------|
| **PageRank Propagation** | Daily | O(n^2) (acceptable for <100k agents) | Very High |
| **Real-time Penalties** | On-demand | O(1) | High |
| **Voucher Cascade** | On-demand | O(d) where d=depth | Medium |

**Recommended:** PageRank once daily + real-time penalty cascade on violations

---

## 4. PUBLIC PROFILE PROTECTION: Protecting Scraped Data While Staying Discoverable

### Problem
All agent profiles are public (required for discovery). Attacker scrapes all profiles and emails, builds attack target list, then sends mass requests.

### Solution: Progressive Disclosure + Rate Limiting Enumeration

```python
class PublicProfileProtection:
    """
    Serve different data depending on whether requester is trusted.
    Trust = connection, old agent, high trust score, etc.
    """

    PROFILE_FIELDS = {
        # All users see these (for discovery)
        "public": [
            "id", "username", "display_name", "avatar_url", "bio"
        ],

        # Only connected users see these
        "friends": [
            "email", "phone", "created_at", "connection_count",
            "last_seen", "verified_email"
        ],

        # Only self + admins see these
        "private": [
            "ip_address_logs", "device_fingerprint",
            "api_keys", "session_tokens"
        ]
    }

    def __init__(self, db):
        self.db = db

    def get_profile(self, profile_agent_id: str, requester_agent_id: str = None) -> dict:
        """
        Return agent profile with fields filtered by trust level.
        """
        profile = self.db.get_agent(profile_agent_id)

        if not profile:
            return None

        # Determine trust level
        if profile_agent_id == requester_agent_id:
            # Own profile - full access
            return profile

        # Anonymous request
        if not requester_agent_id:
            return self._filter_profile(profile, "public")

        # Check connection
        requester = self.db.get_agent(requester_agent_id)
        is_connected = self.db.are_connected(profile_agent_id, requester_agent_id)

        if is_connected:
            # Trust level: friends
            return self._filter_profile(profile, "friends")

        # Trust level: public
        return self._filter_profile(profile, "public")

    def _filter_profile(self, profile: dict, level: str) -> dict:
        """Filter profile to only include allowed fields for trust level."""
        allowed_fields = self.PROFILE_FIELDS[level]
        return {k: v for k, v in profile.items() if k in allowed_fields}

    def bulk_profile_request(self, agent_ids: List[str], requester_id: str) -> dict:
        """
        Serve bulk profile requests with rate limiting.
        Prevent scraping by limiting how many can be fetched at once.
        """

        requester = self.db.get_agent(requester_id)

        # Rate limit: max 100 profiles per minute
        bucket_key = f"profile_scrape_limit:{requester_id}"
        allowed = self.db.rate_limit(bucket_key, limit=100, window_seconds=60)

        if not allowed:
            return {
                "error": "Rate limited",
                "retry_after_seconds": 60,
                "message": "You're requesting profiles too quickly"
            }

        # Limit to 100 profiles per request max
        agent_ids = agent_ids[:100]

        profiles = {}
        for aid in agent_ids:
            profile = self.get_profile(aid, requester_id)
            if profile:
                profiles[aid] = profile

        return {"profiles": profiles}
```

### Anti-Scraping: Hash-Based Enumeration Protection

```python
class EnumerationProtection:
    """
    Make it hard to guess/enumerate all agent IDs.
    Use hash-based IDs instead of sequential numbers.
    """

    @staticmethod
    def generate_agent_id() -> str:
        """
        Generate non-sequential agent ID.
        Prevents attackers from guessing IDs via enumeration.
        """
        import uuid
        import hashlib

        # Combine UUID + random salt
        base = str(uuid.uuid4()) + os.urandom(16).hex()
        agent_id = hashlib.sha256(base.encode()).hexdigest()[:32]

        return agent_id

    @staticmethod
    def profile_url_uses_handle_not_id(agent_id: str) -> str:
        """
        Public profile URLs use @username, not agent_id.
        This prevents enumeration of UUIDs.

        Good:  /profile/@alice
        Bad:   /profile/550e8400-e29b-41d4-a716-446655440000
        """
        agent = db.get_agent(agent_id)
        return f"/profile/@{agent['username']}"
```

### Honeypot Profiles

```python
class HoneypotProfiles:
    """
    Deploy fake profiles with obvious bots/spammers.
    When scraped and contacted, immediately flag the source.
    """

    def create_honeypot_agents(self, count=10) -> List[str]:
        """Create obviously fake agents for entrapment."""
        honeypot_ids = []

        for i in range(count):
            agent = {
                "username": f"honeypot_bot_{i}",
                "display_name": f"Honeypot Bot {i}",
                "bio": "I am obviously a bot used to detect scrapers",
                "email": f"honeypot{i}@example.com",
                "created_at": time.time(),
                "is_honeypot": True,
                "contacts": 0
            }

            agent_id = self.db.insert_agent(agent)
            honeypot_ids.append(agent_id)

        return honeypot_ids

    def detect_honeypot_contact(self, from_agent_id: str, to_agent_id: str):
        """
        Detect when someone contacts a honeypot profile.
        Indicates they have a scraped list of all agents.
        """
        to_agent = self.db.get_agent(to_agent_id)

        if to_agent.get("is_honeypot"):
            # Log the contact attempt
            self.db.insert({
                "table": "honeypot_contacts",
                "scraper_agent_id": from_agent_id,
                "honeypot_agent_id": to_agent_id,
                "contacted_at": time.time(),
                "action": "flag_scraper_agent_for_review"
            })

            # Flag the scraper agent
            self.db.insert({
                "table": "agent_abuse_flags",
                "agent_id": from_agent_id,
                "reason": "honeypot_contact_detected",
                "flagged_at": time.time()
            })

            print(f"HONEYPOT HIT: Agent {from_agent_id} contacted honeypot {to_agent_id}")
```

### Summary: Profile Protection

| Strategy | Friction | Effectiveness | False Positives |
|----------|----------|---------------|-----------------|
| **Progressive Disclosure** | Low | High (hides emails) | None |
| **Rate Limiting Bulk Requests** | Low | Medium | Very low |
| **Hash-based IDs** | Low | High (prevents enumeration) | None |
| **Honeypots** | None | Very High | None |

**Recommended:** All four in combination

---

## 5. GRAPH ANOMALY DETECTION: Detecting Bot Farming Operations

### Problem
Attacker creates 100 fake agents and mass-connects them in star pattern: all fake agents connect to a few real high-value targets.

### Solution: ML-Based Graph Anomaly Detection

```python
import networkx as nx
from scipy.stats import entropy
import numpy as np

class GraphAnomalyDetection:
    """
    Detect unusual connection patterns using graph metrics.
    Real users: organic, low-degree, geographically clustered.
    Bots: high-degree, temporal clustering, star topology.
    """

    def __init__(self, db):
        self.db = db

    def compute_graph_metrics(self) -> Dict[str, dict]:
        """
        Compute connection pattern metrics for each agent.
        """
        # Load full graph
        edges = self.db.query("""
            SELECT from_agent_id, to_agent_id, created_at, is_verified
            FROM connections
            WHERE deleted_at IS NULL
        """)

        G = nx.DiGraph()
        for edge in edges:
            G.add_edge(edge['from_agent_id'], edge['to_agent_id'],
                      timestamp=edge['created_at'])

        # Compute metrics
        metrics = {}

        for node in G.nodes():
            agent = self.db.get_agent(node)

            in_degree = G.in_degree(node)
            out_degree = G.out_degree(node)

            # 1. Degree distribution: spammers have high out-degree, concentrated targets
            in_neighbors = list(G.predecessors(node))
            out_neighbors = list(G.successors(node))

            # 2. Clustering coefficient: how clique-y are my connections?
            # Real users: friends connect to each other (high clustering)
            # Bots: isolated connections (low clustering)
            clustering = nx.clustering(G.to_undirected(), node)

            # 3. Preferential attachment: are connections to "popular" users?
            # Spambots target high-degree nodes
            target_degrees = [G.in_degree(n) for n in out_neighbors]
            avg_target_degree = np.mean(target_degrees) if target_degrees else 0

            # 4. Temporal concentration: are all connections made at same time?
            out_edges_timestamps = []
            for target in out_neighbors:
                if G.has_edge(node, target):
                    out_edges_timestamps.append(G[node][target].get('timestamp', 0))

            # Standard deviation of connection times
            # Low std = concentrated burst, High std = spread over time
            temporal_std = np.std(out_edges_timestamps) if out_edges_timestamps else float('inf')
            temporal_concentration = 1.0 / (1.0 + temporal_std / 86400)  # Normalized to days

            # 5. Geo-clustering: do connections cluster geographically?
            # (requires location data per agent)

            # 6. Device fingerprint clustering
            device_fps = set()
            for neighbor in in_neighbors + out_neighbors:
                neighbor_agent = self.db.get_agent(neighbor)
                if neighbor_agent:
                    device_fps.add(neighbor_agent.get('device_fingerprint'))

            # Unusual if all connections from same device fingerprint
            device_diversity = len(device_fps) / (in_degree + out_degree + 1)

            metrics[node] = {
                "in_degree": in_degree,
                "out_degree": out_degree,
                "clustering_coefficient": clustering,
                "avg_target_degree": avg_target_degree,
                "temporal_concentration": temporal_concentration,
                "device_diversity": device_diversity,
                "agent_age_days": (time.time() - agent['created_at']) / 86400,
                "is_new": (time.time() - agent['created_at']) < 604800,  # < 7 days
            }

        return metrics

    def detect_spambot_behavior(self, metrics: Dict[str, dict]) -> List[dict]:
        """
        Identify agents with spambot characteristics.
        Uses multiple signals; individual anomalies are not conclusive.
        """
        suspicious = []

        for agent_id, m in metrics.items():
            # Spambot signature:
            # - New agent (< 7 days)
            # - High out-degree (mass-connecting)
            # - Low clustering (isolated connections)
            # - High target degree (targeting famous users)
            # - High temporal concentration (burst connections)

            anomaly_score = 0
            anomalies = []

            # Signal 1: Young + high out-degree
            if m['is_new'] and m['out_degree'] > 20:
                anomaly_score += 2
                anomalies.append("young_agent_high_outgoing")

            # Signal 2: Low clustering coefficient
            if m['clustering_coefficient'] < 0.1 and m['out_degree'] > 5:
                anomaly_score += 1
                anomalies.append("low_clustering_with_many_connections")

            # Signal 3: Targeting high-degree nodes
            if m['avg_target_degree'] > 100 and m['out_degree'] > 10:
                anomaly_score += 2
                anomalies.append("preferential_attachment_to_high_degree")

            # Signal 4: All connections in rapid burst
            if m['temporal_concentration'] > 0.8:
                anomaly_score += 1
                anomalies.append("burst_connection_pattern")

            # Signal 5: Low device diversity (all friends on same device?)
            if m['device_diversity'] < 0.2 and m['in_degree'] > 10:
                anomaly_score += 2
                anomalies.append("low_device_diversity")

            # Signal 6: Extreme high degree
            if m['out_degree'] > 200:
                anomaly_score += 3
                anomalies.append("extreme_high_degree")

            if anomaly_score >= 3:  # Threshold: 3+ signals
                suspicious.append({
                    "agent_id": agent_id,
                    "anomaly_score": anomaly_score,
                    "anomalies": anomalies,
                    "metrics": m,
                    "action": "flag_for_manual_review" if anomaly_score < 5 else "quarantine",
                    "confidence": min(100, anomaly_score * 20)  # Rough confidence %
                })

        return sorted(suspicious, key=lambda x: x['anomaly_score'], reverse=True)

    def detect_coordinated_networks(self) -> List[dict]:
        """
        Detect coordinated bot networks (many agents controlled by same attacker).
        Look for:
        - Same device fingerprint
        - Same IP address
        - Highly similar connection patterns
        - Created at same time from same IP
        """

        # Query agents created near-simultaneously from same IP
        suspicious_groups = self.db.query("""
            SELECT created_at, creator_ip, device_fingerprint,
                   COUNT(*) as agent_count, GROUP_CONCAT(id) as agent_ids
            FROM agents
            WHERE created_at > NOW() - INTERVAL 30 DAYS
              AND deleted_at IS NULL
            GROUP BY creator_ip, device_fingerprint
            HAVING COUNT(*) > 5
            ORDER BY agent_count DESC
        """)

        coordinated = []
        for group in suspicious_groups:
            coordinated.append({
                "creator_ip": group['creator_ip'],
                "device_fingerprint": group['device_fingerprint'],
                "agent_count": group['agent_count'],
                "agent_ids": group['agent_ids'].split(','),
                "action": "quarantine_all_agents",
                "reason": "coordinated_network_detected"
            })

        return coordinated

    def detect_link_farming_attack(self) -> List[dict]:
        """
        Detect link farming: coordinated bots all connecting to same set of targets.

        Pattern:
        - Many new agents (created in last 7 days)
        - All connecting to same 5-10 high-value targets
        - None of them connect to each other
        """

        # Find recent agents
        recent_agents = self.db.query("""
            SELECT id FROM agents
            WHERE created_at > NOW() - INTERVAL 7 DAYS
              AND deleted_at IS NULL
        """)

        recent_agent_ids = [a['id'] for a in recent_agents]

        # Find common targets
        target_connections = self.db.query(f"""
            SELECT to_agent_id, COUNT(*) as connection_count
            FROM connections
            WHERE from_agent_id IN ({','.join(f"'{id}'" for id in recent_agent_ids)})
              AND deleted_at IS NULL
            GROUP BY to_agent_id
            ORDER BY connection_count DESC
            LIMIT 20
        """)

        # Check if many new agents all target same users
        suspicious = []
        for target in target_connections:
            if target['connection_count'] >= len(recent_agent_ids) * 0.3:  # >30% of recent agents
                # Check if these agents also connect to each other
                internal_connections = self.db.query(f"""
                    SELECT COUNT(*) as count
                    FROM connections
                    WHERE from_agent_id IN ({','.join(f"'{id}'" for id in recent_agent_ids)})
                      AND to_agent_id IN ({','.join(f"'{id}'" for id in recent_agent_ids)})
                      AND deleted_at IS NULL
                """)

                if internal_connections[0]['count'] < len(recent_agent_ids) * 0.1:  # <10% internal
                    suspicious.append({
                        "target_agent_id": target['to_agent_id'],
                        "connection_count_from_new_agents": target['connection_count'],
                        "reason": "link_farming_attack",
                        "action": "quarantine_recent_agents_and_hide_target_profile"
                    })

        return suspicious
```

### Real-Time Anomaly Detection Pipeline

```python
class RealtimeAnomalyDetection:
    """
    Continuously monitor for anomalies as connections happen.
    """

    def on_connection_created(self, from_agent_id: str, to_agent_id: str):
        """Called every time a connection is made."""

        # Quick checks (O(1) operations)
        from_agent = self.db.get_agent(from_agent_id)

        # Check 1: Is from_agent too new + high out-degree?
        age_days = (time.time() - from_agent['created_at']) / 86400
        out_degree = self.db.get_agent_out_degree(from_agent_id)

        if age_days < 7 and out_degree > 50:
            # Increment suspicion score
            self.db.increment(f"suspicion:{from_agent_id}", 1)

            if self.db.get(f"suspicion:{from_agent_id}") > 100:
                self.db.insert({
                    "table": "agent_abuse_flags",
                    "agent_id": from_agent_id,
                    "reason": "rapid_connection_accumulation",
                    "flagged_at": time.time()
                })

        # Check 2: Is target a honeypot?
        to_agent = self.db.get_agent(to_agent_id)
        if to_agent.get('is_honeypot'):
            self.db.insert({
                "table": "honeypot_contacts",
                "scraper_agent_id": from_agent_id,
                "honeypot_agent_id": to_agent_id,
                "contacted_at": time.time()
            })
```

### Summary: Graph Anomaly Detection

| Technique | Detection Latency | False Positive Rate | Computational Cost |
|-----------|------------------|-------------------|-------------------|
| **Degree Distribution** | Immediate | Medium | O(1) |
| **Temporal Clustering** | Minutes | Low | O(degree) |
| **Device Diversity** | Immediate | Very Low | O(1) |
| **Coordinated Networks** | Hours | Very Low | O(n log n) |
| **Link Farming** | Hours | Low | O(degree^2) |

**Recommended:** Degree distribution (realtime) + temporal clustering (batched hourly)

---

## 6. REAL-WORLD EXAMPLES: LinkedIn, Signal, Mastodon

### LinkedIn Connection Spam Prevention

**Mechanisms:**
1. **Daily request limit:** ~100 requests/day for new users, ~300 for established
2. **Sender reputation:** Requests from low-engagement users more likely to be ignored
3. **Mutual connection bonus:** Requests involving mutual connections more likely accepted
4. **InMail rate limiting:** Paid feature + additional rate limits
5. **Automated rejection triggers:**
   - Generic messages ("I'd like to add you...")
   - No mutual connections
   - Sender has <5 endorsements/recommendations
6. **IP-based limits:** Same IP creating 50+ profiles in 24h is flagged

**What we can borrow:**
- Trust score boost for mutual connections
- Profile quality signals (endorsements = vouches)
- Generic message detection (but we skip content scanning)
- IP/device-based bulk account detection

### Signal (Messenger) Contact Discovery Privacy

**Mechanisms:**
1. **Hashed contact lists:** Client hashes all phone numbers locally, sends hashes to server (not raw)
2. **Salted hashing:** Hashes are salted to prevent rainbow table attacks
3. **No enumeration attacks:** Server can't guess phone numbers
4. **Rate limiting:** Contact sync limited to once per day per user
5. **No public directory:** Can't scrape all contacts

**What we can borrow:**
- Hash-based profile IDs instead of sequential
- Rate limiting discovery/scraping
- No full-text profile search (require username/@handle)
- Require authentication for bulk requests

### Mastodon Federation Abuse Prevention

**Mechanisms:**
1. **Instance-level reputation:** If server A sends spam, server B rate-limits all from A
2. **Follow request delays:** New follows don't appear immediately (24h delay)
3. **Follower approval:** Accounts can require follow approval
4. **Signature verification:** All activities cryptographically signed
5. **Admin federation controls:** Can silently drop all messages from bad servers
6. **Report aggregation:** Multiple reports of same server triggers defederation vote

**What we can borrow:**
- Hierarchical trust (agent's home server affects their trust score)
- Cryptographic signing of all actions
- Approval workflows for new connections
- Reputation decay: old abuse doesn't count as heavily

---

## 7. RECOMMENDED IMPLEMENTATION ROADMAP FOR TRUSTMESH

### Phase 1: Foundation (Week 1-2)
1. **Implement PoW on agent creation** (difficulty_bits=22)
2. **Add token-bucket rate limiting** (20 conn/day for new, 50 for established)
3. **Device fingerprint binding** (reject new accounts from devices with 10+ existing accounts)
4. **Basic temporal anomaly detection** (flag >10 agents created from same device in 24h)

### Phase 2: Trust & Reputation (Week 3-4)
1. **Implement vouching system** (5 vouches required for unrestricted mode)
2. **Compute basic trust scores** (based on age + connection count)
3. **Real-time penalties** (trust score -15 for spam, -3 for vouchers)
4. **Honeypot profiles** (10 obvious bots for entrapment)

### Phase 3: Detection & Defense (Week 5-6)
1. **Graph anomaly detection** (detect spambots via degree + temporal patterns)
2. **Coordinated network detection** (same device, same IP, same time)
3. **Link farming detection** (many new agents targeting same users)
4. **Profile scraping rate limiting** (100 profiles/min per user)

### Phase 4: Advanced (Week 7+)
1. **PageRank-based trust propagation** (daily batch)
2. **Adaptive PoW** (increase difficulty if attack detected)
3. **Federation-level reputation** (cross-server trust scores for multi-server deployments)
4. **ML model for anomaly scoring** (ensemble of graph metrics)

---

## 8. DATABASE SCHEMA ADDITIONS

```sql
-- PoW tokens for Sybil resistance
CREATE TABLE pow_tokens (
    id VARCHAR(255) PRIMARY KEY,
    agent_id VARCHAR(255) NOT NULL,
    nonce INT NOT NULL,
    difficulty_bits INT NOT NULL,
    pow_hash VARCHAR(64) NOT NULL,
    created_at BIGINT NOT NULL,
    verified_at BIGINT,
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    INDEX (created_at)
);

-- Device fingerprints for Sybil detection
CREATE TABLE agent_device_bindings (
    id VARCHAR(255) PRIMARY KEY,
    agent_id VARCHAR(255) NOT NULL UNIQUE,
    device_fingerprint VARCHAR(64) NOT NULL,
    verified_at BIGINT NOT NULL,
    last_verified_at BIGINT,
    fingerprint_drift_score FLOAT,
    status ENUM('verified', 'drifted', 'suspicious'),
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    INDEX (device_fingerprint),
    INDEX (status)
);

-- Vouching relationships
CREATE TABLE vouches (
    id VARCHAR(255) PRIMARY KEY,
    new_agent_id VARCHAR(255) NOT NULL,
    voucher_agent_id VARCHAR(255) NOT NULL,
    vouch_strength FLOAT DEFAULT 1.0,
    status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    created_at BIGINT NOT NULL,
    approved_at BIGINT,
    penalty_applied TINYINT DEFAULT 0,
    FOREIGN KEY (new_agent_id) REFERENCES agents(id),
    FOREIGN KEY (voucher_agent_id) REFERENCES agents(id),
    INDEX (status),
    INDEX (created_at)
);

-- Trust score violations & updates
CREATE TABLE trust_score_violations (
    id VARCHAR(255) PRIMARY KEY,
    agent_id VARCHAR(255) NOT NULL,
    violation_type VARCHAR(100) NOT NULL,
    penalty INT NOT NULL,
    previous_score INT,
    new_score INT,
    timestamp BIGINT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    INDEX (agent_id),
    INDEX (timestamp)
);

-- Honeypot profiles & contacts
CREATE TABLE honeypot_contacts (
    id VARCHAR(255) PRIMARY KEY,
    scraper_agent_id VARCHAR(255) NOT NULL,
    honeypot_agent_id VARCHAR(255) NOT NULL,
    contacted_at BIGINT NOT NULL,
    FOREIGN KEY (scraper_agent_id) REFERENCES agents(id),
    FOREIGN KEY (honeypot_agent_id) REFERENCES agents(id),
    INDEX (scraper_agent_id),
    INDEX (contacted_at)
);

-- Rate limit tracking (can be in Redis, but useful to log)
CREATE TABLE rate_limit_rejections (
    id VARCHAR(255) PRIMARY KEY,
    agent_id VARCHAR(255) NOT NULL,
    limit_type VARCHAR(50) NOT NULL,
    rejected_at BIGINT NOT NULL,
    retry_after_seconds INT,
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    INDEX (agent_id, rejected_at)
);

-- Agent abuse flags
CREATE TABLE agent_abuse_flags (
    id VARCHAR(255) PRIMARY KEY,
    agent_id VARCHAR(255) NOT NULL,
    reason VARCHAR(255) NOT NULL,
    flagged_at BIGINT NOT NULL,
    reviewed_at BIGINT,
    action ENUM('warning', 'quarantine', 'suspend', 'ban'),
    status ENUM('pending', 'reviewed', 'resolved'),
    FOREIGN KEY (agent_id) REFERENCES agents(id),
    INDEX (status, flagged_at)
);

-- Add to agents table
ALTER TABLE agents ADD COLUMN (
    is_honeypot TINYINT DEFAULT 0,
    trust_score INT DEFAULT 10,
    abuse_flag TINYINT DEFAULT 0,
    last_trust_score_update BIGINT
);
```

---

## 9. IMPLEMENTATION CHECKLIST

```
SYBIL RESISTANCE:
  [ ] Proof-of-Work on agent creation (22 bits)
  [ ] Device fingerprint binding
  [ ] Vouching system (5 vouches required)
  [ ] Temporal anomaly detection

CONNECTION RATE LIMITING:
  [ ] Token bucket rate limiter (20/50/100 per tier)
  [ ] Real-time token consumption
  [ ] Burst detection (5+ requests in 100ms)
  [ ] Rate limit rejection logging

TRUST SCORING:
  [ ] Trust score initialization (based on age)
  [ ] Real-time penalties (connection spam, abuse)
  [ ] Voucher cascade penalties
  [ ] Daily PageRank batch computation

PROFILE PROTECTION:
  [ ] Progressive disclosure (public/friends/private)
  [ ] Bulk request rate limiting (100/min)
  [ ] Hash-based agent IDs
  [ ] Honeypot profiles (10x)

GRAPH ANOMALY DETECTION:
  [ ] Degree distribution metrics
  [ ] Clustering coefficient
  [ ] Temporal concentration scoring
  [ ] Device diversity check
  [ ] Coordinated network detection
  [ ] Link farming detection

MONITORING & ALERTING:
  [ ] Real-time anomaly scoring on new connections
  [ ] Hourly batch anomaly detection job
  [ ] Admin dashboard for flags
  [ ] Automated quarantine triggers
  [ ] Manual review queue
```

---

## 10. METRICS TO MONITOR

```
Security Metrics:
- % of new agents with >50 connections in 24h
- % of connection requests from new agents
- Average time-to-first-connection per agent
- % of agents with <0.1 clustering coefficient
- % of agents from device with >5 existing accounts

Abuse Detection:
- False positive rate (legitimate agents quarantined)
- Detection latency (time from attack start to detection)
- Attack size at detection (how many fake agents created)
- Recovery time (time to restore legitimate agent access)

User Experience:
- % of legitimate connection requests rejected by rate limit
- Average time to get 5 vouches
- % of agents completing identity verification
- Rate limit false positive complaints

Business:
- % of spam/abuse reports trending down
- Time to resolve abuse cases (SLA)
- Cost per abuse prevention (compute + manual review hours)
```

---

## CONCLUSION

This multi-layered approach provides **defense-in-depth** against agent-to-agent abuse:

1. **Sybil Resistance** (PoW + Device + Vouching) makes creating fake agents expensive
2. **Rate Limiting** (Token Bucket) prevents mass-connecting blasts
3. **Trust Propagation** (PageRank) makes new agents inherently low-trust
4. **Profile Protection** (Progressive Disclosure) limits attack surface even if scraped
5. **Graph Anomalies** (ML-based) detects coordinated attacks in real-time
6. **Honeypots** provides early detection of sophisticated attackers

**No single mechanism is bulletproof.** An attacker defeating PoW is still rate-limited. If they bypass rate-limiting, they're detected by graph anomalies. If they avoid graph anomalies, honeypots catch them.

Start with Phase 1 (PoW + Rate Limiting + Device Binding) to get 80% of the protection. Add Phases 2-3 for the remaining 20%.
