# ==============================================================================
# RouterX - Frontend Production Dockerfile
# ==============================================================================

# ── Build Stage ──
FROM oven/bun:1-alpine AS builder

WORKDIR /app

# Install dependencies using bun.lock for reproducible builds
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Copy source code
COPY . .

# Build Vite application with production optimizations
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN bun run build

# ── Production Serving Stage ──
FROM nginx:1.27-alpine AS production

# Copy built static assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

# Health check to ensure Nginx is responding
HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/nginx-health || exit 1

CMD ["nginx", "-g", "daemon off;"]
