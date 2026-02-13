# Tinfoil.sh Architecture & Integration Diagrams

## System Architecture

### Tinfoil Inference Platform Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Application                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Tinfoil SDK (Python/JS/Go/Swift)                        │  │
│  │  - Automatic attestation verification                   │  │
│  │  - Certificate pinning                                  │  │
│  │  - End-to-end encryption                               │  │
│  └────────────────┬─────────────────────────────────────────┘  │
└─────────────────┼──────────────────────────────────────────────┘
                  │ HTTPS
                  │ Authorization: Bearer sk-xxx
                  │ Content-Type: application/json
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Tinfoil Inference Service                    │
│              https://inference.tinfoil.sh/v1/*                 │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Router Enclave (Attestation & Load Balancing)         │  │
│  │  - Verifies client requests                            │  │
│  │  - Routes to appropriate inference enclave             │  │
│  │  - Manages SSL/TLS with certificate pinning            │  │
│  └────────┬────────────────────────────────────────────────┘  │
│           │                                                     │
│     ┌─────┴────────┬──────────────┬──────────────┬───────┐    │
│     │              │              │              │       │    │
│  ┌──▼──┐      ┌───▼──┐      ┌──▼──┐      ┌───▼──┐  ┌──▼──┐ │
│  │ GPU1│      │ GPU2 │      │ GPU3│      │ GPU4 │  │ ... │ │
│  │(TEE)│      │(TEE) │      │(TEE)│      │(TEE) │  │     │ │
│  └─────┘      └──────┘      └─────┘      └──────┘  └─────┘ │
│   Kimi K2.5   Llama 3.3    DeepSeek-R1   Qwen3-V    ...    │
│                                                                 │
│  Hardware: NVIDIA Hopper/Blackwell GPUs                       │
│  Security: Encrypted computation in isolated hardware          │
│  Data: Encrypted in-flight, decrypted only inside enclave     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Request/Response Flow

### Chat Completion Flow

```
Your Code                    Tinfoil Service
    │                            │
    │ client.chat.completions   │
    │ .create(                  │
    │   model="kimi-k2.5",      │
    │   messages=[...],         │
    │   tools=[...]             │
    │ )                         │
    ├─────────── POST ──────────>
    │  /v1/chat/completions     │
    │                           │ Authenticate
    │                           │ (verify API key)
    │                           │
    │                           │ Route to GPU
    │                           │ in secure enclave
    │                           │
    │                           │ Execute model
    │                           │ inside TEE
    │                           │
    │<───────── 200 OK ─────────┤
    │ {                         │
    │   choices: [{             │
    │     message: {            │
    │       tool_calls: [...]   │
    │     }                     │
    │   }],                     │
    │   usage: {...}            │
    │ }                         │
    │                           │
    Process tool calls         │
    │                           │
    │ Send tool results         │
    │ back to model             │
    ├─────────── POST ──────────>
    │                           │
    │<───────── 200 OK ─────────┤
    │ Final response            │
    │                           │
```

---

## Function Calling Architecture

### Tool Calling Flow

```
┌─────────────────────────────────────────────────┐
│  1. Define Tools                                │
│                                                 │
│  tools = [{                                     │
│    "type": "function",                          │
│    "function": {                                │
│      "name": "get_weather",                     │
│      "description": "...",                      │
│      "parameters": {...}                        │
│    }                                            │
│  }]                                             │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  2. Send to Tinfoil                             │
│                                                 │
│  POST /v1/chat/completions                      │
│  {                                              │
│    model: "kimi-k2.5",                          │
│    messages: [...],                             │
│    tools: [...]  ◄─── Pass tool definitions    │
│  }                                              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  3. Model Decision (Inside Enclave)             │
│                                                 │
│  Kimi K2.5 analyzes:                            │
│  - User prompt                                  │
│  - Available tools                              │
│  - Decides: "I need weather for London"         │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  4. Return Tool Call                            │
│                                                 │
│  {                                              │
│    choices: [{                                  │
│      message: {                                 │
│        tool_calls: [{                           │
│          id: "call_123",                        │
│          function: {                            │
│            name: "get_weather",                 │
│            arguments: '{"location":"London"}'   │
│          }                                      │
│        }]                                       │
│      }                                          │
│    }]                                           │
│  }                                              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  5. Your Code Executes Tool                     │
│                                                 │
│  result = get_weather("London")                 │
│         → {"temp": 15, "condition": "rainy"}    │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  6. Send Results Back                           │
│                                                 │
│  POST /v1/chat/completions                      │
│  {                                              │
│    messages: [                                  │
│      {role: "user", content: "..."},            │
│      {role: "assistant", tool_calls: [...]},    │
│      {role: "tool", content: result}            │
│    ]                                            │
│  }                                              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  7. Final Response                              │
│                                                 │
│  "It's 15°C and rainy in London today"          │
└─────────────────────────────────────────────────┘
```

---

## Security Architecture

### Verifiable Privacy with TEE

```
┌──────────────────────────────────────────────────────────────┐
│                      Your Application                        │
│                                                              │
│  Data: "What is in this confidential document?"             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Tinfoil SDK                                          │  │
│  │ 1. Verify attestation of inference server           │  │
│  │ 2. Pin TLS certificate                              │  │
│  │ 3. Encrypt request with session key                 │  │
│  │ 4. Send encrypted data                              │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────┬─────────────────────────────────────────┘
                     │ ENCRYPTED
                     │ {eHgV2k9... (encrypted)}
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│               Tinfoil Inference Service                      │
│          (NVIDIA Hopper GPU + Confidential Compute)         │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │        Secure Hardware Enclave (TEE)               │    │
│  │                                                    │    │
│  │  1. Receive encrypted request                     │    │
│  │  2. Decrypt inside TEE                            │    │
│  │  3. Process in isolated environment               │    │
│  │  4. Encrypt response                              │    │
│  │  5. Send encrypted response                       │    │
│  │                                                    │    │
│  │  Security properties:                             │    │
│  │  ✓ Hardware-isolated computation                  │    │
│  │  ✓ Data never visible outside enclave             │    │
│  │  ✓ Even Tinfoil staff cannot access data          │    │
│  │  ✓ Cryptographic attestation proves security      │    │
│  └────────────────────────────────────────────────────┘    │
└────────────────────┬─────────────────────────────────────────┘
                     │ ENCRYPTED
                     │ {aBxC3m7... (encrypted response)}
                     │
                     ▼
┌──────────────────────────────────────────────────────────────┐
│                      Your Application                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Tinfoil SDK                                          │  │
│  │ 1. Verify TLS certificate                           │  │
│  │ 2. Decrypt response                                 │  │
│  │ 3. Return plaintext to application                  │  │
│  │                                                      │  │
│  │ GUARANTEE: This data was processed inside a         │  │
│  │ verified secure enclave. Nobody else saw it.        │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## Integration Points

### Where Tinfoil Fits in Your Stack

```
┌─────────────────────────────────────────────────────────┐
│                   Your Application                      │
│                                                         │
│  ┌─────────────────────────────────────────────────┐  │
│  │  Application Logic (Your Code)                  │  │
│  │  - User interface                              │  │
│  │  - Business logic                              │  │
│  │  - Data processing                             │  │
│  └────────────────┬────────────────────────────────┘  │
│                   │                                    │
│     ┌─────────────┴─────────────┐                     │
│     │                           │                     │
│     ▼                           ▼                     │
│ ┌────────────┐        ┌──────────────────┐          │
│ │  Database  │        │ Tinfoil SDK      │          │
│ │            │        │                  │          │
│ │ Stores:    │        │ Handles:         │          │
│ │ - User data│        │ - API calls      │          │
│ │ - Metadata │        │ - Verification   │          │
│ │ - Config   │        │ - Tool calling   │          │
│ └────────────┘        │ - Streaming      │          │
│                       └────────┬─────────┘          │
│                                │                     │
│                                ▼                     │
└─────────────────────────────────────────────────────┘
                                │
                    ┌───────────┘
                    │ HTTPS + Encryption
                    │
                    ▼
       ┌────────────────────────────────┐
       │  Tinfoil Inference Service     │
       │  https://inference.tinfoil.sh │
       │  /v1/chat/completions         │
       │  /v1/audio/transcriptions      │
       │  /v1/embeddings                │
       └────────────────────────────────┘
```

---

## Authentication Flow

### API Key Verification

```
Step 1: Generate API Key
┌──────────────────────────────────┐
│  https://dash.tinfoil.sh         │
│  Create API key                  │
│  → sk-xxxxxxxxxxxxxxxxxxxxxxx    │
└──────────────────────────────────┘

Step 2: Store Securely
export TINFOIL_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxx"

Step 3: SDK Auto-loads
from tinfoil import TinfoilAI
client = TinfoilAI()  # Reads TINFOIL_API_KEY env var

Step 4: Add to Requests
Authorization: Bearer sk-xxxxxxxxxxxxxxxxxxxxxxx

Step 5: Server Verification
┌──────────────────────────────────┐
│  Tinfoil Service                 │
│  1. Receive API key              │
│  2. Look up in database          │
│  3. Verify not revoked           │
│  4. Check rate limits            │
│  5. Allow/deny request           │
└──────────────────────────────────┘
```

---

## Model Selection Decision Tree

```
Start
  │
  ├─ Need Tool Calling?
  │  ├─ YES → Use kimi-k2.5 (BEST) ⭐⭐⭐
  │  │        or kimi-k2-thinking (⭐⭐⭐)
  │  │        or llama3-3-70b (⭐⭐)
  │  │
  │  └─ NO → Continue
  │
  ├─ Code Generation?
  │  ├─ YES → Use qwen3-coder-480b
  │  └─ NO → Continue
  │
  ├─ Vision/Images?
  │  ├─ YES → Use qwen3-vl
  │  └─ NO → Continue
  │
  ├─ Complex Reasoning?
  │  ├─ YES → Use deepseek-r1 or kimi-k2-thinking
  │  └─ NO → Continue
  │
  ├─ Need Fastest Response?
  │  ├─ YES → Use llama3-3-70b or gpt-oss-20b
  │  └─ NO → Continue
  │
  └─ Default → Use llama3-3-70b (balanced)
```

---

## Cost Flow

### Token-Based Billing

```
Your Request
  │
  ├─ Input Tokens (e.g., 100)
  │  └─ Counted: "How are you?" = 5 tokens
  │            + system prompt = 95 tokens
  │
  ├─ Processing
  │  └─ Model runs in Tinfoil enclave
  │
  └─ Output Tokens (e.g., 50)
     └─ Counted: "I am doing well..." = 50 tokens

Total: 150 tokens

Billing:
150 tokens × ($2 / 1,000,000 tokens) = $0.0003

Daily Usage:
- 50 queries × 150 tokens = 7,500 tokens
- 7,500 × $2/1M = $0.015/day
- Monthly: $0.45
```

---

## Infrastructure Overview

### Tinfoil Platform Components

```
┌──────────────────────────────────────────────────────────┐
│                     Tinfoil Platform                     │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Frontend Layer                                          │
│  ├─ Web Chat: https://chat.tinfoil.sh                   │
│  ├─ Dashboard: https://dash.tinfoil.sh                  │
│  └─ Documentation: https://docs.tinfoil.sh              │
│                                                          │
│  API Layer                                               │
│  ├─ Chat Completions: /v1/chat/completions              │
│  ├─ Audio: /v1/audio/transcriptions                     │
│  ├─ Embeddings: /v1/embeddings                          │
│  └─ Speech: /v1/audio/speech                            │
│                                                          │
│  SDK Layer                                               │
│  ├─ Python: pip install tinfoil                         │
│  ├─ JavaScript: npm install tinfoil                     │
│  ├─ Go: go get github.com/tinfoilsh/tinfoil-go         │
│  └─ Swift: Swift Package Manager                        │
│                                                          │
│  Infrastructure Layer                                    │
│  ├─ Router Enclaves (Load balancing & attestation)      │
│  ├─ Inference Enclaves (Model processing)               │
│  │  ├─ GPU 1: NVIDIA Hopper (TEE mode)                 │
│  │  ├─ GPU 2: NVIDIA Blackwell (TEE mode)              │
│  │  └─ GPU N: ...                                       │
│  ├─ Model Storage (Encrypted)                           │
│  └─ Metrics & Logging                                   │
│                                                          │
│  Security Layer                                          │
│  ├─ Attestation Verification                            │
│  ├─ TLS/SSL with Certificate Pinning                    │
│  ├─ End-to-End Encryption                               │
│  └─ Hardware Isolation (TEE)                            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Deployment Architecture

### Tinfoil in Your Production Stack

```
Internet
  │
  ▼
┌──────────────────────────────────┐
│    Your Reverse Proxy            │
│    (nginx, CloudFlare, etc)      │
└──────────────────────────────────┘
  │
  ▼
┌──────────────────────────────────┐
│    Your Application Container    │
│    - Express.js / FastAPI / etc  │
│    - tinfoil SDK installed       │
│    - Rate limiting middleware    │
│    - Error handling              │
└──────────────────────────────────┘
  │
  ├─────────────────┬──────────────┐
  │                 │              │
  ▼                 ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────────┐
│ Database │  │ Cache    │  │ Tinfoil API  │
│ (Local)  │  │ (Redis)  │  │ (HTTPS)      │
└──────────┘  └──────────┘  └──────────────┘

Flow:
1. User request → Your server
2. Your server queries Tinfoil (with API key)
3. Tinfoil processes in enclave
4. Response returned to your server
5. Server processes and returns to user
```

---

## Error Handling Flow

```
Request
  │
  ├─ API Key Invalid?
  │  ├─ YES → 401 Unauthorized
  │  │        Check TINFOIL_API_KEY env var
  │  │
  │  └─ NO → Continue
  │
  ├─ Request Format Invalid?
  │  ├─ YES → 400 Bad Request
  │  │        Validate JSON payload
  │  │
  │  └─ NO → Continue
  │
  ├─ Rate Limit Exceeded?
  │  ├─ YES → 429 Too Many Requests
  │  │        Implement exponential backoff
  │  │
  │  └─ NO → Continue
  │
  ├─ Server Error?
  │  ├─ YES → 500/503 Server Error
  │  │        Retry with backoff
  │  │        Check https://status.tinfoil.sh
  │  │
  │  └─ NO → Continue
  │
  └─ Success! → 200 OK
     Return response to application
```

---

## Comparison: Direct HTTP vs SDK

```
┌─────────────────────────────────────────────────────────┐
│              Without SDK (Direct HTTP)                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ❌ No attestation verification                         │
│  ❌ No certificate pinning                              │
│  ❌ Vulnerable to MITM attacks                          │
│  ❌ Manual error handling                               │
│  ✓ Fewer dependencies                                   │
│  ✓ Slightly faster (no verification overhead)          │
│                                                         │
│  Use case: Testing only, internal networks             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              With SDK (Recommended)                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ✓ Automatic attestation verification                  │
│  ✓ Certificate pinning enabled                         │
│  ✓ Protection against MITM attacks                     │
│  ✓ Automatic error handling                            │
│  ✓ Streaming support built-in                          │
│  ✓ Async/await patterns                                │
│  ✓ Type hints and IDE support                          │
│  ✓ Tool calling helpers                                │
│                                                         │
│  Minimal overhead: ~50-200ms per request               │
│  Recommended for: Production deployments               │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Timeline

```
Day 1: Setup
├─ Generate API key (5 min)
├─ Install SDK (2 min)
└─ Test basic request (10 min)
   Total: 17 minutes

Day 1-2: Basic Integration
├─ Implement chat wrapper (1 hour)
├─ Add error handling (1 hour)
├─ Test streaming (30 min)
└─ Verify billing setup (30 min)
   Total: 3 hours

Day 2-3: Tool Calling
├─ Design tool schema (1 hour)
├─ Implement handler (2 hours)
├─ Test with kimi-k2.5 (1 hour)
└─ Verify tool flow (1 hour)
   Total: 5 hours

Day 3-4: Production Ready
├─ Rate limiting (2 hours)
├─ Monitoring setup (1 hour)
├─ Cost tracking (1 hour)
└─ Load testing (2 hours)
   Total: 6 hours

TOTAL: ~14-16 hours for full production deployment
```

---

## References

See related documentation:
- TINFOIL_RESEARCH.md - Complete technical details
- TINFOIL_API_SPEC.md - API endpoint specifications
- TINFOIL_IMPLEMENTATION_GUIDE.md - Code examples
- TINFOIL_QUICK_REFERENCE.md - Quick lookup

---

**Document Version**: 1.0
**Created**: 2026-02-12
**Status**: Complete
