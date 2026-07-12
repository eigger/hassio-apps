ARG BUILD_FROM=ghcr.io/hassio-addons/base:21.0.0
ARG APP_API_IMAGE=ghcr.io/eigger/stash-api:latest
ARG APP_WEB_IMAGE=ghcr.io/eigger/stash-web:latest

# hadolint ignore=DL3006
FROM ${APP_API_IMAGE} AS app-api
# hadolint ignore=DL3006
FROM ${APP_WEB_IMAGE} AS app-web

# hadolint ignore=DL3006
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Node runtime from the published API image + app payloads
COPY --from=app-api /usr/local/bin/node /usr/local/bin/node
COPY --from=app-api /usr/local/bin/npx /usr/local/bin/npx
COPY --from=app-api /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=app-api /app /opt/app/api
COPY --from=app-web /app /opt/app/web

RUN apk add --no-cache \
    curl \
    nginx \
    openssl \
    postgresql16 \
    postgresql16-client \
    postgresql16-contrib \
    su-exec \
  && mkdir -p \
    /run/nginx \
    /run/postgresql \
    /opt/app/api/uploads \
  && chown -R nginx:nginx /run/nginx \
  && chown -R postgres:postgres /run/postgresql

COPY rootfs /

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

LABEL \
  io.hass.name="${BUILD_NAME}" \
  io.hass.description="${BUILD_DESCRIPTION}" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.type="addon" \
  io.hass.version=${BUILD_VERSION} \
  maintainer="eigger" \
  org.opencontainers.image.title="${BUILD_NAME}" \
  org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
  org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
  org.opencontainers.image.created=${BUILD_DATE} \
  org.opencontainers.image.revision=${BUILD_REF} \
  org.opencontainers.image.version=${BUILD_VERSION}
