# Refract web — Next.js. Build context = repo root.
# The browser talks to the API directly, so NEXT_PUBLIC_API_BASE is baked at build
# time. Default suits same-host access; for a remote host pass
#   --build-arg NEXT_PUBLIC_API_BASE=http://<host-ip>:8000
# syntax=docker/dockerfile:1

# ---- build ----
FROM node:20-bookworm-slim AS builder
WORKDIR /app

# Install deps against the lockfile (only the two real npm workspaces are needed).
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/workflow-graph/package.json packages/workflow-graph/package.json
RUN npm ci

# Source + build
COPY packages/workflow-graph packages/workflow-graph
COPY apps/web apps/web
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace @refract/web

# ---- run ----
FROM node:20-bookworm-slim AS runner
WORKDIR /app/apps/web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/node_modules /app/node_modules
COPY --from=builder /app/package.json /app/package.json
COPY --from=builder /app/apps/web/package.json ./package.json
COPY --from=builder /app/apps/web/next.config.mjs ./next.config.mjs
COPY --from=builder /app/apps/web/.next ./.next
# public/ is optional — copy if present (kept out of the image otherwise)

EXPOSE 3000
CMD ["npm", "run", "start"]
