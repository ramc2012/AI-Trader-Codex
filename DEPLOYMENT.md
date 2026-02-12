# 🚀 Deployment Guide - Nifty AI Trader

This guide covers deploying the Nifty AI Trader using Docker.

## Prerequisites

- Docker Desktop installed (version 20.10+)
- Docker Compose v2.0+
- 8GB+ RAM available
- 20GB+ free disk space
- Fyers API credentials

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/ramc2012/Invest_manager.git
cd Invest_manager
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Fyers API
FYERS_APP_ID=your_app_id
FYERS_SECRET_KEY=your_secret_key
FYERS_REDIRECT_URI=http://localhost:3000/api/auth/callback
FYERS_REDIRECT_FRONTEND_URL=http://localhost:3000/settings

# Database
POSTGRES_USER=nifty_trader
POSTGRES_PASSWORD=change_this_password
POSTGRES_DB=nifty_trading
DB_HOST=timescaledb
DB_PORT=5432
DATABASE_URL=postgresql+asyncpg://nifty_trader:change_this_password@timescaledb:5432/nifty_trading

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# API
API_HOST=0.0.0.0
API_PORT=8000
APP_ENV=production
SECRET_KEY=$(openssl rand -hex 32)
```

### 2. Build and Start Services

```bash
# Build all images
docker-compose build

# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### 3. Verify Services

```bash
# Check backend API
curl http://localhost:8000/api/v1/health

# Check frontend
open http://localhost:3000

# Check database
docker-compose exec timescaledb psql -U nifty_trader -d nifty_trading -c "\dt"

# Check Redis
docker-compose exec redis redis-cli ping
```

## Service URLs

| Service | URL | Description |
|---------|-----|-------------|
| Frontend Dashboard | http://localhost:3000 | Web UI |
| Backend API | http://localhost:8000 | FastAPI backend |
| API Docs | http://localhost:8000/docs | Swagger UI |
| TimescaleDB | localhost:5432 | PostgreSQL database |
| Redis | localhost:6379 | Cache & message broker |

## Common Operations

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f timescaledb
docker-compose logs -f redis

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart backend
```

### Stop Services

```bash
# Stop all (preserves data)
docker-compose stop

# Stop and remove containers (preserves data volumes)
docker-compose down

# Stop and remove everything including data
docker-compose down -v
```

### Update Application

```bash
# Pull latest code
git pull origin main

# Rebuild images
docker-compose build

# Recreate containers
docker-compose up -d --force-recreate
```

### Database Operations

```bash
# Access PostgreSQL shell
docker-compose exec timescaledb psql -U nifty_trader -d nifty_trading

# Run migrations
docker-compose exec backend python scripts/init_db.py

# Backup database
docker-compose exec timescaledb pg_dump -U nifty_trader nifty_trading > backup_$(date +%Y%m%d).sql

# Restore database
docker-compose exec -T timescaledb psql -U nifty_trader nifty_trading < backup_20240101.sql
```

### Redis Operations

```bash
# Access Redis CLI
docker-compose exec redis redis-cli

# Check memory usage
docker-compose exec redis redis-cli INFO memory

# Clear all data
docker-compose exec redis redis-cli FLUSHALL
```

## Monitoring

### Resource Usage

```bash
# Container stats
docker stats

# Disk usage
docker system df

# Network usage
docker-compose top
```

### Health Checks

```bash
# Check all services
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/monitoring/health

# Database connection
docker-compose exec backend python -c "from src.database.connection import check_db_health; import asyncio; asyncio.run(check_db_health())"
```

## Troubleshooting

### Backend won't start

```bash
# Check logs
docker-compose logs backend

# Common issues:
# 1. Database not ready - wait for timescaledb to be healthy
# 2. Port conflict - change APP_PORT in .env
# 3. Missing env vars - verify .env file
```

### Frontend won't connect

```bash
# Check backend is running
curl http://localhost:8000/api/v1/health

# Check environment variables
docker-compose exec frontend env | grep API

# Rebuild frontend
docker-compose build frontend
docker-compose up -d frontend
```

### Database connection errors

```bash
# Check if database is running
docker-compose ps timescaledb

# Check connection
docker-compose exec timescaledb pg_isready

# Check credentials match
docker-compose exec backend env | grep DB_
```

### Out of disk space

```bash
# Clean up old images
docker system prune -a

# Remove unused volumes
docker volume prune

# Check space usage
df -h
docker system df
```

## Production Deployment

### Security Checklist

- [ ] Change all default passwords
- [ ] Use strong SECRET_KEY
- [ ] Enable HTTPS/TLS
- [ ] Configure firewall rules
- [ ] Set up backup strategy
- [ ] Enable monitoring/alerting
- [ ] Review exposed ports
- [ ] Use secrets management (e.g., Docker secrets)

### Performance Tuning

```yaml
# docker-compose.yml adjustments for production

backend:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 4G
      reservations:
        cpus: '1'
        memory: 2G
  environment:
    APP_ENV: production
    APP_DEBUG: false
    WORKERS: 4  # Adjust based on CPU cores

timescaledb:
  deploy:
    resources:
      limits:
        memory: 8G
  command: postgres -c shared_buffers=2GB -c max_connections=200
```

### Backup Strategy

```bash
# Automated daily backups
crontab -e

# Add this line:
0 2 * * * cd /path/to/Invest_manager && docker-compose exec -T timescaledb pg_dump -U nifty_trader nifty_trading | gzip > backups/backup_$(date +\%Y\%m\%d).sql.gz
```

## Scaling

### Horizontal Scaling

```bash
# Scale backend replicas
docker-compose up -d --scale backend=3

# Add load balancer (nginx)
# See docker-compose.prod.yml
```

### Vertical Scaling

Edit resource limits in docker-compose.yml or use docker-compose.override.yml

## Maintenance

### Regular Tasks

- **Daily**: Check logs for errors
- **Weekly**: Review resource usage, backup verification
- **Monthly**: Update dependencies, security patches

### Updates

```bash
# Update Docker images
docker-compose pull

# Update Python dependencies
docker-compose exec backend pip list --outdated

# Update Node.js dependencies
docker-compose exec frontend npm outdated
```

## Support

For issues:
1. Check logs: `docker-compose logs`
2. Review health checks
3. Check [GitHub Issues](https://github.com/ramc2012/Invest_manager/issues)
4. Read [Troubleshooting Guide](docs/troubleshooting.md)
