# Deploy Tomo

Tomo uses Cloudflare Pages for the static website and Railway for the FastAPI
service. Keep Railway Serverless **off** so the API responds on the first visit.
The public demo uses `AI_MODE=demo`; it needs no paid LLM key. Sign-in uses Clerk.
The website and API deploy from the same GitHub branch.

## Before switching the public site

1. In the existing Clerk app, create a **Production** instance for
   `tomoplanner.app`. Enable the sign-in methods you want to offer. Clerk's
   **API Keys** page contains the production Publishable Key (`pk_live_...`)
   and JWT public key. The backend verifies tokens with the public key, so it
   does not need a Clerk Secret Key. Name the Clerk application **Tomo** so
   authentication emails and provider prompts use the right name.
2. Keep the current Railway `/data` volume. The old shared demo database may
   stay on that volume; new private workspaces use `/data/workspaces`. Existing
   shared sample data is not moved into users' accounts.
3. Generate a long random shared secret, for example with
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Put the same
   value in Railway and Cloudflare as described below. Never commit it.

## Railway API

In the existing backend service, keep the root directory `/backend`, the
persistent volume mounted at `/data`, the public HTTPS domain and `/health`
health check. Set these service variables:

| Variable | Value |
| --- | --- |
| `WORKSPACE_ROOT` | `/data/workspaces` |
| `AI_MODE` | `demo` |
| `CLERK_JWT_KEY` | Clerk JWT public key, including PEM header/footer; `\n` may represent line breaks |
| `CLERK_AUTHORIZED_PARTIES` | `https://tomoplanner.app` |
| `PROXY_SHARED_SECRET` | The generated shared secret |

`DATABASE_URL` and `SEED_ON_START` are ignored in workspace mode. At startup,
the container prepares one sample plan; each demo visitor receives a quick,
separate copy. Signed-in users start with an empty private planner. The API
refuses direct public requests without the Cloudflare proxy secret.

Leave **Settings → Deploy → Serverless** disabled. Set a usage alert in Railway.
Railway can charge beyond the plan's included usage; check the current price
and limits in your Railway account.

## Cloudflare Pages

In the existing Pages project, keep the root directory `/frontend`, build
command `STATIC_EXPORT=true npm run build`, and output directory `out`. Set:

| Variable | Value | Scope |
| --- | --- | --- |
| `API_BASE_URL` | Railway HTTPS origin, without `/api` or trailing slash | Pages runtime |
| `PROXY_SHARED_SECRET` | The same generated secret as Railway | Pages runtime, encrypted |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk Production Publishable Key (`pk_live_...`) | Build |

Set them for **Production**. Preview builds need matching development Clerk
keys and an authorized preview origin, so leave preview deployments private
until configured. Trigger a new deployment after changing build variables.

Open `https://tomoplanner.app`, choose **Try the demo**, change something,
then open an incognito window and confirm the first visitor's changes are not
there. Next, create an account, sign out, sign back in and confirm its data
persists. Check `/health` on Railway separately. A direct request to
`/api/goals` on the Railway domain should return 403.

Pushing to the connected GitHub production branch triggers both deployments.
Review Railway and Cloudflare build logs, then run the checks above after each
release. The domain renewal is a separate annual cost.
