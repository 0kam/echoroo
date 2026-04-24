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
# Env var overrides (quickstart.md §1) are respected so operators can
# customise alias names per environment.

ECHOROO_KMS_TOTP_DEK_ALIAS="${AWS_KMS_CMK_2FA_ALIAS:-alias/echoroo-totp-dek}"
ECHOROO_KMS_INVITATION_HMAC_ALIAS="${AWS_KMS_CMK_INVITATION_HMAC_ALIAS:-alias/echoroo-invitation-hmac}"
ECHOROO_KMS_PII_HASH_ALIAS="${AWS_KMS_CMK_PII_HASH_ALIAS:-alias/echoroo-pii-hash-hmac}"
ECHOROO_KMS_AUDIT_CHAIN_ALIAS="${AWS_KMS_CMK_AUDIT_CHAIN_ALIAS:-alias/echoroo-audit-chain-hmac}"

# create_cmk_with_alias <alias-name> <key-usage> <key-spec> <description>
#   key-usage: ENCRYPT_DECRYPT | GENERATE_VERIFY_MAC
#   key-spec : SYMMETRIC_DEFAULT | HMAC_256
create_cmk_with_alias() {
  local alias_name="$1"
  local key_usage="$2"
  local key_spec="$3"
  local description="$4"

  # Check alias existence — list-aliases is cheap enough on LocalStack
  if awslocal kms list-aliases --query "Aliases[?AliasName=='${alias_name}'].AliasName" --output text 2>/dev/null | grep -Fxq "${alias_name}"; then
    echo "KMS alias '${alias_name}' already exists, skipping create"
    return 0
  fi

  # Create the CMK. LocalStack Community supports SYMMETRIC_DEFAULT out of the
  # box; HMAC_256 is supported by recent community images and by LocalStack
  # Pro. If unsupported we fall back to SYMMETRIC_DEFAULT so dev still boots.
  local key_id=""
  if ! key_id=$(awslocal kms create-key \
    --key-usage "${key_usage}" \
    --key-spec "${key_spec}" \
    --description "${description}" \
    --query 'KeyMetadata.KeyId' --output text 2>/dev/null); then
    echo "KMS create-key for '${alias_name}' with spec ${key_spec} failed, falling back to SYMMETRIC_DEFAULT (dev only)"
    key_id=$(awslocal kms create-key \
      --key-usage ENCRYPT_DECRYPT \
      --key-spec SYMMETRIC_DEFAULT \
      --description "${description} (fallback SYMMETRIC_DEFAULT)" \
      --query 'KeyMetadata.KeyId' --output text)
  fi

  awslocal kms create-alias \
    --alias-name "${alias_name}" \
    --target-key-id "${key_id}"
  echo "KMS alias '${alias_name}' created (key-id=${key_id})"
}

# 1) TOTP DEK wrapping key — envelope encryption
create_cmk_with_alias \
  "${ECHOROO_KMS_TOTP_DEK_ALIAS}" \
  "ENCRYPT_DECRYPT" \
  "SYMMETRIC_DEFAULT" \
  "Echoroo: wraps TOTP data encryption keys (FR-051, FR-066)"

# 2) Invitation HMAC signing key
create_cmk_with_alias \
  "${ECHOROO_KMS_INVITATION_HMAC_ALIAS}" \
  "GENERATE_VERIFY_MAC" \
  "HMAC_256" \
  "Echoroo: HMAC signing for invitation tokens (FR-052, dual-key rotation)"

# 3) PII hash HMAC key (GenerateMac only)
create_cmk_with_alias \
  "${ECHOROO_KMS_PII_HASH_ALIAS}" \
  "GENERATE_VERIFY_MAC" \
  "HMAC_256" \
  "Echoroo: keyed HMAC for PII hashing (FR-091, FR-091b)"

# 4) Audit log chain-hash HMAC key
create_cmk_with_alias \
  "${ECHOROO_KMS_AUDIT_CHAIN_ALIAS}" \
  "GENERATE_VERIFY_MAC" \
  "HMAC_256" \
  "Echoroo: keyed HMAC for audit log chain hashing (FR-092)"

echo "LocalStack bootstrap complete"
