import type { NextConfig } from 'next';

const apiHost = process.env.API_HOST || 'localhost';

const nextConfig: NextConfig = {
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `http://${apiHost}:8000/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
