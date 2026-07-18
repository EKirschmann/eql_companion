/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // NEXT_EXPORT=1 produces a static ./out for the single-process / exe build
  ...(process.env.NEXT_EXPORT ? { output: "export" } : {}),
  // production builds live in .next-prod so a running dev server (.next)
  // and a prod build can never corrupt each other
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

module.exports = nextConfig;
