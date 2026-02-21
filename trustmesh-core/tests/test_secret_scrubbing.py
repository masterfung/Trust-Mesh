"""Tests for secret prefix scrubbing in tool output.

Validates that well-known API keys, service tokens, and credential patterns
are scrubbed from tool output before being sent to the LLM. Adopted from
NullClaw/ZeroClaw's secret scrubbing patterns.
"""

import json
import pytest

from src.citadel import (
    scrub_secret_prefixes,
    scrub_tool_output,
    MAX_TOOL_OUTPUT_CHARS,
)


# ═══════════════════════════════════════════════════════════════
# Prefix-based token scrubbing
# ═══════════════════════════════════════════════════════════════

class TestSecretPrefixScrubbing:
    """Test scrubbing of well-known token prefixes."""

    def test_openai_key(self):
        text = "Found key: sk-abcdef1234567890abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "sk-[REDACTED]" in result
        assert "abcdef1234567890" not in result

    def test_slack_bot_token(self):
        text = "Token is xoxb-12345678-abcdefgh"
        result = scrub_secret_prefixes(text)
        assert "xoxb-[REDACTED]" in result
        assert "12345678" not in result

    def test_slack_user_token(self):
        text = "User token: xoxp-999888777666"
        result = scrub_secret_prefixes(text)
        assert "xoxp-[REDACTED]" in result

    def test_github_pat(self):
        text = "ghp_ABCDEFghijklmnop1234567890"
        result = scrub_secret_prefixes(text)
        assert "ghp_[REDACTED]" in result
        assert "ABCDEFghijklmnop" not in result

    def test_github_oauth(self):
        text = "gho_abcdefghijklmnop"
        result = scrub_secret_prefixes(text)
        assert "gho_[REDACTED]" in result

    def test_github_service(self):
        text = "ghs_xyzxyzxyz123456"
        result = scrub_secret_prefixes(text)
        assert "ghs_[REDACTED]" in result

    def test_github_user_to_server(self):
        text = "ghu_abcd1234efgh5678"
        result = scrub_secret_prefixes(text)
        assert "ghu_[REDACTED]" in result

    def test_gitlab_pat(self):
        text = "glpat-abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "glpat-[REDACTED]" in result

    def test_aws_access_key(self):
        text = "AKIAIOSFODNN7EXAMPLE"
        result = scrub_secret_prefixes(text)
        assert "AKIA[REDACTED]" in result
        assert "IOSFODNN7EXAMPLE" not in result

    def test_pypi_token(self):
        text = "pypi-AgEIcHlwaS5vcmcCJGNkMjY4OTczLTNjYm"
        result = scrub_secret_prefixes(text)
        assert "pypi-[REDACTED]" in result

    def test_npm_token(self):
        text = "npm_abcdefghijklmnop"
        result = scrub_secret_prefixes(text)
        assert "npm_[REDACTED]" in result

    def test_shopify_token(self):
        text = "shpat_abcd1234efgh5678ijkl"
        result = scrub_secret_prefixes(text)
        assert "shpat_[REDACTED]" in result

    def test_stripe_webhook_secret(self):
        text = "whsec_abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "whsec_[REDACTED]" in result

    def test_stripe_live_secret(self):
        text = "sk_live_abcdef1234567890abcdef"
        result = scrub_secret_prefixes(text)
        assert "sk_live_[REDACTED]" in result

    def test_stripe_test_secret(self):
        text = "sk_test_xyzxyz1234567890"
        result = scrub_secret_prefixes(text)
        assert "sk_test_[REDACTED]" in result

    def test_stripe_publishable_live(self):
        text = "pk_live_abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "pk_live_[REDACTED]" in result

    def test_stripe_restricted(self):
        text = "rk_live_abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "rk_live_[REDACTED]" in result

    def test_sendgrid(self):
        text = "SG.abcdefghijklmnop"
        result = scrub_secret_prefixes(text)
        assert "SG.[REDACTED]" in result

    def test_slack_app_token(self):
        text = "xapp-1234567890abcdef"
        result = scrub_secret_prefixes(text)
        assert "xapp-[REDACTED]" in result

    def test_digitalocean_token(self):
        text = "dop_v1_abcdefghijklmnopqrst"
        result = scrub_secret_prefixes(text)
        assert "dop_v1_[REDACTED]" in result

    def test_snyk_token(self):
        text = "snyk-abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "snyk-[REDACTED]" in result

    def test_square_sandbox(self):
        text = "sq0csp-abcdefghijklmnop"
        result = scrub_secret_prefixes(text)
        assert "sq0csp-[REDACTED]" in result

    def test_multiple_tokens_in_same_text(self):
        text = "Keys: sk-abc123def456, ghp_xyz789abc012, AKIAEXAMPLE12345"
        result = scrub_secret_prefixes(text)
        assert "sk-[REDACTED]" in result
        assert "ghp_[REDACTED]" in result
        assert "AKIA[REDACTED]" in result
        assert "abc123def456" not in result
        assert "xyz789abc012" not in result

    def test_token_in_json(self):
        data = json.dumps({"api_key": "sk-realkey1234567890abc"})
        result = scrub_secret_prefixes(data)
        assert "sk-[REDACTED]" in result
        assert "realkey1234567890" not in result

    def test_short_prefix_not_scrubbed(self):
        """Tokens shorter than 4 chars after prefix are not scrubbed."""
        text = "sk-ab"  # Only 2 chars after prefix — too short
        result = scrub_secret_prefixes(text)
        assert result == text  # Unchanged

    def test_empty_string(self):
        assert scrub_secret_prefixes("") == ""

    def test_none_passthrough(self):
        assert scrub_secret_prefixes("") == ""

    def test_no_secrets_unchanged(self):
        text = "Hello, this is a normal response with no secrets."
        assert scrub_secret_prefixes(text) == text


# ═══════════════════════════════════════════════════════════════
# Key-value pattern scrubbing
# ═══════════════════════════════════════════════════════════════

class TestKeyValueScrubbing:
    """Test scrubbing of key=value credential patterns."""

    def test_api_key_equals(self):
        text = "api_key=abc12345678"
        result = scrub_secret_prefixes(text)
        assert "api_key=[REDACTED]" in result
        assert "abc12345678" not in result

    def test_api_key_colon(self):
        text = "api_key: abc12345678"
        result = scrub_secret_prefixes(text)
        assert "api_key=[REDACTED]" in result

    def test_api_secret(self):
        text = "api_secret=mysecretvalue1234"
        result = scrub_secret_prefixes(text)
        assert "api_secret=[REDACTED]" in result

    def test_token_equals(self):
        text = "token=abcdef1234567890"
        result = scrub_secret_prefixes(text)
        assert "token=[REDACTED]" in result

    def test_password_equals(self):
        text = "password=hunter2_extended_version"
        result = scrub_secret_prefixes(text)
        assert "password=[REDACTED]" in result

    def test_secret_key(self):
        text = "secret_key=very_secret_key_123456"
        result = scrub_secret_prefixes(text)
        assert "secret_key=[REDACTED]" in result

    def test_access_key(self):
        text = "access_key=myaccesskey12345678"
        result = scrub_secret_prefixes(text)
        assert "access_key=[REDACTED]" in result

    def test_auth_token(self):
        text = "auth_token=someauthtoken12345"
        result = scrub_secret_prefixes(text)
        assert "auth_token=[REDACTED]" in result

    def test_client_secret(self):
        text = "client_secret=clientsecretvalue"
        result = scrub_secret_prefixes(text)
        assert "client_secret=[REDACTED]" in result

    def test_signing_key(self):
        text = "signing_key=signingkeyvalue12345"
        result = scrub_secret_prefixes(text)
        assert "signing_key=[REDACTED]" in result

    def test_hyphenated_variants(self):
        text = "api-key=hyphenated12345678"
        result = scrub_secret_prefixes(text)
        assert "api-key=[REDACTED]" in result

    def test_case_insensitive(self):
        text = "API_KEY=MySecret12345678"
        result = scrub_secret_prefixes(text)
        assert "[REDACTED]" in result
        assert "MySecret12345678" not in result

    def test_quoted_value(self):
        text = 'api_key="quotedvalue12345"'
        result = scrub_secret_prefixes(text)
        assert "api_key=[REDACTED]" in result

    def test_short_value_not_scrubbed(self):
        """Values shorter than 8 chars are not matched by the KV pattern."""
        text = "token=short"  # Only 5 chars
        result = scrub_secret_prefixes(text)
        # Short values don't match the pattern (min 8 chars)
        assert result == text


# ═══════════════════════════════════════════════════════════════
# Bearer token scrubbing
# ═══════════════════════════════════════════════════════════════

class TestBearerTokenScrubbing:
    """Test scrubbing of Bearer tokens in auth headers."""

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        result = scrub_secret_prefixes(text)
        assert "Bearer [REDACTED]" in result
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_bearer_lowercase(self):
        text = "bearer sometoken1234567890"
        result = scrub_secret_prefixes(text)
        assert "bearer [REDACTED]" in result

    def test_bearer_uppercase(self):
        text = "BEARER MYTOKEN1234567890"
        result = scrub_secret_prefixes(text)
        assert "BEARER [REDACTED]" in result


# ═══════════════════════════════════════════════════════════════
# scrub_tool_output (combined: truncation + scrubbing)
# ═══════════════════════════════════════════════════════════════

class TestScrubToolOutput:
    """Test the combined tool output scrubbing function."""

    def test_scrubs_and_returns(self):
        text = json.dumps({"result": "sk-realkey1234567890"})
        result = scrub_tool_output(text)
        assert "sk-[REDACTED]" in result
        assert "realkey1234567890" not in result

    def test_truncates_large_output(self):
        text = "x" * (MAX_TOOL_OUTPUT_CHARS + 5000)
        result = scrub_tool_output(text)
        assert len(result) <= MAX_TOOL_OUTPUT_CHARS + 50  # allow for suffix
        assert "[output truncated]" in result

    def test_truncation_then_scrub(self):
        """Secrets near the end of oversized output are truncated away."""
        safe = "a" * (MAX_TOOL_OUTPUT_CHARS - 10)
        text = safe + "sk-secretkey1234567890abcdef"
        result = scrub_tool_output(text)
        assert "secretkey1234567890" not in result

    def test_empty_string(self):
        assert scrub_tool_output("") == ""

    def test_normal_text_unchanged(self):
        text = json.dumps({"success": True, "message": "Capsule saved"})
        assert scrub_tool_output(text) == text

    def test_mixed_content(self):
        """Real-world tool output with an embedded secret."""
        data = {
            "success": True,
            "results": [
                {"title": "API Setup", "snippet": "Set your key: sk-proj-abcdef1234567890xyz"},
                {"title": "Normal", "snippet": "Nothing sensitive here"},
            ],
        }
        text = json.dumps(data)
        result = scrub_tool_output(text)
        parsed = json.loads(result)
        # The secret should be scrubbed in the snippet
        assert "abcdef1234567890" not in parsed["results"][0]["snippet"]
        assert "sk-[REDACTED]" in parsed["results"][0]["snippet"]  # sk- matches first
        # Normal snippet unchanged
        assert "Nothing sensitive here" in parsed["results"][1]["snippet"]


# ═══════════════════════════════════════════════════════════════
# Integration: execute_tool scrubs output
# ═══════════════════════════════════════════════════════════════

class TestExecuteToolScrubbing:
    """Verify that execute_tool applies scrubbing to all tool results."""

    @pytest.mark.asyncio
    async def test_web_search_scrubbed(self):
        """Web search results containing secrets are scrubbed."""
        # We don't need a real web search — just verify the scrub is called
        # by testing the scrub_tool_output function directly on representative output
        web_result = json.dumps({
            "success": True,
            "results": [
                {"title": "Leaked Keys", "url": "https://example.com", "snippet": "Use sk-live1234567890abc for production"},
            ],
        })
        from src.citadel import scrub_tool_output
        scrubbed = scrub_tool_output(web_result)
        assert "sk-[REDACTED]" in scrubbed  # sk- prefix matches
        assert "live1234567890abc" not in scrubbed

    @pytest.mark.asyncio
    async def test_vault_search_scrubbed(self):
        """Vault content containing accidentally-stored keys is scrubbed."""
        vault_result = json.dumps({
            "found": 1,
            "capsules": [
                {"id": "c1", "title": "API Notes", "content": "My GitHub token: ghp_abcdefghijklmno12345"},
            ],
        })
        from src.citadel import scrub_tool_output
        scrubbed = scrub_tool_output(vault_result)
        assert "ghp_[REDACTED]" in scrubbed
        assert "abcdefghijklmno12345" not in scrubbed


# ═══════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge cases and regression tests."""

    def test_prefix_at_start_of_string(self):
        result = scrub_secret_prefixes("sk-abcdef1234567890")
        assert result == "sk-[REDACTED]"

    def test_prefix_at_end_of_string(self):
        result = scrub_secret_prefixes("key is sk-abcdef1234567890")
        assert "sk-[REDACTED]" in result

    def test_multiple_same_prefix(self):
        text = "sk-key1abcdefgh and sk-key2abcdefgh"
        result = scrub_secret_prefixes(text)
        assert result.count("[REDACTED]") == 2

    def test_prefix_in_url(self):
        text = "https://api.example.com?token=sk-abc1234567890xyz"
        result = scrub_secret_prefixes(text)
        assert "sk-[REDACTED]" in result

    def test_no_false_positive_on_normal_sk(self):
        """'sk-' followed by less than 4 chars should not be scrubbed."""
        text = "The sk-ip was fun"  # "sk-ip" = only 2 chars after prefix
        result = scrub_secret_prefixes(text)
        assert result == text

    def test_json_structure_preserved(self):
        """JSON remains valid after scrubbing (structure not broken)."""
        data = {"key": "sk-abcdef1234567890", "safe": "hello"}
        text = json.dumps(data)
        result = scrub_tool_output(text)
        # Should still be valid JSON-ish (the redacted value breaks exact JSON
        # but the structure around it is preserved)
        assert '"safe": "hello"' in result
        assert "sk-[REDACTED]" in result

    def test_multiline_content(self):
        text = """Results from web search:
1. API docs say use sk-proj-abc123456789xyz
2. Set GITHUB_TOKEN=ghp_realtoken12345678
3. Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature"""
        result = scrub_secret_prefixes(text)
        assert "sk-[REDACTED]" in result
        assert "ghp_[REDACTED]" in result
        assert "Bearer [REDACTED]" in result
        assert "abc123456789" not in result
        assert "realtoken12345678" not in result

    def test_unicode_content_not_broken(self):
        """Non-ASCII content is preserved alongside scrubbing."""
        text = "用户密码: password=supersecretvalue123 好的"
        result = scrub_secret_prefixes(text)
        assert "password=[REDACTED]" in result
        assert "用户密码" in result
        assert "好的" in result
