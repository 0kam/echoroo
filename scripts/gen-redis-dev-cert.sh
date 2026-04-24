#!/bin/bash
# Generate a self-signed TLS certificate for the dev Redis container.
#
# This script is intended for local development only. It produces a short
# chain (self-signed CA + server cert signed by that CA) under
# `config/redis/tls/`, which is then mounted read-only into the Redis
# container by compose.dev.yaml.
#
# Usage:
#   ./scripts/gen-redis-dev-cert.sh              # generate if missing
#   ./scripts/gen-redis-dev-cert.sh --force      # regenerate even if present
#
# NOTE: Never reuse this certificate in production. Production deployments
# must use certificates issued by a trusted CA and provisioned via secrets
# management (SOPS / Vault / AWS Secrets Manager).

set -euo pipefail

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/config/redis/tls"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "${CERT_DIR}"

if [[ -f "${CERT_DIR}/redis.crt" && -f "${CERT_DIR}/redis.key" && -f "${CERT_DIR}/ca.crt" && ${FORCE} -eq 0 ]]; then
  echo "Dev Redis certificates already present under ${CERT_DIR} (pass --force to regenerate)"
  exit 0
fi

command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required but was not found in PATH" >&2
  exit 1
}

echo "Generating self-signed Redis dev certificate under ${CERT_DIR}"

# 1. CA key + cert
openssl genrsa -out "${CERT_DIR}/ca.key" 4096 >/dev/null 2>&1
openssl req -x509 -new -nodes \
  -key "${CERT_DIR}/ca.key" \
  -sha256 -days 3650 \
  -subj "/C=JP/ST=Dev/L=Dev/O=Echoroo/OU=Dev/CN=echoroo-dev-ca" \
  -out "${CERT_DIR}/ca.crt" >/dev/null 2>&1

# 2. Server key + CSR
openssl genrsa -out "${CERT_DIR}/redis.key" 4096 >/dev/null 2>&1
openssl req -new \
  -key "${CERT_DIR}/redis.key" \
  -subj "/C=JP/ST=Dev/L=Dev/O=Echoroo/OU=Dev/CN=redis" \
  -out "${CERT_DIR}/redis.csr" >/dev/null 2>&1

# 3. Server cert signed by CA (SAN covers docker service + localhost)
cat > "${CERT_DIR}/redis.ext" <<'EOF'
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = redis
DNS.2 = localhost
IP.1  = 127.0.0.1
EOF

openssl x509 -req \
  -in "${CERT_DIR}/redis.csr" \
  -CA "${CERT_DIR}/ca.crt" \
  -CAkey "${CERT_DIR}/ca.key" \
  -CAcreateserial \
  -out "${CERT_DIR}/redis.crt" \
  -days 825 -sha256 \
  -extfile "${CERT_DIR}/redis.ext" >/dev/null 2>&1

rm -f "${CERT_DIR}/redis.csr" "${CERT_DIR}/redis.ext" "${CERT_DIR}/ca.srl"
chmod 600 "${CERT_DIR}"/*.key

echo "Dev Redis certificate generated successfully"
