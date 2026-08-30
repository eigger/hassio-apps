#!/command/with-contenv bashio
# ==============================================================================
# Garage app: prepare persistent data, secrets, and Postgres
# ==============================================================================
set -euo pipefail

# The add-on base image pins libcrypto3/libssl3 to its own snapshot, so pulling the
# openssl package in fails to resolve against the current Alpine index. Random bytes
# were the only thing it was used for, and busybox's od covers that.
rand_hex() {
  od -An -N "${1}" -tx1 /dev/urandom | tr -d ' \n'
}

bashio::log.info "Preparing Garage data directories"

mkdir -p /data/postgres /data/uploads /data/secrets
chown -R postgres:postgres /data/postgres
chmod 700 /data/postgres

SECRETS_FILE=/data/secrets/env

if [[ ! -f "${SECRETS_FILE}" ]]; then
  bashio::log.info "Generating initial secrets"
  umask 077
  {
    echo "POSTGRES_USER=garage"
    echo "POSTGRES_DB=garage"
    echo "POSTGRES_PASSWORD=$(rand_hex 16)"
    echo "JWT_SECRET=$(rand_hex 32)"
  } > "${SECRETS_FILE}"
fi

# shellcheck disable=SC1090
source "${SECRETS_FILE}"

if [[ -z "${JWT_SECRET:-}" ]]; then
  JWT_SECRET="$(rand_hex 32)"
  echo "JWT_SECRET=${JWT_SECRET}" >> "${SECRETS_FILE}"
fi

# Home Assistant serves Ingress at /api/hassio_ingress/<token>/, and the token is handed
# out per installation — so the web app's base path can only be settled here, at start-up.
# Asking the Supervisor directly (rather than through bashio) keeps this working across
# the addon/app helper rename in bashio.
supervisor_ingress_entry() {
  local endpoint
  for endpoint in addons apps; do
    curl -fsSL -H "Authorization: Bearer ${SUPERVISOR_TOKEN:-}" \
      "http://supervisor/${endpoint}/self/info" 2>/dev/null \
      | jq -r '.data.ingress_entry // empty' \
      | grep . && return 0
  done
  return 1
}

INGRESS_PATH="$(supervisor_ingress_entry || true)"
if [[ -z "${INGRESS_PATH}" ]]; then
  bashio::log.warning "Could not read the Ingress entry from the Supervisor"
  bashio::log.warning "Serving from the root path — Ingress will not render, use the host port"
else
  bashio::log.info "Ingress entry: ${INGRESS_PATH}"
fi

# nginx has to know the prefix too: Ingress arrives with it stripped, while a browser on
# the host port asks for the prefixed URLs the page carries. Fold both into one shape.
if [[ -n "${INGRESS_PATH}" ]]; then
  STRIP_RULES="rewrite ^${INGRESS_PATH}\$ / last; rewrite ^${INGRESS_PATH}(/.*)\$ \$1 last;"
else
  STRIP_RULES=""
fi

sed -e "s|%%INGRESS_PATH%%|${INGRESS_PATH}|g" \
    -e "s|%%STRIP_INGRESS_PREFIX%%|${STRIP_RULES}|g" \
    /etc/nginx/nginx.conf.template > /etc/nginx/nginx.conf

RUNTIME_ENV=/data/secrets/runtime.env
umask 077
cat > "${RUNTIME_ENV}" <<EOF
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_DB=${POSTGRES_DB}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
JWT_SECRET=${JWT_SECRET}
DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}
NODE_ENV=production
PORT=8080
BASE_PATH=${INGRESS_PATH}
EOF

mkdir -p /var/run/s6/container_environment
while IFS='=' read -r key value; do
  [[ -z "${key}" || "${key}" =~ ^# ]] && continue
  printf '%s' "${value}" > "/var/run/s6/container_environment/${key}"
done < "${RUNTIME_ENV}"

if [[ ! -f /data/postgres/PG_VERSION ]]; then
  bashio::log.info "Initializing PostgreSQL data directory"
  su-exec postgres initdb -D /data/postgres --auth-local=trust --auth-host=scram-sha-256 --encoding=UTF8

  cat >> /data/postgres/postgresql.conf <<'EOF'
listen_addresses = '127.0.0.1'
port = 5432
unix_socket_directories = '/run/postgresql'
EOF

  cat > /data/postgres/pg_hba.conf <<'EOF'
local   all             all                                     trust
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
EOF
fi

bashio::log.info "Setup complete"
