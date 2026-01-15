/** @type {import('next').NextConfig} */
const nextConfig = {
  // Use standalone output for optimized Docker builds
  // This creates a minimal production bundle with all dependencies
  output: "standalone",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  // Proxy API requests to backend server
  // This allows frontend to use relative paths like /api/v1/...
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_HOST || "http://localhost:5000";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};
module.exports = nextConfig;
