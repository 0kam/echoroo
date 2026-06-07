#!/usr/bin/env bash
# Compatibility wrapper for the top-level Echoroo Docker CLI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

if [[ "${1:-}" == "dev" || "${1:-}" == "development" || "${1:-}" == "prod" || "${1:-}" == "production" ]]; then
  env_name="$1"
  shift

  if [[ "${env_name}" == "dev" || "${env_name}" == "development" ]]; then
    if [[ $# -eq 0 ]]; then
      if [[ "${ECHOROO_BUILD:-0}" == "1" ]]; then
        exec "${PROJECT_DIR}/echoroo.sh" "${env_name}" start --build
      fi
      exec "${PROJECT_DIR}/echoroo.sh" "${env_name}" start
    fi

    if [[ "$1" == "start" && "${ECHOROO_BUILD:-0}" == "1" ]]; then
      shift
      exec "${PROJECT_DIR}/echoroo.sh" "${env_name}" start --build "$@"
    fi

    if [[ "$1" == "build" ]]; then
      shift
      if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
        exec "${PROJECT_DIR}/echoroo.sh" "${env_name}" build "$@"
      fi
      exec "${PROJECT_DIR}/echoroo.sh" "${env_name}" build --no-cache "$@"
    fi
  fi

  exec "${PROJECT_DIR}/echoroo.sh" "${env_name}" "$@"
fi

exec "${PROJECT_DIR}/echoroo.sh" dev "$@"
