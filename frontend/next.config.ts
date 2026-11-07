import type { NextConfig } from "next";

const staticExport = process.env.STATIC_EXPORT === "true";
const config: NextConfig = {
  ...(staticExport ? { output: "export" as const } : {}),
  // The /api proxy gives up after 30 s by default; planning with a reasoning model and reviewing
  // the result can take longer, so match the client's 300 s chat timeout.
  experimental: { proxyTimeout: 300_000 },
  ...(staticExport ? {} : {
    async rewrites() {
      return [{ source: "/api/:path*", destination: `${process.env.API_BASE_URL || "http://127.0.0.1:8000"}/api/:path*` }];
    },
  }),
};
export default config;
