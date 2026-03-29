/**
 * GET /.well-known/did.json
 *
 * Publishes the registry's did:web DID document so agents can resolve the
 * registry's identity and public key without out-of-band configuration.
 *
 * Also serves as the did:key self-description — the DID embedded here is a
 * did:key derived from the registry's ed25519 public key, which is what pods
 * actually use to verify signed responses (simpler than a full did:web resolve).
 *
 * Agent verification flow:
 *   1. Hit GET /.well-known/did.json — extract publicKeyMultibase → derive did:key
 *   2. OR use TRUSTMESH_REGISTRY_DID env var (pinned value, no fetch needed)
 *   3. On each registry API response, verify X-TrustMesh-Signature against that DID
 */

import { NextResponse } from "next/server";
import { getRegistryDid, getRegistryPublicKey } from "@/lib/registry-key";

// Base58btc encode (duplicated here to avoid server-only import in Next.js edge)
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

export function GET() {
  const did = getRegistryDid();
  const pubKey = getRegistryPublicKey();

  // multibase-encode the raw public key (z + base58btc, no multicodec — just the 32 bytes)
  const pubKeyMultibase = "z" + base58btcEncode(pubKey);

  // did:web host — derive from NEXT_PUBLIC_REGISTRY_URL or fall back to localhost
  const registryUrl = process.env.NEXT_PUBLIC_REGISTRY_URL || "http://localhost:9100";
  const host = registryUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
  // did:web uses colon-encoded paths; for root domain it's just did:web:<host>
  const didWeb = `did:web:${host.replace(/:/g, "%3A")}`;

  const document = {
    "@context": [
      "https://www.w3.org/ns/did/v1",
      "https://w3id.org/security/suites/ed25519-2020/v1",
    ],
    id: didWeb,
    // Also advertise the did:key equivalent so agents can use it without resolving did:web
    alsoKnownAs: [did],
    verificationMethod: [
      {
        id: `${didWeb}#key-1`,
        type: "Ed25519VerificationKey2020",
        controller: didWeb,
        // Raw 32-byte public key in multibase (z + base58btc, no multicodec prefix)
        publicKeyMultibase: pubKeyMultibase,
      },
    ],
    authentication: [`${didWeb}#key-1`],
    assertionMethod: [`${didWeb}#key-1`],
    service: [
      {
        id: `${didWeb}#registry`,
        type: "TrustMeshRegistry",
        serviceEndpoint: `${registryUrl}/api`,
      },
    ],
  };

  return NextResponse.json(document, {
    headers: {
      "Content-Type": "application/did+json",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
