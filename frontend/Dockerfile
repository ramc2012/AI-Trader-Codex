# =============================================================================
# Nifty AI Trader — Frontend (Next.js)
# =============================================================================
# Multi-stage build: install deps, build, then serve from minimal image.

# --- Stage 1: Install dependencies ---
FROM node:20-alpine AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

# --- Stage 2: Build ---
FROM node:20-alpine AS builder

WORKDIR /app

# Accept build argument for API_HOST
ARG API_HOST=localhost
ARG NEXT_PUBLIC_API_URL=/api/v1
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/api/v1
ARG NEXT_PUBLIC_APP_NAME_BASE="AI TRADER"
ARG NEXT_PUBLIC_APP_INSTANCE_LABEL=LOCAL

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# API calls use same-origin /api/v1 proxy route in Next.js.
# WebSockets must target backend directly (Next route handlers don't proxy WS upgrades).
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_APP_NAME_BASE=$NEXT_PUBLIC_APP_NAME_BASE
ENV NEXT_PUBLIC_APP_INSTANCE_LABEL=$NEXT_PUBLIC_APP_INSTANCE_LABEL
ENV API_HOST=$API_HOST

# Build Next.js in standalone mode
RUN npm run build

# --- Stage 3: Runtime ---
FROM node:20-alpine AS runner

WORKDIR /app

# Accept build argument for API_HOST
ARG API_HOST=localhost
ARG NEXT_PUBLIC_APP_NAME_BASE="AI TRADER"
ARG NEXT_PUBLIC_APP_INSTANCE_LABEL=LOCAL

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV API_HOST=$API_HOST
ENV NEXT_PUBLIC_APP_NAME_BASE=$NEXT_PUBLIC_APP_NAME_BASE
ENV NEXT_PUBLIC_APP_INSTANCE_LABEL=$NEXT_PUBLIC_APP_INSTANCE_LABEL

# Create non-root user
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Copy built assets
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000', (r) => { process.exit(r.statusCode === 200 ? 0 : 1) }).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
