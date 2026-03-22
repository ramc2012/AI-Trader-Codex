#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env.aws.single" ]]; then
  echo "Missing .env.aws.single. Create it from scripts/aws/env.aws.single.example first."
  exit 1
fi

env_value() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" .env.aws.single | tail -n 1)"
  printf '%s' "${value}"
}

AWS_REGION="$(env_value AWS_REGION)"
AWS_ACCOUNT_ID="$(env_value AWS_ACCOUNT_ID)"
BACKEND_IMAGE="$(env_value BACKEND_IMAGE)"
FRONTEND_IMAGE="$(env_value FRONTEND_IMAGE)"
EXECUTION_CORE_IMAGE="$(env_value EXECUTION_CORE_IMAGE)"
PUBLIC_HOST="$(env_value PUBLIC_HOST)"
DEPLOY_SUBSECOND_STACK="${DEPLOY_SUBSECOND_STACK:-$(env_value DEPLOY_SUBSECOND_STACK)}"
ALLOW_UNDERSIZED_SUBSECOND_STACK="${ALLOW_UNDERSIZED_SUBSECOND_STACK:-$(env_value ALLOW_UNDERSIZED_SUBSECOND_STACK)}"
SUBSECOND_MIN_MEMORY_GB="${SUBSECOND_MIN_MEMORY_GB:-$(env_value SUBSECOND_MIN_MEMORY_GB)}"
ENSURE_SWING_RESEARCH_ARTIFACTS="${ENSURE_SWING_RESEARCH_ARTIFACTS:-$(env_value ENSURE_SWING_RESEARCH_ARTIFACTS)}"
SWING_RESEARCH_SKIP_EXISTING="${SWING_RESEARCH_SKIP_EXISTING:-$(env_value SWING_RESEARCH_SKIP_EXISTING)}"

if [[ -z "${AWS_REGION:-}" || -z "${AWS_ACCOUNT_ID:-}" ]]; then
  echo "Set AWS_REGION and AWS_ACCOUNT_ID in .env.aws.single"
  exit 1
fi

if [[ -z "${BACKEND_IMAGE:-}" || -z "${FRONTEND_IMAGE:-}" || -z "${PUBLIC_HOST:-}" ]]; then
  echo "Set BACKEND_IMAGE, FRONTEND_IMAGE, and PUBLIC_HOST in .env.aws.single"
  exit 1
fi

compose_args=(--env-file .env.aws.single -f docker-compose.aws-single.yml)
stack_mode="core"

if [[ "${DEPLOY_SUBSECOND_STACK:-false}" == "true" ]]; then
  if [[ -z "${EXECUTION_CORE_IMAGE:-}" ]]; then
    echo "Set EXECUTION_CORE_IMAGE in .env.aws.single when DEPLOY_SUBSECOND_STACK=true"
    exit 1
  fi
  required_memory_gb="${SUBSECOND_MIN_MEMORY_GB:-8}"
  if [[ -r /proc/meminfo ]]; then
    host_memory_mb="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)"
    if [[ -n "${host_memory_mb:-}" ]] && (( host_memory_mb < required_memory_gb * 1024 )); then
      if [[ "${ALLOW_UNDERSIZED_SUBSECOND_STACK:-false}" != "true" ]]; then
        echo "Optional subsecond stack requires about ${required_memory_gb} GiB RAM; host has ~$((${host_memory_mb}/1024)) GiB."
        echo "Use a larger instance or set ALLOW_UNDERSIZED_SUBSECOND_STACK=true to force deployment."
        exit 1
      fi
      echo "Warning: forcing optional subsecond stack on ~$((${host_memory_mb}/1024)) GiB host."
    fi
  fi
  compose_args+=(-f docker-compose.aws-subsecond.yml)
  stack_mode="complete"
fi

echo "Deploying ${stack_mode} stack..."
echo "Logging into ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Pulling latest images..."
docker compose "${compose_args[@]}" pull

echo "Fixing persistent data ownership..."
mkdir -p backend_data
sudo chown -R 1000:1000 backend_data

if [[ "${ENSURE_SWING_RESEARCH_ARTIFACTS:-true}" == "true" ]]; then
  echo "Preparing swing research artifacts..."
  bootstrap_args=()
  if [[ "${SWING_RESEARCH_SKIP_EXISTING:-true}" == "true" ]]; then
    bootstrap_args+=(--skip-existing)
  fi
  docker compose "${compose_args[@]}" run --rm --no-deps backend \
    python -m src.research.bootstrap_runtime_artifacts "${bootstrap_args[@]}"
fi

echo "Ensuring host swap is enabled..."
if ! sudo swapon --show | grep -q '/swapfile'; then
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  if ! grep -q '^/swapfile ' /etc/fstab; then
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
fi

echo "Starting stack..."
docker compose "${compose_args[@]}" up -d

echo "Deployment completed."
docker compose "${compose_args[@]}" ps
