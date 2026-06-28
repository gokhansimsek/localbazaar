/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  // Same-origin proxy: the browser only ever talks to /api on this host.
  // Next.js forwards each call to the internal API service, which is not
  // exposed to the public internet. API_INTERNAL_URL is read at server start.
  async rewrites() {
    const upstream = (process.env.API_INTERNAL_URL ?? "http://api:8000").replace(/\/$/, "");
    return [{ source: "/api/:path*", destination: `${upstream}/api/:path*` }];
  },
};

export default nextConfig;
