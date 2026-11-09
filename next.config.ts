import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  output: "standalone",
  // The development toolbar overlaps the role avatar in the lower-left sidebar.
  devIndicators: false,
  experimental: {
    // System settings allow up to 1 GiB per file, plus multipart overhead.
    proxyClientMaxBodySize: "1100mb",
  },
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backendOrigin}/api/:path*` },
      { source: "/v1/:path*", destination: `${backendOrigin}/v1/:path*` },
    ];
  },
};

export default nextConfig;
