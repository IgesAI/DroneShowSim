import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  transpilePackages: ['@lumina/schema', '@lumina/simulator'],
}

export default nextConfig
