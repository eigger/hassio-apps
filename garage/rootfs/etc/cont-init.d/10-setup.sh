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
