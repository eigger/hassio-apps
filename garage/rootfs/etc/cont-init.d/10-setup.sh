#!/command/with-contenv bashio
# ==============================================================================
# Garage app: prepare persistent data, secrets, and Postgres
# ==============================================================================
set -euo pipefail

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
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
    echo "JWT_SECRET=$(openssl rand -hex 32)"
  } > "${SECRETS_FILE}"
fi

# shellcheck disable=SC1090
source "${SECRETS_FILE}"

if [[ -z "${JWT_SECRET:-}" ]]; then
  JWT_SECRET="$(openssl rand -hex 32)"
  echo "JWT_SECRET=${JWT_SECRET}" >> "${SECRETS_FILE}"
fi

# Optional integrations, same env vars as upstream's docker-compose.prod.yml.
# Left empty the API falls back to mock data (Opinet / EV chargers) and web push
# reminders stay off, so none of these are required to run the app.
OPINET_API_KEY="$(bashio::config 'opinet_api_key' '')"
EV_CHARGER_API_KEY="$(bashio::config 'ev_charger_api_key' '')"
VAPID_PUBLIC_KEY="$(bashio::config 'vapid_public_key' '')"
VAPID_PRIVATE_KEY="$(bashio::config 'vapid_private_key' '')"
VAPID_SUBJECT="$(bashio::config 'vapid_subject' '')"
if bashio::config.true 'cheonan_card_enabled'; then
  CHEONAN_CARD_ENABLED="true"
else
  CHEONAN_CARD_ENABLED=""
fi

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
OPINET_API_KEY=${OPINET_API_KEY}
CHEONAN_CARD_ENABLED=${CHEONAN_CARD_ENABLED}
EV_CHARGER_API_KEY=${EV_CHARGER_API_KEY}
VAPID_PUBLIC_KEY=${VAPID_PUBLIC_KEY}
VAPID_PRIVATE_KEY=${VAPID_PRIVATE_KEY}
VAPID_SUBJECT=${VAPID_SUBJECT}
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
