# Deploy Tomo

Use Cloudflare Pages for the static Next.js frontend and Railway Hobby for the
FastAPI backend. Railway's optional Serverless setting must stay **off** so the
API does not sleep. The public demo uses `AI_MODE=demo`, so no paid LLM key is
needed. Both services deploy from the same GitHub production branch.

## Railway API

1. Create a Railway project from the GitHub repository. Select the production
   branch and set the service root directory to `/backend`. Railway should find
   `backend/Dockerfile` in that directory.
2. Choose Hobby. Add a small persistent volume mounted at `/data`.
3. Set runtime variables:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | `sqlite:////data/tomo-demo.db` |
   | `AI_MODE` | `demo` |
   | `SEED_ON_START` | `true` |

4. Generate a public HTTPS domain for the service and set the health check path
   to `/health`. Confirm the URL returns `{"status":"ok"}`. Save the origin URL
   without a trailing slash.
5. Leave **Settings → Deploy → Serverless** disabled. In **Workspace Usage**,
   set a compute usage alert. Railway Hobby costs at least $5/month, with the
   first $5 of usage included. Usage above $5 costs extra; a $5 hard limit
   prevents extra compute charges by taking the API offline.

The container runs migrations and adds sample data at startup when the database
is empty. The volume keeps data across redeploys. This is a shared public demo
without login; do not add private calendar URLs or API keys.

## Cloudflare Pages frontend

1. In **Workers & Pages**, create a Pages project from the same GitHub repo.
   Select the same production branch and set the root directory to `/frontend`.
2. Use the **Next.js (Static HTML Export)** preset. Set the build command to
   `STATIC_EXPORT=true npm run build` and output directory to `out`.
3. Set the environment variable `API_BASE_URL` to the Railway HTTPS origin,
   without `/api` or a trailing slash. Set it for Production and Preview if you
   want both environments to work.
4. Deploy. Open the assigned `*.pages.dev` URL and check `/api/system` on that
   domain. Cloudflare Pages Functions proxies `/api/*` to Railway, so browser
   requests stay on the same origin.

Pushing updates to the connected GitHub branch triggers both platform builds.
The repository's GitHub Actions checks run separately; review their result
before treating a deployment as ready.

## Custom domain

The `*.pages.dev` URL is free. When the demo is working, buy a domain and add it
under the Pages project's **Custom domains** settings. Follow Cloudflare's DNS
instructions. A domain has an annual registration fee even if hosting is free.
