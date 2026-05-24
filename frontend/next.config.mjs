/** @type {import('next').NextConfig} */
const apiProxyTarget = (
  process.env.API_PROXY_TARGET
  || process.env.NEXT_PUBLIC_API_BASE?.replace(/\/api\/?$/, "")
  || "http://127.0.0.1:8003"
).replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: [
    "127.0.0.1",
    "localhost",
  ],
  env: {
    API_PROXY_TARGET: apiProxyTarget,
  },
  webpack: (config, { isServer }) => {
    if (isServer) {
      config.output.chunkFilename = "chunks/[name].js";
    }
    return config;
  },
};

export default nextConfig;
