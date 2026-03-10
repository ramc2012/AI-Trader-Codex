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
PUBLIC_HOST="$(env_value PUBLIC_HOST)"

if [[ -z "${AWS_REGION:-}" || -z "${AWS_ACCOUNT_ID:-}" ]]; then
  echo "Set AWS_REGION and AWS_ACCOUNT_ID in .env.aws.single"
  exit 1
fi

if [[ -z "${BACKEND_IMAGE:-}" || -z "${FRONTEND_IMAGE:-}" || -z "${PUBLIC_HOST:-}" ]]; then
  echo "Set BACKEND_IMAGE, FRONTEND_IMAGE, and PUBLIC_HOST in .env.aws.single"
  exit 1
fi

echo "Logging into ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Pulling latest images..."
docker compose --env-file .env.aws.single -f docker-compose.aws-single.yml pull

echo "Fixing persistent data ownership..."
mkdir -p backend_data
sudo chown -R 1000:1000 backend_data

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
docker compose --env-file .env.aws.single -f docker-compose.aws-single.yml up -d

echo "Deployment completed."
docker compose --env-file .env.aws.single -f docker-compose.aws-single.yml ps
