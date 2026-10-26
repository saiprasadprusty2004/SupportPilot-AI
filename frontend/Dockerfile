FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
RUN addgroup -g 10001 pilot && adduser -D -u 10001 -G pilot pilot \
    && mkdir -p /config /data /srv && chown -R pilot:pilot /config /data /srv
COPY --from=build --chown=pilot:pilot /app/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile
USER pilot
EXPOSE 8080 8443
HEALTHCHECK --interval=15s --timeout=5s CMD wget -q -O /dev/null http://localhost:8080/healthz || exit 1
