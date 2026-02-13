# Tinfoil.sh API Specification - Technical Details

## Endpoint Configuration

### HTTP Endpoint
```
https://inference.tinfoil.sh/v1/chat/completions
```

### Request Method
```
POST
```

### Content Type
```
Content-Type: application/json
```

---

## Authentication

### Header Format
```
Authorization: Bearer YOUR_API_KEY
```

### Example Header
```
Authorization: Bearer sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### API Key Format
- **Prefix**: `sk-`
- **Length**: ~48-50 characters
- **Source**: Generated at https://dash.tinfoil.sh
- **Environment Variable**: `TINFOIL_API_KEY`

---

## Request Payload Schema

### Complete Example
```json
POST https://inference.tinfoil.sh/v1/chat/completions
Authorization: Bearer sk-your-api-key
Content-Type: application/json

{
  "model": "kimi-k2.5",
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Hello, how are you?"
    }
  ],
  "temperature": 0.7,
  "top_p": 0.9,
  "max_tokens": 500,
  "stream": false,
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather information",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "City name"
            }
          },
          "required": ["location"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Required Fields
| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Model identifier (see model list) |
| `messages` | array | Conversation history |

### Optional Fields
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `temperature` | float | 1.0 | 0.0-2.0, controls randomness |
| `top_p` | float | 1.0 | 0.0-1.0, nucleus sampling |
| `max_tokens` | int | unlimited | Max output tokens |
| `stream` | boolean | false | Stream response chunks |
| `tools` | array | undefined | Available functions for tool calling |
| `tool_choice` | string | "auto" | "auto", "required", or function name |
| `frequency_penalty` | float | 0 | -2.0 to 2.0 |
| `presence_penalty` | float | 0 | -2.0 to 2.0 |

---

## Response Payload Schema

### Standard Response (Non-Streaming)
```json
{
  "id": "chatcmpl-123456",
  "object": "chat.completion",
  "created": 1707123456,
  "model": "kimi-k2.5",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! I'm doing well, thank you for asking.",
        "tool_calls": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 15,
    "total_tokens": 40
  }
}
```

### Tool Calling Response
```json
{
  "id": "chatcmpl-789012",
  "object": "chat.completion",
  "created": 1707123457,
  "model": "kimi-k2.5",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": null,
        "tool_calls": [
          {
            "id": "call_abc123def456",
            "type": "function",
            "function": {
              "name": "get_weather",
              "arguments": "{\"location\": \"London\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ],
  "usage": {
    "prompt_tokens": 45,
    "completion_tokens": 28,
    "total_tokens": 73
  }
}
```

### Streaming Response (Chunks)
```json
{"object":"chat.completion.chunk","id":"chatcmpl-999","created":1707123458,"model":"kimi-k2.5","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}

{"object":"chat.completion.chunk","id":"chatcmpl-999","created":1707123458,"model":"kimi-k2.5","choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}

{"object":"chat.completion.chunk","id":"chatcmpl-999","created":1707123458,"model":"kimi-k2.5","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
```

---

## Message Format

### Role Types
```python
{
  "role": "system",    # System prompt/instructions
  "content": "You are a helpful assistant."
}

{
  "role": "user",      # User message
  "content": "What is 2+2?"
}

{
  "role": "assistant", # Assistant response
  "content": "The answer is 4."
}

{
  "role": "tool",      # Tool/function result
  "tool_call_id": "call_abc123",
  "content": "{\"weather\": \"sunny\", \"temp\": 72}"
}
```

### Message Content Types
```python
# Text content
{"role": "user", "content": "Hello"}

# Multiple content types (for vision models)
{"role": "user", "content": [
    {"type": "text", "text": "What's in this image?"},
    {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
]}
```

---

## Tool/Function Calling Schema

### Tool Definition
```json
{
  "type": "function",
  "function": {
    "name": "calculate",
    "description": "Perform a mathematical calculation",
    "parameters": {
      "type": "object",
      "properties": {
        "operation": {
          "type": "string",
          "enum": ["add", "subtract", "multiply", "divide"],
          "description": "The operation to perform"
        },
        "a": {
          "type": "number",
          "description": "First operand"
        },
        "b": {
          "type": "number",
          "description": "Second operand"
        }
      },
      "required": ["operation", "a", "b"]
    }
  }
}
```

### Tool Choice Options
```
"tool_choice": "auto"       # Let model decide
"tool_choice": "required"   # Force tool calling
"tool_choice": "none"       # No tool calling
"tool_choice": {"type": "function", "function": {"name": "calculate"}}  # Specific tool
```

---

## Model IDs (Complete List)

### Chat Models
```
kimi-k2.5              # Best for agentic/tool calling - RECOMMENDED
kimi-k2-thinking       # Reasoning with tool calling
llama3-3-70b          # General purpose, multilingual
qwen3-coder-480b      # Code generation specialized
qwen3-vl              # Vision-language model
deepseek-r1           # Reasoning model
gpt-oss-120b          # General purpose (large)
gpt-oss-20b           # General purpose (smaller)
```

### Audio Models
```
whisper-large-v3-turbo # Audio transcription
```

---

## cURL Examples

### Basic Chat
```bash
curl -X POST https://inference.tinfoil.sh/v1/chat/completions \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3-3-70b",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### With Temperature Control
```bash
curl -X POST https://inference.tinfoil.sh/v1/chat/completions \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kimi-k2.5",
    "messages": [{"role": "user", "content": "Write a poem"}],
    "temperature": 0.8,
    "max_tokens": 200
  }'
```

### With Tool Calling
```bash
curl -X POST https://inference.tinfoil.sh/v1/chat/completions \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kimi-k2.5",
    "messages": [{"role": "user", "content": "Whats the weather?"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "Get weather",
        "parameters": {
          "type": "object",
          "properties": {"city": {"type": "string"}},
          "required": ["city"]
        }
      }
    }],
    "tool_choice": "auto"
  }'
```

### Streaming Response
```bash
curl -X POST https://inference.tinfoil.sh/v1/chat/completions \
  -H "Authorization: Bearer sk-your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3-3-70b",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```

---

## Python Examples

### Direct HTTP (Not Recommended - No Verification)
```python
import requests
import os

api_key = os.environ.get("TINFOIL_API_KEY")

response = requests.post(
    "https://inference.tinfoil.sh/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    },
    json={
        "model": "llama3-3-70b",
        "messages": [{"role": "user", "content": "Hello"}]
    }
)

data = response.json()
print(data["choices"][0]["message"]["content"])
```

### Using Tinfoil SDK (Recommended)
```python
from tinfoil import TinfoilAI
import os

client = TinfoilAI(api_key=os.environ.get("TINFOIL_API_KEY"))

response = client.chat.completions.create(
    model="llama3-3-70b",
    messages=[{"role": "user", "content": "Hello"}]
)

print(response.choices[0].message.content)
```

---

## Error Handling

### HTTP Status Codes
| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Invalid request (bad parameters) |
| 401 | Unauthorized (invalid API key) |
| 429 | Rate limited |
| 500 | Server error |
| 503 | Service unavailable |

### Error Response Format
```json
{
  "error": {
    "message": "Invalid model specified",
    "type": "invalid_request_error",
    "param": "model",
    "code": "invalid_value"
  }
}
```

### Python Exception Handling
```python
from tinfoil import TinfoilAI

try:
    response = client.chat.completions.create(...)
except ValueError as e:
    # Invalid parameters
    print(f"Invalid request: {e}")
except Exception as e:
    # Network or server errors
    print(f"Error: {e}")
```

---

## Rate Limiting & Quotas

### Check Dashboard For
- Requests per minute (RPM)
- Tokens per minute (TPM)
- Daily/monthly usage limits
- Account tier limits

### Recommended Retry Strategy
```python
import time
from tinfoil import TinfoilAI

client = TinfoilAI()

def call_with_retry(max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model="llama3-3-70b",
                messages=[{"role": "user", "content": "test"}]
            )
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # exponential backoff
                time.sleep(wait_time)
            else:
                raise

response = call_with_retry()
```

---

## Security Considerations

### Do
- ✓ Store API key in environment variable
- ✓ Use SDK for automatic verification
- ✓ Implement certificate pinning (SDK does this)
- ✓ Use HTTPS (enforce in code)
- ✓ Rotate API keys periodically

### Don't
- ✗ Commit API key to version control
- ✗ Use direct HTTP access without verification
- ✗ Share API key in logs or error messages
- ✗ Make requests from client-side code
- ✗ Ignore SSL/TLS certificate warnings

---

## Integration Checklist

- [ ] API key generated at https://dash.tinfoil.sh
- [ ] Environment variable set: `export TINFOIL_API_KEY=sk-...`
- [ ] Tinfoil SDK installed: `pip install tinfoil`
- [ ] Test basic chat request works
- [ ] Test tool calling with `kimi-k2.5`
- [ ] Implement error handling
- [ ] Set up monitoring/logging
- [ ] Configure rate limiting
- [ ] Test streaming responses
- [ ] Verify pricing/billing setup

---

## Related Documentation

- Full Research: `TINFOIL_RESEARCH.md`
- Implementation Guide: `TINFOIL_IMPLEMENTATION_GUIDE.md`
- Official Docs: https://docs.tinfoil.sh
- API Reference: https://docs.tinfoil.sh/api-reference/libraries
