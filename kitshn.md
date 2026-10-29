# kitshn

This repository deploys with [kitshn 2](https://kit.yarden-zamir.com).

- `kitshn.config.ts` names the app and its deploys: a Compose app on a machine labelled `docker`.
- `.github/workflows/kitshn.yml` calls `kitshn2-deploy.yml`. It signs in to kitshn with GitHub OIDC, so the repo needs no deploy secrets.
- A push to `main` deploys `prod` at `riffle.yarden-zamir.com`. Each pull request deploys a `pr-<number>` preview at `riffle-pr-<number>.yarden-zamir.com`, and kitshn removes it when the pull request closes.
- GitHub secrets and variables named `KITSHN_<NAME>` reach the app as `<NAME>`.

## This app

- Services: `app` (FastAPI and the built frontend) and `router` (Caddy on the kitshn socket, in the place of the KitSHn 1 host Caddy). The `github-auth` Compose profile adds `oauth2-proxy`.
- `app` keeps DuckDB at `/data/riffle.duckdb`, from `${KITSHN_DATA_DIR}/data`. Run one container with one Uvicorn worker only.
- Variables: `KITSHN_COMPOSE_PROFILES`, `KITSHN_RIFFLE_AUTH_ENABLED`, `KITSHN_OAUTH2_PROXY_CLIENT_ID`, and optional `KITSHN_RIFFLE_PUBLIC_ORIGIN`, `KITSHN_RIFFLE_CORS_ORIGINS`.
- Secrets: `KITSHN_OAUTH2_PROXY_CLIENT_SECRET`, `KITSHN_OAUTH2_PROXY_COOKIE_SECRET` (URL-safe base64).
- Prod login needs both `COMPOSE_PROFILES=github-auth` and `RIFFLE_AUTH_ENABLED=true`. Previews run without login by default.
- Sign-in uses the GitHub App `riffle-yarden-zamir`, made through the manifest flow. Its callback URL is `https://riffle.yarden-zamir.com/auth/callback`, and it has the account permission Email addresses: read, which oauth2-proxy needs.
- Turn off "Expire user authorization tokens" in the GitHub App settings. The proxy never refreshes a token (`--cookie-refresh=0`), and the app checks each token against GitHub `/user`. With expiring tokens, readers sign in again after 8 hours.
- `changelorg.yarden-zamir.com`, the old name, is a kitshn redirect address of this card: a 308 to the same path on `riffle.yarden-zamir.com`.
- The proxy session cookie lasts 30 days. The router removes client `Authorization` headers only on `/auth/*`, so agent tokens reach the app and never reach oauth2-proxy.
- Agent approval needs GitHub sign-in. A preview without login cannot approve agents.
- The news site syncs reader state from the browser. It has two hosts, `https://news.yarden-zamir.com` and `https://the-riffle.yarden-zamir.com`. `compose.yml` puts both in the default of `RIFFLE_CORS_ORIGINS`, and lets oauth2-proxy redirect to them (`--whitelist-domain`). A `KITSHN_RIFFLE_CORS_ORIGINS` value replaces that default, so it must list both news origins too.
