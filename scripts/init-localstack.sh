#!/bin/bash
# LocalStack dev bootstrap script.
#
# Responsibilities:
#   1. Provision the default S3 bucket used by the API / workers.
#   2. Apply permissive CORS for browser-based presigned uploads.
#   3. Provision KMS Customer Master Keys (CMKs) + aliases used by the
#      006-permissions-redesign feature (per research.md §1 key isolation).
#
# The script is expected to be idempotent — re-running it on an existing
# LocalStack instance must not error out. Each resource is guarded by an
# existence check before creation.
#
# It runs in two contexts:
#   * inside the LocalStack container as a ready.d hook
#     (/etc/localstack/init/ready.d/init-s3.sh) — re-executed on EVERY
#     container start;
#   * on the GitHub e2e runner host (bash scripts/init-localstack.sh with
#     AWS_ENDPOINT_URL pointing at the LocalStack service container).
# Both contexts provide bash, awslocal, openssl and base64 — do not add
# other dependencies (python `cryptography` is NOT importable via the
# container's system python3).

set -euo pipefail

# ---------------------------------------------------------------------------
# S3 bucket
# ---------------------------------------------------------------------------

# Create the default S3 bucket for development (idempotent)
if awslocal s3api head-bucket --bucket echoroo >/dev/null 2>&1; then
  echo "Bucket 'echoroo' already exists, skipping create"
else
  awslocal s3 mb s3://echoroo
  echo "Bucket 'echoroo' created successfully"
fi

# Configure CORS on the bucket for browser-based uploads via presigned URLs
awslocal s3api put-bucket-cors --bucket echoroo --cors-configuration '{
  "CORSRules": [
    {
      "AllowedOrigins": ["http://localhost:5173", "http://localhost:3000"],
      "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag", "x-amz-version-id"],
      "MaxAgeSeconds": 3600
    }
  ]
}'
echo "CORS configuration applied to bucket 'echoroo'"

# ---------------------------------------------------------------------------
# KMS CMKs + aliases (006-permissions-redesign)
# ---------------------------------------------------------------------------
#
# Four isolated keys are required. Each alias maps to a distinct CMK so that
# a compromise of one key does not affect the others (defence-in-depth).
#
#   1) alias/echoroo-totp-dek           — wraps TOTP data encryption keys
#                                         (FR-051, FR-066). Used via
#                                         kms:GenerateDataKey / kms:Decrypt.
#   2) alias/echoroo-invitation-hmac    — signs invitation tokens via
#                                         kms:GenerateMac (FR-052). Supports
#                                         k_old/k_new dual-key rotation —
#                                         additional aliases may be
#                                         provisioned at rotation time.
#   3) alias/echoroo-pii-hash-hmac      — keyed HMAC for PII hashing
#                                         (FR-091, FR-091b). Must be used
#                                         only via kms:GenerateMac so the
#                                         raw key never leaves KMS.
#   4) alias/echoroo-audit-chain-hmac   — keyed HMAC for audit log chain
#                                         hashing (FR-092). Provides tamper
#                                         evidence for the audit trail.
#
# PERSISTENCE ACROSS RESTARTS (dev-only design):
#
# LocalStack Community silently ignores PERSISTENCE=1, so a plain
# `kms create-key` produces a NEW random key id + random key material on
# every container start. That invalidates every TOTP DEK ciphertext, PII
# hash MAC and audit-chain MAC in the dev database (IncorrectKeyException
# on login, etc.). To make dev keys survive restarts, each CMK is created
# with:
#
#   * a FIXED key id — LocalStack assigns the exact UUID passed via the
#     magic `_custom_id_` tag (the id must be UUID-format; symmetric
#     ciphertexts embed the key id, so a stable id is mandatory);
#   * FIXED key material — the key is created with --origin EXTERNAL and
#     32 bytes of deterministic material are imported via the standard
#     RSAES_OAEP_SHA_256 import flow (wrapped with openssl).
#
# Same id + same material on every run → previously produced ciphertexts
# and MACs remain valid across LocalStack restarts.
#
# SECURITY NOTE: the key material below is derived from a plaintext seed
# committed to the repository. This is intentionally DEV-ONLY fake material.
# Production uses real AWS KMS CMKs and never runs this script.
#
# Env var overrides (quickstart.md §1) are respected so operators can
# customise alias names / key ids / material seed per environment.

ECHOROO_KMS_TOTP_DEK_ALIAS="${AWS_KMS_CMK_2FA_ALIAS:-alias/echoroo-totp-dek}"
ECHOROO_KMS_INVITATION_HMAC_ALIAS="${AWS_KMS_CMK_INVITATION_HMAC_ALIAS:-alias/echoroo-invitation-hmac}"
ECHOROO_KMS_PII_HASH_ALIAS="${AWS_KMS_CMK_PII_HASH_ALIAS:-alias/echoroo-pii-hash-hmac}"
ECHOROO_KMS_AUDIT_CHAIN_ALIAS="${AWS_KMS_CMK_AUDIT_CHAIN_ALIAS:-alias/echoroo-audit-chain-hmac}"

# Fixed dev key ids (must be UUID-format — LocalStack constraint).
ECHOROO_KMS_TOTP_DEK_KEY_ID="${ECHOROO_KMS_TOTP_DEK_KEY_ID:-f0a0d0e0-0000-4000-8000-000000000001}"
ECHOROO_KMS_INVITATION_HMAC_KEY_ID="${ECHOROO_KMS_INVITATION_HMAC_KEY_ID:-f0a0d0e0-0000-4000-8000-000000000002}"
ECHOROO_KMS_PII_HASH_KEY_ID="${ECHOROO_KMS_PII_HASH_KEY_ID:-f0a0d0e0-0000-4000-8000-000000000003}"
ECHOROO_KMS_AUDIT_CHAIN_KEY_ID="${ECHOROO_KMS_AUDIT_CHAIN_KEY_ID:-f0a0d0e0-0000-4000-8000-000000000004}"

# Seed for the deterministic dev key material (32 bytes per key derived as
# sha256("<seed>:<alias-name>")). Changing the seed invalidates all existing
# dev ciphertexts/MACs — treat it like a dev-database reset.
ECHOROO_KMS_DEV_MATERIAL_SEED="${ECHOROO_KMS_DEV_MATERIAL_SEED:-echoroo-dev-kms-fixed-material-v1}"

# Scratch space for the openssl import flow, cleaned up on exit.
KMS_TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${KMS_TMP_DIR}"' EXIT

# import_key_material <key-id> <alias-name>
#   Imports 32 bytes of deterministic dev material into an EXTERNAL-origin
#   CMK sitting in PendingImport state. Wrapping is done with openssl
#   (RSAES_OAEP_SHA_256 over an RSA_2048 wrapping key) because the python
#   `cryptography` package is not available in the LocalStack container.
import_key_material() {
  local key_id="$1"
  local alias_name="$2"
  local workdir="${KMS_TMP_DIR}/${key_id}"
  mkdir -p "${workdir}"

  # 32 bytes of deterministic dev-only material, stable across runs.
  printf '%s' "${ECHOROO_KMS_DEV_MATERIAL_SEED}:${alias_name}" \
    | openssl dgst -sha256 -binary > "${workdir}/material.bin"

  # Fetch the wrapping public key (base64 DER) + import token.
  local params
  params=$(awslocal kms get-parameters-for-import \
    --key-id "${key_id}" \
    --wrapping-algorithm RSAES_OAEP_SHA_256 \
    --wrapping-key-spec RSA_2048 \
    --query '[PublicKey, ImportToken]' --output text)
  awk '{print $1}' <<<"${params}" | base64 -d > "${workdir}/wrapping-key.der"
  awk '{print $2}' <<<"${params}" | base64 -d > "${workdir}/import-token.bin"

  # DER (SPKI) → PEM so pkeyutl can consume it portably.
  openssl pkey -pubin -inform DER \
    -in "${workdir}/wrapping-key.der" -out "${workdir}/wrapping-key.pem"

  # Wrap the material with RSAES_OAEP_SHA_256.
  openssl pkeyutl -encrypt -pubin \
    -inkey "${workdir}/wrapping-key.pem" \
    -in "${workdir}/material.bin" \
    -out "${workdir}/material.wrapped.bin" \
    -pkeyopt rsa_padding_mode:oaep \
    -pkeyopt rsa_oaep_md:sha256 \
    -pkeyopt rsa_mgf1_md:sha256

  awslocal kms import-key-material \
    --key-id "${key_id}" \
    --import-token "fileb://${workdir}/import-token.bin" \
    --encrypted-key-material "fileb://${workdir}/material.wrapped.bin" \
    --expiration-model KEY_MATERIAL_DOES_NOT_EXPIRE
  echo "KMS key material imported for '${alias_name}' (key-id=${key_id})"
}

# ensure_alias <alias-name> <key-id>
#   Creates the alias if missing; repoints it if it targets a different key
#   (e.g. an old random CMK from an existing dev environment).
ensure_alias() {
  local alias_name="$1"
  local key_id="$2"

  local current_target
  current_target=$(awslocal kms list-aliases \
    --query "Aliases[?AliasName=='${alias_name}'].TargetKeyId" \
    --output text 2>/dev/null || true)

  if [ -z "${current_target}" ] || [ "${current_target}" = "None" ]; then
    awslocal kms create-alias \
      --alias-name "${alias_name}" --target-key-id "${key_id}"
    echo "KMS alias '${alias_name}' created (key-id=${key_id})"
  elif [ "${current_target}" != "${key_id}" ]; then
    awslocal kms update-alias \
      --alias-name "${alias_name}" --target-key-id "${key_id}"
    echo "KMS alias '${alias_name}' repointed ${current_target} -> ${key_id}"
  else
    echo "KMS alias '${alias_name}' already targets key-id=${key_id}, skipping"
  fi
}

# create_cmk_with_alias <alias-name> <fixed-key-id> <key-usage> <key-spec> <description>
#   key-usage: ENCRYPT_DECRYPT | GENERATE_VERIFY_MAC
#   key-spec : SYMMETRIC_DEFAULT | HMAC_256
#     (both specs take exactly 32 bytes of imported material; the pinned
#      community-archive image supports HMAC_256 natively, so the old
#      SYMMETRIC_DEFAULT fallback was dropped)
#   Idempotent state machine:
#     key absent          → create (EXTERNAL, fixed id) + import material
#     key PendingImport   → import material (recover a partial previous run)
#     key Enabled         → skip
create_cmk_with_alias() {
  local alias_name="$1"
  local key_id="$2"
  local key_usage="$3"
  local key_spec="$4"
  local description="$5"

  local key_state
  key_state=$(awslocal kms describe-key --key-id "${key_id}" \
    --query 'KeyMetadata.KeyState' --output text 2>/dev/null || true)

  case "${key_state}" in
    Enabled)
      echo "KMS key '${alias_name}' (key-id=${key_id}) already Enabled, skipping create+import"
      ;;
    PendingImport)
      echo "KMS key '${alias_name}' (key-id=${key_id}) is PendingImport, importing material"
      import_key_material "${key_id}" "${alias_name}"
      ;;
    ""|None|NotFoundException)
      # LocalStack honours the magic `_custom_id_` tag and assigns exactly
      # this key id, which is what keeps ciphertexts valid across restarts.
      local created_id
      created_id=$(awslocal kms create-key \
        --origin EXTERNAL \
        --key-usage "${key_usage}" \
        --key-spec "${key_spec}" \
        --description "${description}" \
        --tags "TagKey=_custom_id_,TagValue=${key_id}" \
        --query 'KeyMetadata.KeyId' --output text)
      if [ "${created_id}" != "${key_id}" ]; then
        echo "ERROR: LocalStack did not honour _custom_id_ for '${alias_name}' (wanted ${key_id}, got ${created_id})" >&2
        exit 1
      fi
      echo "KMS key '${alias_name}' created with fixed key-id=${key_id}"
      import_key_material "${key_id}" "${alias_name}"
      ;;
    *)
      echo "ERROR: KMS key ${key_id} ('${alias_name}') in unexpected state '${key_state}'" >&2
      exit 1
      ;;
  esac

  ensure_alias "${alias_name}" "${key_id}"
}

# 1) TOTP DEK wrapping key — envelope encryption
create_cmk_with_alias \
  "${ECHOROO_KMS_TOTP_DEK_ALIAS}" \
  "${ECHOROO_KMS_TOTP_DEK_KEY_ID}" \
  "ENCRYPT_DECRYPT" \
  "SYMMETRIC_DEFAULT" \
  "Echoroo: wraps TOTP data encryption keys (FR-051, FR-066)"

# 2) Invitation HMAC signing key
create_cmk_with_alias \
  "${ECHOROO_KMS_INVITATION_HMAC_ALIAS}" \
  "${ECHOROO_KMS_INVITATION_HMAC_KEY_ID}" \
  "GENERATE_VERIFY_MAC" \
  "HMAC_256" \
  "Echoroo: HMAC signing for invitation tokens (FR-052, dual-key rotation)"

# 3) PII hash HMAC key (GenerateMac only)
create_cmk_with_alias \
  "${ECHOROO_KMS_PII_HASH_ALIAS}" \
  "${ECHOROO_KMS_PII_HASH_KEY_ID}" \
  "GENERATE_VERIFY_MAC" \
  "HMAC_256" \
  "Echoroo: keyed HMAC for PII hashing (FR-091, FR-091b)"

# 4) Audit log chain-hash HMAC key
create_cmk_with_alias \
  "${ECHOROO_KMS_AUDIT_CHAIN_ALIAS}" \
  "${ECHOROO_KMS_AUDIT_CHAIN_KEY_ID}" \
  "GENERATE_VERIFY_MAC" \
  "HMAC_256" \
  "Echoroo: keyed HMAC for audit log chain hashing (FR-092)"

echo "LocalStack bootstrap complete"
