# ─────────────────────────────────────────────────────────────
# Palimpsest Web — multi-stage: node build → nginx serve
# ─────────────────────────────────────────────────────────────

FROM node:20-alpine AS builder

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci --prefer-offline --no-audit 2>/dev/null || npm install --no-audit

COPY apps/web/ ./

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_MAP_ENGINE=maplibre
ARG VITE_GOOGLE_MAP_TILES_API_KEY=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_MAP_ENGINE=${VITE_MAP_ENGINE} \
    VITE_GOOGLE_MAP_TILES_API_KEY=${VITE_GOOGLE_MAP_TILES_API_KEY}

RUN npm run build

# ── runtime ──────────────────────────────────────────────────

FROM nginx:1.27-alpine AS runtime

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/ || exit 1
