/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // production builds live in .next-prod so a running dev server (.next)
  // and a prod build can never corrupt each other
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

module.exports = nextConfig;
