# TrustMesh UI

Next.js 16 frontend for [TrustMesh](https://github.com/TryMightyAI/trustmesh) — a trust-aware knowledge sharing platform for personal AI agents.

## Quick start

```bash
bun install
bun dev --port 3050
```

Open [http://localhost:3050](http://localhost:3050).

The backend must be running on `:9000` (single-pod) or `:9001–9016` (multi-pod). See the root `CLAUDE.md` for full setup instructions.

## Environment variables

Create a `.env.local` file (gitignored — never committed) in this directory:

```bash
# .env.local

# Show pod selector dropdowns on /login and /signup.
# Set to "true" for local multi-pod demo; leave unset for production.
NEXT_PUBLIC_MULTI_POD=true
```

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_MULTI_POD` | _(unset)_ | Enables pod selector dropdowns on login/signup. **Never set in production.** |
| `NEXT_PUBLIC_API_URL` | _(unset)_ | Override the backend pod URL (optional). |
| `NEXT_PUBLIC_REGISTRY_URL` | _(unset)_ | Override the registry URL (optional). |

### Production deployment

Leave `NEXT_PUBLIC_MULTI_POD` unset (or `false`). Pod selection dropdowns will not render — users connect to a single pod determined by the server they visit. No multi-pod scaffolding reaches the browser bundle.

## Multi-pod demo

When running the full multi-pod demo (`./multi-pod.sh demo` from the repo root), set `NEXT_PUBLIC_MULTI_POD=true` in `.env.local` to unlock the pod switcher on login and signup.

Demo pods run on `:9001–9016`. Port `:9000` is seeded with the **Johnny Hung** demo account and is intentionally excluded from the signup dropdown (login still works).

## Tests

```bash
bun run test:e2e      # Playwright E2E (requires pods + frontend running)
```

E2E tests require `NEXT_PUBLIC_MULTI_POD=true` in `.env.local` — the pod selector auth helper depends on it.

## Stack

- **Next.js 16** — App Router, Server Components
- **Tailwind CSS** — Dark-mode design system
- **TanStack Query** — Server state + mutations
- **Playwright** — E2E tests
- **D3.js** — Trust graph visualization
