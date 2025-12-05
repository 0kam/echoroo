/** @type {import('next').NextConfig} */
const nextConfig = {
  // output: "export", // Disabled for dynamic routes support
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};
module.exports = nextConfig;
