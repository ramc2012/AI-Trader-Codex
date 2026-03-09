#!/usr/bin/env bash
set -euo pipefail

# Deploy/update Nifty AI Trader on an EC2 host using docker-compose.aws.yml.
# Requires Docker Compose v2 and AWS CLI configured on the host.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f ".env.aws" ]]; then
  echo "Missing .env.aws. Create it from scripts/aws/env.aws.example first."
  exit 1
fi

source .env.aws

if [[ -z "${AWS_REGION:-}" || -z "${AWS_ACCOUNT_ID:-}" ]]; then
  echo "Set AWS_REGION and AWS_ACCOUNT_ID in .env.aws"
  exit 1
fi

if [[ -z "${BACKEND_IMAGE:-}" || -z "${FRONTEND_IMAGE:-}" ]]; then
  echo "Set BACKEND_IMAGE and FRONTEND_IMAGE (ECR image URIs) in .env.aws"
  exit 1
fi

echo "Logging into ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "Pulling latest images..."
docker compose --env-file .env.aws -f docker-compose.aws.yml pull

echo "Starting stack..."
docker compose --env-file .env.aws -f docker-compose.aws.yml up -d

echo "Deployment completed."
docker compose --env-file .env.aws -f docker-compose.aws.yml ps
