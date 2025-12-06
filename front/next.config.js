/** @type {import('next').NextConfig} */
const nextConfig = {
  // Use standalone output for optimized Docker builds
  // This creates a minimal production bundle with all dependencies
  output: "standalone",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};
module.exports = nextConfig;
