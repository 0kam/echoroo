#!/usr/bin/env bash
# Echoroo development Docker CLI.

set -euo pipefail

SCRIPT_VERSION="0.1.0"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${PROJECT_DIR}"

COMPOSE_FILE="compose.dev.yaml"
CONFIRM_DELETE="delete echoroo dev volumes"
COMPOSE_AVAILABLE=0

if [[ -t 1 && "${NO_COLOR:-}" == "" ]]; then
  RED=$'\033[0;31m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[1;33m'
  BLUE=$'\033[0;34m'
  NC=$'\033[0m'
else
  RED=""
  GREEN=""
  YELLOW=""
  BLUE=""
  NC=""
fi

info() { printf '%s[INFO]%s %s\n' "${BLUE}" "${NC}" "$*"; }
ok() { printf '%s[OK]%s %s\n' "${GREEN}" "${NC}" "$*"; }
warn() { printf '%s[WARN]%s %s\n' "${YELLOW}" "${NC}" "$*"; }
err() { printf '%s[ERROR]%s %s\n' "${RED}" "${NC}" "$*" >&2; }
die() { err "$*"; exit 1; }

usage() {
  cat <<'EOF'
Echoroo development Docker CLI

Usage:
  ./echoroo.sh [--env dev] <command> [args]
  ./echoroo.sh <command> [args]

Environment:
  dev is the only supported environment in this initial CLI.
  prod/production is intentionally unsupported until a production compose stack exists.

Commands:
  install             Prepare local dev prerequisites. Creates .env from .env.example
                      when missing and generates Redis dev TLS certificates when missing.
                      If .env is created, install exits non-zero so you can edit it.
  checkenv            Validate required and high-risk .env settings.
  start [--build]     Start the dev stack with docker compose up -d.
  stop                Stop the stack and keep data volumes.
  restart [service]   Restart the stack. Without a service, runs down then up -d so
                      compose/env changes are applied. With a service, restarts only it.
                      The "workers" alias expands to "worker worker-cpu".
  update [--allow-dirty] [--yes-migrate] [--ref <branch-or-ref>]
                      Fast-forward the current branch or explicit ref, pull images,
                      build, optionally migrate, and up -d.
                      Aborts on any dirty git status, including untracked files,
                      unless --allow-dirty is explicitly provided.
  version             Show script, git, app, Docker, Compose, and Alembic versions.
  status              Show compose ps plus frontend/backend URLs and /health status.
  logs [service]      Follow compose logs for all services or one service.
  shell [service]     Open a shell in a service container (default: backend).
  db                  Open psql in the db container.
  migrate             Run uv run alembic upgrade head in the backend container.
  seed e2e [args...]  Run the backend E2E permissions seed command. Except for
                      help, passes --confirm unless already provided.
                      Its stdout JSON includes credentials/tokens; handle it as sensitive.
  build [--no-cache] [service...]
                      Build compose images. Uses cache by default; pass --no-cache
                      for a clean rebuild. Optional services are passed to compose.
  clean               docker compose down --remove-orphans.
  clean-all           Remove containers and volumes after typed confirmation.
  help                Show this help.

Examples:
  ./echoroo.sh install
  ./echoroo.sh checkenv
  ./echoroo.sh start --build
  ./echoroo.sh update --ref main
  ./echoroo.sh update --yes-migrate
  ./echoroo.sh restart workers
  ./echoroo.sh logs backend
  ./echoroo.sh clean-all
EOF
}

update_usage() {
  cat <<'EOF'
Usage:
  ./echoroo.sh update [--allow-dirty] [--yes-migrate] [--ref <branch-or-ref>]

Fast-forwards the current git branch with git pull --ff-only, or fast-forwards
to an explicit origin ref when --ref is provided. Then runs docker compose pull,
build, and up -d.

By default this command aborts when git status --porcelain is non-empty,
including untracked files. Use --allow-dirty only when you intentionally want
to update with local changes present.

Migrations are not run by default. Run ./echoroo.sh migrate after update, or
pass --yes-migrate to run migrations during update. When --yes-migrate is used,
the command prints a database backup/snapshot warning and Alembic state before
applying migrations.
EOF
}

build_usage() {
  cat <<'EOF'
Usage:
  ./echoroo.sh build [--no-cache] [service...]

Build compose images. Uses cache by default; pass --no-cache for a clean
rebuild. Optional service names are passed through to docker compose build.
EOF
}

detect_compose() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose -f "${COMPOSE_FILE}")
    COMPOSE_AVAILABLE=1
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose -f "${COMPOSE_FILE}")
    COMPOSE_AVAILABLE=1
    return 0
  fi

  COMPOSE_AVAILABLE=0
  return 1
}

require_compose() {
  detect_compose && return 0
  die "Docker Compose was not found. Install Docker Compose v2 ('docker compose') or docker-compose."
}

compose() {
  "${COMPOSE[@]}" "$@"
}

ensure_dev_environment() {
  local env_name="${1:-dev}"
  case "${env_name}" in
    dev|development) ;;
    prod|production)
      die "Production is not supported yet: no production compose stack exists in this repository."
      ;;
    *)
      die "Unsupported environment '${env_name}'. Only 'dev' is currently supported."
      ;;
  esac

  [[ -f "${COMPOSE_FILE}" ]] || die "Compose file not found: ${COMPOSE_FILE}"
}

ensure_env_file() {
  if [[ -f .env ]]; then
    return 0
  fi

  [[ -f .env.example ]] || die ".env is missing and .env.example was not found."
  cp .env.example .env
  warn "Created .env from .env.example."
  warn "Edit .env before starting Echoroo, then run './echoroo.sh checkenv'."
  exit 1
}

env_value() {
  local key="$1"
  [[ -f .env ]] || return 0

  local line name value
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line%$'\r'}"
    line="$(trim_ws "${line}")"
    [[ -z "${line}" || "${line:0:1}" == "#" || "${line}" != *"="* ]] && continue
    name="$(trim_ws "${line%%=*}")"
    [[ "${name}" == "${key}" ]] || continue
    value="${line#*=}"
    value="$(strip_env_comment "${value}")"
    value="$(trim_ws "${value}")"
    if [[ ( "${value:0:1}" == '"' && "${value: -1}" == '"' ) || ( "${value:0:1}" == "'" && "${value: -1}" == "'" ) ]]; then
      value="${value:1:${#value}-2}"
    fi
    printf '%s\n' "${value}"
    return 0
  done < .env
}

trim_ws() {
  local s="$1"
  while [[ "${s}" == [[:space:]]* ]]; do
    s="${s:1}"
  done
  while [[ "${s}" == *[[:space:]] ]]; do
    s="${s:0:${#s}-1}"
  done
  printf '%s' "${s}"
}

strip_env_comment() {
  local s="$1"
  local out="" char prev="" in_single=0 in_double=0
  local i
  for (( i = 0; i < ${#s}; i++ )); do
    char="${s:i:1}"
    if [[ "${char}" == "'" && "${in_double}" -eq 0 ]]; then
      in_single=$((1 - in_single))
    elif [[ "${char}" == '"' && "${in_single}" -eq 0 ]]; then
      in_double=$((1 - in_double))
    elif [[ "${char}" == "#" && "${in_single}" -eq 0 && "${in_double}" -eq 0 ]]; then
      if [[ -z "${prev}" || "${prev}" == [[:space:]] ]]; then
        break
      fi
    fi
    out+="${char}"
    prev="${char}"
  done
  printf '%s' "${out}"
}

redis_cert_missing() {
  [[ ! -f config/redis/tls/ca.crt || ! -f config/redis/tls/redis.crt || ! -f config/redis/tls/redis.key ]]
}

ensure_redis_cert() {
  if redis_cert_missing; then
    [[ -x scripts/gen-redis-dev-cert.sh ]] || die "scripts/gen-redis-dev-cert.sh is missing or not executable."
    info "Generating Redis dev TLS certificates..."
    ./scripts/gen-redis-dev-cert.sh
  fi
}

check_env_values() {
  ensure_env_file

  local failures=0
  local postgres_password invitation_key invitation_kid audio_dir
  local invitation_kid_old invitation_key_old
  local environment test_mode test_totp
  local database_url redis_url s3_endpoint s3_bucket jwt_secret
  local web_session_secret two_factor_hmac
  postgres_password="$(env_value POSTGRES_PASSWORD)"
  invitation_key="$(env_value INVITATION_TOKEN_HMAC_KEY)"
  invitation_kid="$(env_value INVITATION_TOKEN_KID_NEW)"
  invitation_kid_old="$(env_value INVITATION_TOKEN_KID_OLD)"
  invitation_key_old="$(env_value INVITATION_TOKEN_HMAC_KEY_OLD)"
  audio_dir="$(env_value ECHOROO_AUDIO_DIR)"
  environment="$(env_value ENVIRONMENT)"
  test_mode="$(env_value TEST_MODE)"
  test_totp="$(env_value TEST_TOTP_SECRET_BASE32)"
  database_url="$(env_value DATABASE_URL)"
  redis_url="$(env_value REDIS_URL)"
  s3_endpoint="$(env_value S3_ENDPOINT_URL)"
  s3_bucket="$(env_value S3_BUCKET)"
  jwt_secret="$(env_value JWT_SECRET_KEY)"
  web_session_secret="$(env_value web_session_secret)"
  two_factor_hmac="$(env_value TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY)"

  if [[ -z "${postgres_password}" || "${postgres_password}" == "CHANGE_ME_BEFORE_USE" ]]; then
    err "POSTGRES_PASSWORD must be set to a non-placeholder value."
    failures=1
  fi

  # Invitation-token signing — KID_NEW + HMAC_KEY are required at every boot
  # in every environment (spec/011 NFR-011-010; enforced by settings.py).
  if [[ -z "${invitation_key}" ]]; then
    err "INVITATION_TOKEN_HMAC_KEY must be set (required at every boot)."
    failures=1
  fi
  if [[ -z "${invitation_kid}" ]]; then
    err "INVITATION_TOKEN_KID_NEW must be set (required at every boot)."
    failures=1
  fi
  # The _OLD rotation pair must be set together or both unset.
  if [[ -n "${invitation_kid_old}" && -z "${invitation_key_old}" ]] \
    || [[ -z "${invitation_kid_old}" && -n "${invitation_key_old}" ]]; then
    err "INVITATION_TOKEN_KID_OLD and INVITATION_TOKEN_HMAC_KEY_OLD must be set together (or both unset)."
    failures=1
  fi

  case "${audio_dir}" in
    ""|"/path/to/your/audio/files"|"CHANGE_ME"*|"changeme"*|"TODO"*|"todo"*|"placeholder"*|"/tmp/echoroo-audio")
      err "ECHOROO_AUDIO_DIR must be set to a real host audio directory, not '${audio_dir:-<empty>}'."
      failures=1
      ;;
    *)
      if [[ ! -d "${audio_dir}" ]]; then
        err "ECHOROO_AUDIO_DIR does not exist or is not a directory: ${audio_dir}"
        failures=1
      fi
      ;;
  esac

  # TEST_MODE is a dev-only 2FA bypass; when enabled the shared TOTP secret
  # is mandatory (mirrors the settings.py model_validator).
  if [[ "${test_mode,,}" == "true" || "${test_mode}" == "1" ]]; then
    if [[ -z "${test_totp}" ]]; then
      err "TEST_MODE is enabled but TEST_TOTP_SECRET_BASE32 is not set."
      failures=1
    fi
    if [[ "${environment,,}" == "production" ]]; then
      err "TEST_MODE must not be enabled when ENVIRONMENT=production."
      failures=1
    fi
  fi

  # Connection-string sanity checks — only when set explicitly (the dev
  # Docker stack builds DATABASE_URL / REDIS_URL from POSTGRES_* / REDIS_*
  # inside compose, so an empty value here is expected and not an error).
  if [[ -n "${database_url}" && "${database_url}" != postgresql* ]]; then
    err "DATABASE_URL must be a postgresql:// (asyncpg) connection string, got: ${database_url}"
    failures=1
  fi
  if [[ -n "${redis_url}" && "${redis_url}" != redis://* && "${redis_url}" != rediss://* ]]; then
    err "REDIS_URL must start with redis:// or rediss://, got: ${redis_url}"
    failures=1
  fi
  # Object storage — only format-check when overridden (compose supplies the
  # dev defaults). Both must be non-empty together to be usable.
  if [[ -n "${s3_endpoint}" && "${s3_endpoint}" != http://* && "${s3_endpoint}" != https://* ]]; then
    err "S3_ENDPOINT_URL must be an http(s):// URL, got: ${s3_endpoint}"
    failures=1
  fi
  if [[ -n "${s3_endpoint}" && -z "${s3_bucket}" ]]; then
    err "S3_ENDPOINT_URL is set but S3_BUCKET is empty."
    failures=1
  fi

  # Production/staging secret-strength gate — mirrors the settings.py
  # validate_production_secrets guard so a bad .env fails here (fast, offline)
  # rather than at container boot. KMS aliases default to the LocalStack
  # bootstrap values, so they are only checked for format when set.
  if [[ "${environment,,}" == "production" || "${environment,,}" == "staging" ]]; then
    require_strong_secret "JWT_SECRET_KEY" "${jwt_secret}" \
      "your-secret-key-change-in-production dev-secret-key-change-in-production" \
      failures
    require_strong_secret "web_session_secret" "${web_session_secret}" \
      "dev-web-session-secret-change-in-production" failures
    require_strong_secret "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY" "${two_factor_hmac}" \
      "dev-two-factor-confirmation-hmac-change-in-production" failures
    require_strong_secret "INVITATION_TOKEN_HMAC_KEY" "${invitation_key}" "" failures
    local s3_secret
    s3_secret="$(env_value S3_SECRET_KEY)"
    if [[ "${s3_secret}" == "echoroo-dev" ]]; then
      err "S3_SECRET_KEY must be changed from the dev default in production/staging."
      failures=1
    fi
    check_kms_alias_format failures
  fi

  if redis_cert_missing; then
    err "Redis TLS certificates are missing under config/redis/tls. Run './echoroo.sh install'."
    failures=1
  fi

  # Xeno-Canto search is an optional feature (settings.py xeno_canto_enabled).
  # It is enabled only when XENO_CANTO_API_KEY is a real, non-"demo" key; the
  # backend degrades gracefully otherwise (typed 409 + hidden UI tab). This is
  # purely informational and never fails the check.
  local xeno_canto_key
  xeno_canto_key="$(env_value XENO_CANTO_API_KEY)"
  if [[ -z "${xeno_canto_key}" ]]; then
    info "Xeno-Canto search is disabled (XENO_CANTO_API_KEY not set) — optional feature."
  elif [[ "${xeno_canto_key}" == "demo" ]]; then
    info "Xeno-Canto search is disabled (XENO_CANTO_API_KEY='demo' is treated as unset) — optional feature."
  fi

  if [[ "${failures}" -ne 0 ]]; then
    exit 1
  fi

  ok ".env looks usable for the dev Docker stack."
}

# require_strong_secret NAME VALUE "weak default1 default2 ..." FAILVAR
# Flags an empty value, any listed weak default, or a value shorter than 32
# chars. FAILVAR is the name of the caller's failures variable (set to 1 on
# error). Used only inside the production/staging branch of check_env_values.
require_strong_secret() {
  local name="$1" value="$2" weak_defaults="$3" fail_var="$4"
  if [[ -z "${value}" ]]; then
    err "${name} must be set to a strong secret (>=32 chars) in production/staging."
    printf -v "${fail_var}" '%s' 1
    return
  fi
  local weak
  for weak in ${weak_defaults}; do
    if [[ "${value}" == "${weak}" ]]; then
      err "${name} is still the insecure default value; change it in production/staging."
      printf -v "${fail_var}" '%s' 1
      return
    fi
  done
  if [[ "${#value}" -lt 32 ]]; then
    err "${name} must be at least 32 characters in production/staging (got ${#value})."
    printf -v "${fail_var}" '%s' 1
  fi
}

# check_kms_alias_format FAILVAR
# When a KMS CMK alias is set explicitly, sanity-check it is an alias/... name
# or an arn:aws:kms ARN. Unset aliases fall back to the code defaults and are
# fine. Also enforces the TOTP-DEK rotation _OLD alias/kid co-presence rule.
check_kms_alias_format() {
  local fail_var="$1" var value
  for var in \
    AWS_KMS_CMK_2FA_ALIAS \
    AWS_KMS_CMK_PII_HASH_ALIAS \
    AWS_KMS_CMK_PII_HASH_ALIAS_V2 \
    AWS_KMS_CMK_AUDIT_CHAIN_ALIAS \
    AWS_KMS_CMK_INVITATION_HMAC_ALIAS \
    AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW \
    AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD \
    AWS_KMS_CMK_2FA_DEK_ALIAS_NEW \
    AWS_KMS_CMK_2FA_DEK_ALIAS_OLD; do
    value="$(env_value "${var}")"
    if [[ -n "${value}" && "${value}" != alias/* && "${value}" != arn:aws:kms:* ]]; then
      err "${var} must be an 'alias/...' name or a KMS ARN, got: ${value}"
      printf -v "${fail_var}" '%s' 1
    fi
  done
  local dek_alias_old dek_kid_old
  dek_alias_old="$(env_value AWS_KMS_CMK_2FA_DEK_ALIAS_OLD)"
  dek_kid_old="$(env_value AWS_KMS_CMK_2FA_DEK_KID_OLD)"
  if [[ -n "${dek_alias_old}" && -z "${dek_kid_old}" ]] \
    || [[ -z "${dek_alias_old}" && -n "${dek_kid_old}" ]]; then
    err "AWS_KMS_CMK_2FA_DEK_ALIAS_OLD and AWS_KMS_CMK_2FA_DEK_KID_OLD must be set together (or both unset)."
    printf -v "${fail_var}" '%s' 1
  fi
}

print_urls() {
  local frontend_port backend_port public_host
  frontend_port="$(env_value ECHOROO_FRONTEND_PORT)"
  backend_port="$(env_value ECHOROO_API_PORT)"
  # ECHOROO_PUBLIC_HOST is the single deploy knob (default localhost); showing
  # the effective value lets LAN/FQDN deployers see the real browser URLs.
  public_host="$(env_value ECHOROO_PUBLIC_HOST)"
  printf 'Frontend: http://%s:%s\n' "${public_host:-localhost}" "${frontend_port:-5173}"
  printf 'Backend:  http://%s:%s\n' "${public_host:-localhost}" "${backend_port:-8002}"
}

start_stack() {
  local build=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --build) build=1 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown start option: $1" ;;
    esac
    shift
  done

  check_env_values
  if [[ "${build}" -eq 1 ]]; then
    compose up -d --build
  else
    compose up -d
  fi
  ok "Dev stack started."
  print_urls
}

restart_stack() {
  if [[ $# -gt 0 ]]; then
    if [[ "$1" == "workers" ]]; then
      compose restart worker worker-cpu
    else
      compose restart "$1"
    fi
    ok "Restart complete."
    return
  fi

  check_env_values
  compose down
  compose up -d
  ok "Dev stack restarted."
  print_urls
}

run_update() {
  local allow_dirty=0
  local yes_migrate=0
  local update_ref=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --allow-dirty) allow_dirty=1 ;;
      --yes-migrate) yes_migrate=1 ;;
      --ref)
        [[ $# -ge 2 ]] || die "--ref requires a branch or ref."
        update_ref="$2"
        shift
        ;;
      -h|--help) update_usage; exit 0 ;;
      *) die "Unknown update option: $1" ;;
    esac
    shift
  done

  if git_available && git_dirty && [[ "${allow_dirty}" -eq 0 ]]; then
    err "Refusing to update with a dirty git worktree."
    err "Commit, stash, or remove local changes first, or rerun with --allow-dirty."
    exit 1
  fi

  check_env_values

  if git_available; then
    update_git_checkout "${update_ref}"
  else
    warn "Not a git checkout or git is unavailable; skipping git pull."
  fi

  info "Pulling compose images where possible..."
  if ! compose pull; then
    warn "docker compose pull failed for one or more services. This is expected for locally built services; continuing with build."
  fi

  compose build
  if [[ "${yes_migrate}" -eq 1 ]]; then
    run_migrate
  else
    warn "Skipping DB migrations during update."
    warn "Run './echoroo.sh migrate' after update, or rerun './echoroo.sh update --yes-migrate' to include migrations."
  fi
  compose up -d
  ok "Update complete."
  print_urls
}

update_git_checkout() {
  local update_ref="$1"
  local current_branch default_branch
  current_branch="$(git branch --show-current 2>/dev/null || true)"
  default_branch="$(git_default_branch)"

  if [[ -n "${update_ref}" ]]; then
    info "Fetching origin ${update_ref} and fast-forwarding with FETCH_HEAD..."
    git fetch origin "${update_ref}"
    git merge --ff-only FETCH_HEAD
    return
  fi

  if [[ -n "${current_branch}" ]]; then
    info "Updating current git branch '${current_branch}' with git pull --ff-only..."
    if [[ -n "${default_branch}" && "${current_branch}" != "${default_branch}" ]]; then
      warn "Current branch '${current_branch}' is not the default branch '${default_branch}'."
      warn "Use './echoroo.sh update --ref ${default_branch}' if you intended to update from the default branch."
    elif [[ -z "${default_branch}" && "${current_branch}" != "main" && "${current_branch}" != "master" ]]; then
      warn "Current branch '${current_branch}' is not main/master; git pull --ff-only will update this branch."
    fi
  else
    warn "Git checkout is detached; git pull --ff-only will run on the current detached HEAD."
  fi
  git pull --ff-only
}

git_default_branch() {
  local ref
  ref="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  printf '%s\n' "${ref#origin/}"
}

run_migrate() {
  warn "DB migrations may change schema. A database backup/snapshot is recommended."
  if service_running backend; then
    print_alembic_state_exec
    compose exec backend uv run alembic upgrade head
  else
    warn "Backend is not running; starting db, redis, and localstack before one-off migration."
    compose up -d db redis localstack
    wait_service_healthy db 60
    print_alembic_state_run
    compose run --rm backend uv run alembic upgrade head
  fi
}

print_alembic_state_exec() {
  info "Alembic current revision:"
  compose exec -T backend uv run alembic current || warn "Could not read Alembic current revision."
  info "Alembic heads:"
  compose exec -T backend uv run alembic heads || warn "Could not read Alembic heads."
  if compose exec -T backend uv run alembic check; then
    ok "Alembic check passed."
  else
    warn "Alembic check did not pass or is unsupported in this environment; continuing because current/heads were displayed above."
  fi
}

print_alembic_state_run() {
  info "Alembic current revision:"
  compose run --rm backend uv run alembic current || warn "Could not read Alembic current revision."
  info "Alembic heads:"
  compose run --rm backend uv run alembic heads || warn "Could not read Alembic heads."
  if compose run --rm backend uv run alembic check; then
    ok "Alembic check passed."
  else
    warn "Alembic check did not pass or is unsupported in this environment; continuing because current/heads were displayed above."
  fi
}

run_seed_e2e() {
  local seed_args=()
  local has_confirm=0
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    seed_args=(--help)
  else
    seed_args=("$@")
    for arg in "${seed_args[@]}"; do
      if [[ "${arg}" == "--confirm" ]]; then
        has_confirm=1
        break
      fi
    done
    if [[ "${has_confirm}" -eq 0 ]]; then
      seed_args=(--confirm "${seed_args[@]}")
    fi
  fi

  if [[ "${seed_args[0]:-}" != "--help" && "${seed_args[0]:-}" != "-h" ]]; then
    warn "seed e2e prints JSON containing credentials/tokens. Treat stdout as sensitive."
  fi

  if service_running backend; then
    compose exec backend uv run python -m echoroo.scripts.seed_e2e_permissions "${seed_args[@]}"
  else
    compose run --rm backend uv run python -m echoroo.scripts.seed_e2e_permissions "${seed_args[@]}"
  fi
}

run_build() {
  local no_cache=0
  local services=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-cache)
        no_cache=1
        ;;
      -h|--help)
        build_usage
        exit 0
        ;;
      --*)
        die "Unknown build option: $1"
        ;;
      *)
        services+=("$1")
        ;;
    esac
    shift
  done

  local build_args=()
  if [[ "${no_cache}" -eq 1 ]]; then
    build_args+=(--no-cache)
  fi
  build_args+=("${services[@]}")
  compose build "${build_args[@]}"
}

run_db() {
  local db_user db_name
  db_user="$(env_value POSTGRES_USER)"
  db_name="$(env_value POSTGRES_DB)"
  compose exec db psql -U "${db_user:-postgres}" "${db_name:-echoroo}"
}

run_shell() {
  local service="${1:-backend}"
  compose exec "${service}" /bin/sh
}

run_logs() {
  if [[ $# -gt 0 ]]; then
    compose logs -f "$1"
  else
    compose logs -f
  fi
}

git_version() {
  if git_available; then
    local desc dirty
    desc="$(git describe --tags --always 2>/dev/null || git rev-parse --short HEAD)"
    dirty=""
    if git_dirty; then
      dirty=" dirty"
    fi
    printf '%s%s\n' "${desc}" "${dirty}"
  else
    printf 'unavailable\n'
  fi
}

git_available() {
  command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1
}

git_dirty() {
  [[ -n "$(git status --porcelain)" ]]
}

toml_version() {
  awk -F= '$1 == "version " || $1 == "version" {gsub(/[ "]/, "", $2); print $2; exit}' apps/api/pyproject.toml 2>/dev/null || true
}

json_version() {
  sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' apps/web/package.json 2>/dev/null | head -n 1
}

alembic_current() {
  if [[ "${COMPOSE_AVAILABLE}" -eq 1 ]] && service_running backend; then
    compose exec -T backend uv run alembic current 2>/dev/null | sed -n '1p' || true
  fi
}

service_running() {
  [[ "${COMPOSE_AVAILABLE}" -eq 1 ]] || return 1
  command -v docker >/dev/null 2>&1 || return 1
  local service="$1"
  local cid
  cid="$(compose ps -q "${service}" 2>/dev/null | head -n 1 || true)"
  [[ -n "${cid}" ]] || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "${cid}" 2>/dev/null || true)" == "true" ]]
}

wait_service_healthy() {
  local service="$1"
  local timeout_seconds="${2:-60}"
  local start now cid status
  start="$(date +%s)"

  while true; do
    cid="$(compose ps -q "${service}" 2>/dev/null | head -n 1 || true)"
    if [[ -n "${cid}" ]]; then
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{if .State.Running}}running{{else}}stopped{{end}}{{end}}' "${cid}" 2>/dev/null || true)"
      case "${status}" in
        healthy|running)
          ok "${service} is ${status}."
          return 0
          ;;
        unhealthy)
          die "${service} became unhealthy."
          ;;
      esac
    fi

    now="$(date +%s)"
    if (( now - start >= timeout_seconds )); then
      die "Timed out waiting for ${service} to become healthy."
    fi
    sleep 2
  done
}

run_version() {
  printf 'Echoroo CLI: %s\n' "${SCRIPT_VERSION}"
  printf 'Git:         %s\n' "$(git_version)"
  printf 'API:         %s\n' "$(toml_version)"
  printf 'Web:         %s\n' "$(json_version)"

  local docker_version
  if command -v docker >/dev/null 2>&1 && docker_version="$(docker --version 2>/dev/null)"; then
    printf 'Docker:      %s\n' "${docker_version}"
  else
    printf 'Docker:      unavailable\n'
  fi

  local compose_version
  if [[ "${COMPOSE_AVAILABLE}" -eq 1 ]]; then
    compose_version="$("${COMPOSE[@]}" version 2>/dev/null | head -n 1 || true)"
    printf 'Compose:     %s\n' "${compose_version:-unavailable}"
  else
    printf 'Compose:     unavailable\n'
  fi

  local current
  current="$(alembic_current)"
  printf 'Alembic:     %s\n' "${current:-unavailable (backend not running)}"
}

run_status() {
  compose ps
  echo
  print_urls

  local backend_port health_url
  backend_port="$(env_value ECHOROO_API_PORT)"
  health_url="http://localhost:${backend_port:-8002}/health"

  if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 3 "${health_url}" >/dev/null; then
      ok "Backend health: ${health_url} is reachable."
    else
      warn "Backend health: ${health_url} is not reachable."
    fi
  else
    warn "curl is unavailable; skipped backend /health check."
  fi
}

run_clean_all() {
  warn "This will delete Echoroo dev containers and Docker volumes."
  warn "Database, backend data, Redis data, ML cache, and generated frontend volume will be removed."
  printf 'Type "%s" to continue: ' "${CONFIRM_DELETE}"
  local reply
  read -r reply
  if [[ "${reply}" != "${CONFIRM_DELETE}" ]]; then
    die "Confirmation did not match. Aborted."
  fi
  compose down -v --remove-orphans
  ok "Dev containers and volumes removed."
}

main() {
  local env_name="dev"
  if [[ "${1:-}" == "--env" || "${1:-}" == "-e" ]]; then
    [[ $# -ge 2 ]] || die "--env requires a value."
    env_name="$2"
    shift 2
  elif [[ "${1:-}" == "dev" || "${1:-}" == "development" || "${1:-}" == "prod" || "${1:-}" == "production" ]]; then
    env_name="$1"
    shift
  fi

  local command="${1:-help}"
  shift || true

  case "${command}" in
    help|-h|--help)
      usage
      exit 0
      ;;
  esac

  ensure_dev_environment "${env_name}"

  if [[ "${command}" == "update" && ( "${1:-}" == "--help" || "${1:-}" == "-h" ) ]]; then
    update_usage
    exit 0
  fi

  if [[ "${command}" == "build" && ( "${1:-}" == "--help" || "${1:-}" == "-h" ) ]]; then
    build_usage
    exit 0
  fi

  if [[ "${command}" == "version" ]]; then
    detect_compose || true
    run_version
    exit 0
  fi

  require_compose

  case "${command}" in
    install)
      ensure_redis_cert
      ensure_env_file
      check_env_values
      ;;
    checkenv) check_env_values ;;
    start|up) start_stack "$@" ;;
    stop) compose stop; ok "Dev stack stopped; data volumes were kept." ;;
    restart) restart_stack "$@" ;;
    update) run_update "$@" ;;
    status|ps) run_status ;;
    logs) run_logs "$@" ;;
    shell) run_shell "$@" ;;
    db) run_db ;;
    migrate) run_migrate ;;
    seed)
      [[ "${1:-}" == "e2e" ]] || die "Only 'seed e2e' is supported."
      shift
      run_seed_e2e "$@"
      ;;
    build) run_build "$@" ;;
    clean) compose down --remove-orphans; ok "Dev containers removed; data volumes were kept." ;;
    clean-all) run_clean_all ;;
    *)
      err "Unknown command: ${command}"
      usage
      exit 1
      ;;
  esac
}

main "$@"
