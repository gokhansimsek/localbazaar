# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=20-alpine

# ---- Base ----
FROM node:${NODE_VERSION} AS base
RUN corepack enable
WORKDIR /app

# ---- Dependencies (installed once, reused) ----
FROM base AS deps
# .npmrc holds node-linker=hoisted so node_modules has real directories instead of
# symlinks into a content-addressed store. Required for multi-stage COPY to survive.
COPY package.json pnpm-lock.yaml* .npmrc* ./
RUN --mount=type=cache,id=pnpm,target=/root/.pnpm-store \
    pnpm config set store-dir /root/.pnpm-store \
    && pnpm install --frozen-lockfile 2>/dev/null \
    || pnpm install

# ---- Dev image (used by docker-compose) ----
FROM base AS dev
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=development
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---- Builder (production) ----
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time for
# Next.js standalone output. Pass them via --build-arg.
ARG NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=""
ARG NEXT_PUBLIC_ADSENSE_CLIENT_ID=""
ARG NEXT_PUBLIC_ADSENSE_TRENDS_SLOT=""
ARG NEXT_PUBLIC_ADSENSE_CMP_ENABLED=""
ENV NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=$NEXT_PUBLIC_GOOGLE_MAPS_API_KEY \
    NEXT_PUBLIC_ADSENSE_CLIENT_ID=$NEXT_PUBLIC_ADSENSE_CLIENT_ID \
    NEXT_PUBLIC_ADSENSE_TRENDS_SLOT=$NEXT_PUBLIC_ADSENSE_TRENDS_SLOT \
    NEXT_PUBLIC_ADSENSE_CMP_ENABLED=$NEXT_PUBLIC_ADSENSE_CMP_ENABLED \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# ---- Runner (production) ----
FROM node:${NODE_VERSION} AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# next.config.mjs has output: "standalone" — copy only the standalone bundle.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
