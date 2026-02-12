"""Tests for the encryption module."""

from src.crypto import (
    content_hash,
    decrypt,
    decrypt_text,
    derive_vault_key,
    encrypt,
    encrypt_text,
    generate_key,
)


def test_generate_key_length():
    key = generate_key()
    assert len(key) == 32  # AES-256


def test_encrypt_decrypt_roundtrip():
    key = generate_key()
    plaintext = b"Hello, TrustMesh!"
    ciphertext = encrypt(plaintext, key)
    assert ciphertext != plaintext
    assert decrypt(ciphertext, key) == plaintext


def test_encrypt_text_roundtrip():
    key = generate_key()
    text = "Grandma Rose's medication: Lisinopril 10mg"
    encrypted = encrypt_text(text, key)
    assert isinstance(encrypted, bytes)
    assert decrypt_text(encrypted, key) == text


def test_different_keys_cannot_decrypt():
    key1 = generate_key()
    key2 = generate_key()
    plaintext = b"Private medical records"
    ciphertext = encrypt(plaintext, key1)
    try:
        decrypt(ciphertext, key2)
        assert False, "Should have raised an error"
    except Exception:
        pass  # Expected: wrong key fails


def test_derive_vault_key_deterministic():
    password = "trustmesh-demo"
    key1, salt = derive_vault_key(password)
    key2, _ = derive_vault_key(password, salt)
    assert key1 == key2


def test_derive_vault_key_different_passwords():
    key1, salt = derive_vault_key("password1")
    key2, _ = derive_vault_key("password2", salt)
    assert key1 != key2


def test_content_hash_consistent():
    content = "Bill is lactose intolerant"
    h1 = content_hash(content)
    h2 = content_hash(content)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_content_hash_different_inputs():
    assert content_hash("hello") != content_hash("world")
