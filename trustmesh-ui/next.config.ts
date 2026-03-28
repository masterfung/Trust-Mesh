import type { NextConfig } from "next";

// When running with a public tunnel (cloudflare, ngrok), set TRUSTMESH_PROXY_POD
// to the backend pod URL. Next.js will proxy all /api/* requests to it server-side,
// so the phone browser never makes cross-origin calls (CORS solved).
//
// Example:
//   TRUSTMESH_PROXY_POD=http://localhost:9004 bun dev --port 3050
const proxyPod = process.env.TRUSTMESH_PROXY_POD?.replace(/\/$/, "") ?? "";

const nextConfig: NextConfig = {
  async rewrites() {
    if (!proxyPod) return [];
    return [
      {
        // Proxy all /api/* to the backend pod — but let Next.js own API routes
        // take precedence (Next.js checks its own routes first, then rewrites).
        source: "/api/:path*",
        destination: `${proxyPod}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
