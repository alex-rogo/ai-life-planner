export async function onRequest({ request, env }) {
  if (!env.API_BASE_URL) {
    return new Response("API_BASE_URL is not configured", { status: 502 });
  }
  const incoming = new URL(request.url);
  const target = new URL(incoming.pathname + incoming.search, env.API_BASE_URL);
  return fetch(new Request(target, request));
}
