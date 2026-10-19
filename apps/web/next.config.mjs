/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The dev-only "N" badge sits bottom-left, over the sidebar's
  // expand/collapse toggle (and a browser-saved position overrides any
  // `position` set here), so hide it. Build errors still show as an overlay.
  devIndicators: false,
};

export default nextConfig;
