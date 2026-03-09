import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  // API proxying is now handled by API routes in src/app/api/[...path]/route.ts
  // This allows runtime environment variable usage
};

export default nextConfig;
