/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  eslint: {
    ignoreDuringBuilds: true,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  // API proxying is now handled by API routes in src/app/api/[...path]/route.ts
  // This allows runtime environment variable usage
};

export default nextConfig;
