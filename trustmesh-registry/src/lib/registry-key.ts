/**
 * Registry identity keypair + DID management.
 *
 * The registry signs its API responses so agents can verify they are talking
 * to the legitimate registry.  The keypair is loaded from REGISTRY_PRIVATE_KEY
 * (base64url-encoded raw 32-byte ed25519 seed).  On first run without that env
 * var the module generates a fresh keypair, logs it, and runs in-memory only —
 * set REGISTRY_PRIVATE_KEY to persist the identity across restarts.
 *
 * The registry's DID is a did:key derived from the public key, e.g.:
 *   did:key:z6Mk...
 *
 * Agents configure TRUSTMESH_REGISTRY_DID to this value so they can verify
 * responses without a live DID-document fetch.
 */

import * as ed25519 from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2";

// Configure sha512 sync (required for sync sign/verify in @noble/ed25519 ≥2)
ed25519.etc.sha512Sync = (...msgs: Uint8Array[]) => {
  const h = sha512.create();
  for (const m of msgs) h.update(m);
  return h.digest();
};

// Base58btc alphabet
const B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

function base58btcEncode(bytes: Uint8Array): string {
  let num = BigInt(0);
  for (const b of bytes) num = num * 256n + BigInt(b);
  let result = "";
  while (num > 0n) {
    result = B58[Number(num % 58n)] + result;
    num = num / 58n;
  }
  for (const b of bytes) {
    if (b !== 0) break;
    result = "1" + result;
  }
  return result;
}

function b64urlDecode(s: string): Uint8Array {
  let padded = s;
  const rem = padded.length % 4;
  if (rem === 2) padded += "==";
  else if (rem === 3) padded += "=";
  const bin = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function b64urlEncode(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

function publicKeyToDid(pubKey: Uint8Array): string {
  // ed25519-pub multicodec prefix: 0xed 0x01
  const multicodec = new Uint8Array(2 + pubKey.length);
  multicodec[0] = 0xed;
  multicodec[1] = 0x01;
  multicodec.set(pubKey, 2);
  return `did:key:z${base58btcEncode(multicodec)}`;
}

interface RegistryKeypair {
  privateKey: Uint8Array; // 32-byte seed
  publicKey: Uint8Array;  // 32-byte public key
  did: string;            // did:key:z...
}

function generateKeypair(): RegistryKeypair {
  const privateKey = crypto.getRandomValues(new Uint8Array(32));
  const publicKey = ed25519.getPublicKey(privateKey);
  const did = publicKeyToDid(publicKey);
  return { privateKey, publicKey, did };
}

function loadKeypair(): RegistryKeypair {
  const envKey = process.env.REGISTRY_PRIVATE_KEY;
  if (envKey) {
    try {
      const privateKey = b64urlDecode(envKey);
      if (privateKey.length !== 32) throw new Error("REGISTRY_PRIVATE_KEY must be 32 bytes");
      const publicKey = ed25519.getPublicKey(privateKey);
      const did = publicKeyToDid(publicKey);
      return { privateKey, publicKey, did };
    } catch (e) {
      console.error("[registry-key] Failed to load REGISTRY_PRIVATE_KEY:", e);
      console.error("[registry-key] Falling back to ephemeral keypair");
    }
  }
  const kp = generateKeypair();
  const privB64 = b64urlEncode(kp.privateKey);
  console.warn("[registry-key] No REGISTRY_PRIVATE_KEY set — using ephemeral keypair.");
  console.warn("[registry-key] To persist registry identity, set:");
  console.warn(`[registry-key]   REGISTRY_PRIVATE_KEY=${privB64}`);
  console.warn(`[registry-key] Registry DID: ${kp.did}`);
  return kp;
}

// Singleton — loaded once at module init
const _kp: RegistryKeypair = loadKeypair();

export function getRegistryDid(): string {
  return _kp.did;
}

export function getRegistryPublicKey(): Uint8Array {
  return _kp.publicKey;
}

/**
 * Sign a response body and return TrustMesh signature headers.
 * Mirrors sign_federation_request() in federation_auth.py.
 */
export function signRegistryResponse(body: Uint8Array): Record<string, string> {
  const ts = Math.floor(Date.now() / 1000);
  const nonce = b64urlEncode(crypto.getRandomValues(new Uint8Array(18)));

  const prefix = new TextEncoder().encode(`${ts}\n${nonce}\n`);
  const message = new Uint8Array(prefix.length + body.length);
  message.set(prefix);
  message.set(body, prefix.length);

  const sig = ed25519.sign(message, _kp.privateKey);

  return {
    "X-TrustMesh-Timestamp": String(ts),
    "X-TrustMesh-Nonce": nonce,
    "X-TrustMesh-Signature": b64urlEncode(sig),
    "X-TrustMesh-Signature-Alg": "ed25519",
    "X-TrustMesh-Registry-DID": _kp.did,
  };
}
