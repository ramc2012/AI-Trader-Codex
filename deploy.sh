#!/usr/bin/env bash
# NiftyTraderGravity - Google Cloud Platform Deployment Script
# This script provisions a Google Compute Engine VM and deploys the docker-compose stack.
# Usage: ./deploy.sh
# Note: Ensure you are logged into gcloud via `gcloud auth login` and have a project set.

set -e

# Configuration
INSTANCE_NAME="nifty-trader-node"
MACHINE_TYPE="n2-standard-2" # 2 vCPU, 8GB RAM (High Availability Tier)
ZONE="us-central1-a"
IMAGE_FAMILY="debian-11"
IMAGE_PROJECT="debian-cloud"

echo "============================================================"
echo "🚀 NiftyTraderGravity GCP Deployment Orchestrator"
echo "============================================================"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ Error: Google Cloud CLI 'gcloud' is not installed."
    echo "Please visit: https://cloud.google.com/sdk/docs/install or run this from Google Cloud Shell."
    exit 1
fi

# Fetch current active account and project
CURRENT_ACCOUNT=$(gcloud config get-value account 2>/dev/null)
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)

if [ -z "$CURRENT_PROJECT" ]; then
    echo "❌ Error: No GCP Project is set."
    echo "Run: gcloud config set project [YOUR_PROJECT_ID]"
    exit 1
fi

echo "✅ Authenticated as: $CURRENT_ACCOUNT"
echo "✅ Target Project: $CURRENT_PROJECT"
echo ""
echo "This will create a new Compute Engine VM ($INSTANCE_NAME) and deploy the Docker stack."

echo "⏳ Provisioning Compute Engine VM ($INSTANCE_NAME)..."

# Create the instance (ignore error if exists)
gcloud compute instances create $INSTANCE_NAME \
    --project=$CURRENT_PROJECT \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --image-family=$IMAGE_FAMILY \
    --image-project=$IMAGE_PROJECT \
    --tags=http-server,https-server,nifty-trader \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-ssd || echo "⚠️ Instance $INSTANCE_NAME already exists, skipping creation."

echo "✅ VM Provisioned successfully."

echo "⏳ Configuring firewall rules for the application..."
gcloud compute firewall-rules create allow-nifty-trader \
    --direction=INGRESS \
    --priority=1000 \
    --network=default \
    --action=ALLOW \
    --rules=tcp:80,tcp:443,tcp:3000-3250,tcp:8000-8050 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=nifty-trader || echo "⚠️ Firewall rule already exists."

echo "✅ Firewall rules configured."

# Give the VM time to boot up SSH keys
echo "⏳ Waiting for VM SSH access to spin up (30 seconds)..."
sleep 30

echo "⏳ Installing Docker & cloning repository on the VM..."

# We use a startup script passed via SSH to install dependencies and run the compose.
# In a real environment, you'd pull from your private git repo. We will copy the files using gcloud scp.

# Creating an archive to send
echo "📦 Packaging local repository..."
tar --exclude='venv' --exclude='.git' --exclude='node_modules' --exclude='.next' --exclude='__pycache__' -czf nifty-trader.tar.gz .

echo "📤 Uploading repository to VM..."
gcloud compute scp nifty-trader.tar.gz $INSTANCE_NAME:~ --zone=$ZONE

# Remote execution: Extract, Build, and Start
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command="
    if ! command -v docker &> /dev/null; then
        echo '⏳ Installing Docker...'
        sudo apt-get update && \
        sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release && \
        curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
        echo \"deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \$(lsb_release -cs) stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null && \
        sudo apt-get update && \
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin && \
        sudo usermod -aG docker \$USER
    fi
    
    mkdir -p nifty-trader && \
    tar -xzf nifty-trader.tar.gz -C nifty-trader && \
    cd nifty-trader && \
    sudo docker compose build --build-arg NEXT_PUBLIC_APP_INSTANCE_LABEL=GCloud && \
    sudo docker compose up -d
"

# Get Public IP
PUBLIC_IP=$(gcloud compute instances describe $INSTANCE_NAME --zone=$ZONE --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

echo "============================================================"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "============================================================"
echo "Frontend URL: http://$PUBLIC_IP:3201 (or 3000 depending on env)"
echo "Backend API & Swagger: http://$PUBLIC_IP:8001/docs"
echo "Prometheus Metrics: http://$PUBLIC_IP:8001/metrics"
echo ""
echo "Note: It may take 1-3 minutes for the DB to initialize and the web server to start responding."
echo "To view logs, run: gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command=\"cd nifty-trader && sudo docker compose logs -f\""
