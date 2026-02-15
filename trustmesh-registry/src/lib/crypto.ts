import * as ed25519 from "@noble/ed25519";
import { sha512 } from "@noble/hashes/sha2";

// Configure noble/ed25519 to use sha512 (required for sync verify)
ed25519.etc.sha512Sync = (...msgs: Uint8Array[]) => {
  const h = sha512.create();
  for (const m of msgs) h.update(m);
  return h.digest();
};

// Base58btc alphabet (same as used in Python crypto.py)
const B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

// ed25519-pub multicodec prefix: 0xed 0x01
const ED25519_MULTICODEC_PREFIX = new Uint8Array([0xed, 0x01]);

function base58btcDecode(s: string): Uint8Array {
  if (!s) return new Uint8Array(0);

  let num = BigInt(0);
  for (const ch of s) {
    const idx = B58_ALPHABET.indexOf(ch);
    if (idx === -1) throw new Error(`Invalid base58btc character: ${ch}`);
    num = num * 58n + BigInt(idx);
  }

  // Convert bigint to bytes (big endian)
  const hexStr = num === 0n ? "" : num.toString(16).padStart(
    num.toString(16).length + (num.toString(16).length % 2), "0",
  );
  const rawBytes = hexStr ? new Uint8Array(
    hexStr.match(/.{2}/g)!.map((b) => parseInt(b, 16)),
  ) : new Uint8Array(0);

  // Count leading '1's (representing leading zero bytes)
  let pad = 0;
  for (const ch of s) {
    if (ch === "1") pad++;
    else break;
  }

  const result = new Uint8Array(pad + rawBytes.length);
  result.set(rawBytes, pad);
  return result;
}

/**
 * Extract raw 32-byte ed25519 public key from a did:key identifier.
 * Mirrors crypto.py:did_key_to_public_key().
 */
export function didKeyToPublicKey(did: string): Uint8Array {
  const prefix = "did:key:z";
  if (!did || !did.startsWith(prefix)) {
    throw new Error("Unsupported DID format (expected did:key:z...)");
  }

  const multicodec = base58btcDecode(did.slice(prefix.length));

  if (
    multicodec.length < ED25519_MULTICODEC_PREFIX.length ||
    multicodec[0] !== ED25519_MULTICODEC_PREFIX[0] ||
    multicodec[1] !== ED25519_MULTICODEC_PREFIX[1]
  ) {
    throw new Error("Unsupported did:key multicodec (expected ed25519-pub)");
  }

  const pub = multicodec.slice(ED25519_MULTICODEC_PREFIX.length);
  if (pub.length !== 32) {
    throw new Error("Invalid ed25519 public key length in DID");
  }
  return pub;
}

function base64urlDecode(s: string): Uint8Array {
  // Add padding if needed
  let padded = s;
  const remainder = padded.length % 4;
  if (remainder === 2) padded += "==";
  else if (remainder === 3) padded += "=";

  const binaryString = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

/**
 * Verify a federation-style signed request.
 * Same protocol as federation_auth.py:verify_federation_request().
 *
 * Signing scheme: the sender signs "<timestamp>\n<nonce>\n" + raw body bytes
 * using their ed25519 private key. We extract the public key from the DID
 * to verify.
 */
export function verifyRegistration(
  did: string,
  body: Uint8Array,
  headers: Record<string, string | undefined>,
): { valid: boolean; status: "valid" | "invalid" | "missing"; reason?: string } {
  const timestamp = headers["x-trustmesh-timestamp"];
  const nonce = headers["x-trustmesh-nonce"];
  const signature = headers["x-trustmesh-signature"];

  // No signature headers → unsigned (backward compatible)
  if (!timestamp && !nonce && !signature) {
    return { valid: false, status: "missing" };
  }

  // Partial headers → invalid
  if (!timestamp) return { valid: false, status: "invalid", reason: "Missing X-TrustMesh-Timestamp" };
  if (!nonce) return { valid: false, status: "invalid", reason: "Missing X-TrustMesh-Nonce" };
  if (!signature) return { valid: false, status: "invalid", reason: "Missing X-TrustMesh-Signature" };

  const ts = parseInt(timestamp, 10);
  if (isNaN(ts) || ts <= 0) {
    return { valid: false, status: "invalid", reason: "Invalid timestamp" };
  }

  // Check timestamp within 5 minutes
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - ts) > 300) {
    return { valid: false, status: "invalid", reason: "Timestamp outside allowed window" };
  }

  try {
    const publicKey = didKeyToPublicKey(did);
    const sigBytes = base64urlDecode(signature);
    if (sigBytes.length !== 64) {
      return { valid: false, status: "invalid", reason: "Invalid signature length" };
    }

    // Reconstruct signed message: "<ts>\n<nonce>\n" + body
    const prefix = new TextEncoder().encode(`${ts}\n${nonce}\n`);
    const message = new Uint8Array(prefix.length + body.length);
    message.set(prefix);
    message.set(body, prefix.length);

    const isValid = ed25519.verify(sigBytes, message, publicKey) as boolean;
    if (isValid) {
      return { valid: true, status: "valid" };
    }
    return { valid: false, status: "invalid", reason: "Invalid signature" };
  } catch (e) {
    return { valid: false, status: "invalid", reason: `Verification error: ${e}` };
  }
}
