# Tinfoil.sh Implementation Quick Reference

## Setup (5 minutes)

### 1. Get API Key
```bash
# Visit https://dash.tinfoil.sh and generate an API key
# Store securely in environment
export TINFOIL_API_KEY="sk-your-key-here"
```

### 2. Install SDK
```bash
pip install tinfoil
```

### 3. Verify Connection
```python
from tinfoil import TinfoilAI

client = TinfoilAI()  # auto-loads TINFOIL_API_KEY
response = client.chat.completions.create(
    model="llama3-3-70b",
    messages=[{"role": "user", "content": "test"}]
)
print(response.choices[0].message.content)
```

---

## Common Code Patterns

### Basic Chat
```python
from tinfoil import TinfoilAI

client = TinfoilAI()

response = client.chat.completions.create(
    model="llama3-3-70b",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantum computing briefly."}
    ],
    temperature=0.7,
    max_tokens=500
)

print(response.choices[0].message.content)
```

### Function Calling (Tool Use)
```python
from tinfoil import TinfoilAI

client = TinfoilAI()

# Define available tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}
                },
                "required": ["city"]
            }
        }
    }
]

# Initial request
response = client.chat.completions.create(
    model="kimi-k2.5",  # Best for function calling
    messages=[{"role": "user", "content": "What's the weather in London?"}],
    tools=tools,
    tool_choice="auto"
)

# Process tool calls
message = response.choices[0].message
if message.tool_calls:
    for tool_call in message.tool_calls:
        if tool_call.function.name == "get_weather":
            # Execute your function
            result = get_weather_impl(tool_call.function.arguments)

            # Send result back to model
            response = client.chat.completions.create(
                model="kimi-k2.5",
                messages=[
                    {"role": "user", "content": "What's the weather in London?"},
                    {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    }
                ],
                tools=tools
            )
            print(response.choices[0].message.content)
```

### Streaming Response
```python
from tinfoil import TinfoilAI

client = TinfoilAI()

with client.chat.completions.create(
    model="llama3-3-70b",
    messages=[{"role": "user", "content": "Write a short poem about AI"}],
    stream=True
) as stream:
    for text in stream.text_stream:
        print(text, end="", flush=True)
```

### Async/Await
```python
import asyncio
from tinfoil import AsyncTinfoilAI

async def main():
    client = AsyncTinfoilAI()

    response = await client.chat.completions.create(
        model="llama3-3-70b",
        messages=[{"role": "user", "content": "Hello"}]
    )

    print(response.choices[0].message.content)

asyncio.run(main())
```

### Audio Transcription
```python
from tinfoil import TinfoilAI

client = TinfoilAI()

with open("audio.mp3", "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=audio_file
    )

print(transcript.text)
```

---

## Model Selection Guide

### For Tool Calling / Agentic Tasks
```python
# BEST: Superior tool calling, reasoning
model = "kimi-k2.5"

# GOOD: Excellent reasoning with tool use
model = "kimi-k2-thinking"

# SOLID: Reliable tool calling, fast
model = "llama3-3-70b"
```

### For Code Generation
```python
model = "qwen3-coder-480b"  # Specialized for coding
```

### For Vision Tasks
```python
model = "qwen3-vl"  # Vision-language understanding
```

### For General Chat (Cost-Efficient)
```python
model = "llama3-3-70b"  # Balanced performance/cost
```

### For Complex Reasoning
```python
model = "deepseek-r1"  # Strong reasoning abilities
```

---

## Error Handling

```python
from tinfoil import TinfoilAI
import os

client = TinfoilAI(api_key=os.environ.get("TINFOIL_API_KEY"))

try:
    response = client.chat.completions.create(
        model="kimi-k2.5",
        messages=[{"role": "user", "content": "test"}],
        timeout=30
    )
except ValueError as e:
    # Invalid model, missing parameters, etc
    print(f"Invalid request: {e}")
except Exception as e:
    # Network, timeout, server errors
    print(f"Request failed: {e}")
    # Implement retry logic here
```

---

## Cost Estimation

**Rate**: $2 per 1,000,000 tokens

### Example Costs
| Use Case | Avg Tokens | Cost |
|----------|-----------|------|
| Simple chat (1 exchange) | 200 | $0.0004 |
| Code review (full file) | 2,000 | $0.004 |
| Daily chat usage (50 queries) | 10,000 | $0.02 |
| RAG document processing | 50,000 | $0.10 |
| Monthly usage (active dev) | 100,000 | $0.20 |

### Token Counting
```python
# Rough estimation (more accurate counting with token counter)
message = "Your message here"
estimated_tokens = len(message.split()) * 1.3  # rough approximation

# For accurate counting, could integrate with tiktoken
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")
tokens = len(enc.encode(message))
```

---

## Comparison: Tinfoil vs Alternatives

| Feature | Tinfoil | OpenAI | Claude API | Local LLM |
|---------|---------|--------|-----------|-----------|
| **Privacy** | ✓✓✓ Hardware-verified | ✓ Some data processed on cloud | ✓✓ Better privacy | ✓✓✓ Local only |
| **Cost** | $2/1M tokens | $0.50-15/1M tokens | $3-24/1M tokens | Free (compute) |
| **API Compatibility** | ✓ OpenAI | ✓ OpenAI | ✗ Custom | ✗ Varies |
| **Tool Calling** | ✓✓ Excellent | ✓✓ Excellent | ✓✓ Excellent | ✓ Good |
| **Latency** | ~200-500ms | ~100-300ms | ~150-400ms | ~100-2000ms |
| **Verifiable Security** | ✓ Cryptographic proof | ✗ Trust-based | ✗ Trust-based | ✓ Inherent |

**Use Tinfoil When**:
- Privacy/compliance is critical
- Need verifiable security guarantees
- Handling sensitive data (medical, financial, legal)
- Want open-source transparency

---

## Troubleshooting

### API Key Not Found
```python
# Make sure environment variable is set
import os
assert os.environ.get("TINFOIL_API_KEY"), "TINFOIL_API_KEY not set"
```

### Slow Responses
- Using direct HTTP instead of SDK? Use SDK for better performance
- Model might be under load. Try `kimi-k2.5` or `llama3-3-70b` for speed
- Streaming responses for long outputs: use `stream=True`

### Tool Calling Not Working
- Ensure model supports function calling: use `kimi-k2.5` or `llama3-3-70b`
- Check tool schema is valid JSON
- Verify `tool_choice="auto"` is set if you want automatic tool calling

### Rate Limiting
- Check dashboard for account limits
- Implement exponential backoff for retries
- Batch requests when possible

---

## Integration with Application

### As Drop-in Replacement
```python
# Before (OpenAI)
from openai import OpenAI
client = OpenAI(api_key="sk-...")

# After (Tinfoil) - minimal changes!
from tinfoil import TinfoilAI
client = TinfoilAI(api_key="sk-...")

# Same method calls work!
response = client.chat.completions.create(
    model="llama3-3-70b",  # change model name
    messages=[...]
)
```

### Environment-Based Selection
```python
import os
from tinfoil import TinfoilAI
from openai import OpenAI

if os.environ.get("USE_TINFOIL"):
    client = TinfoilAI()
else:
    client = OpenAI()

# Same code works for both!
response = client.chat.completions.create(...)
```

---

## Resources

- **Docs**: https://docs.tinfoil.sh
- **Dashboard**: https://dash.tinfoil.sh
- **GitHub**: https://github.com/tinfoilsh/tinfoil-python
- **PyPI**: https://pypi.org/project/tinfoil/
- **Status**: https://status.tinfoil.sh

---

## Related Integration Files

See also:
- `TINFOIL_RESEARCH.md` - Comprehensive technical research
- Project documentation for TEE provider abstraction layer
