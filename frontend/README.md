# ohmypm Web UI

React 19 + TypeScript (strict) + Vite + Tailwind CSS v4 + shadcn/ui + TanStack Query + react-router.

```bash
pnpm install
pnpm dev          # http://127.0.0.1:5173, proxies /api and /mcp to OHMYPM_BACKEND (default http://127.0.0.1:8765)
pnpm typecheck && pnpm test && pnpm lint
pnpm build        # dist/ — served by the backend when OHMYPM_WEB_DIST points at it (the Docker image does this)
```

Structure: `src/lib` (API client, types mirroring the backend schemas, fetch-based SSE, formatting),
`src/components` (app shell, dialogs/forms, run log, shared bits; `ui/` = generated shadcn components),
`src/pages` (routes). Sign in with the server's `OHMYPM_API_TOKEN` or a `#token=` link from `ohmypm open`.
