# ─────────────────────────────────────────────────────────────
# Palimpsest Web — multi-stage: node build → nginx serve
# ─────────────────────────────────────────────────────────────

FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline --no-audit 2>/dev/null || npm install --no-audit --legacy-peer-deps

COPY . ./

# Default to the relative /api path so the nginx proxy in this same image
# handles routing to the api service. The published image then works for any
# user running docker compose -f docker-compose.prod.yml up, regardless of host.
# (Dev compose still passes http://localhost:8000 via .env.)
ARG VITE_API_BASE_URL=/api
ARG VITE_MAP_ENGINE=maplibre
ARG VITE_GOOGLE_MAP_TILES_API_KEY=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_MAP_ENGINE=${VITE_MAP_ENGINE} \
    VITE_GOOGLE_MAP_TILES_API_KEY=${VITE_GOOGLE_MAP_TILES_API_KEY}

RUN npm run build

# ── runtime ──────────────────────────────────────────────────

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1
