# 🚀 Quick Start Guide - Nifty AI Trader

## ✅ Repository Successfully Created!

**GitHub Repository**: https://github.com/ramc2012/Invest_manager

---

## 🎯 What's Running Now

Your Nifty AI Trader is now deployed and running with Docker!

### Running Services:
- ✅ **Backend API**: http://localhost:8000
- ✅ **TimescaleDB**: localhost:5432
- ✅ **Redis**: localhost:6379
- ⏸️ **Frontend**: Not built (build error - can be fixed separately)

### Service Status:
```bash
$ docker-compose ps
NAME                IMAGE                               STATUS
nifty-backend       nifty-ai-trader-backend             Up (healthy)
nifty-redis         redis:7-alpine                      Up (healthy)
nifty-timescaledb   timescale/timescaledb:latest-pg15   Up (healthy)
```

---

## 🔗 Access Points

### Backend API
- **Health Check**: http://localhost:8000/api/v1/health
- **API Documentation**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Database
```bash
# Connect to TimescaleDB
docker-compose exec timescaledb psql -U nifty_trader -d nifty_trading

# Example query
SELECT * FROM ohlc_data LIMIT 10;
```

### Redis
```bash
# Connect to Redis
docker-compose exec redis redis-cli

# Test Redis
PING
```

---

## 📋 Next Steps

### 1. Configure Fyers API Credentials

```bash
# Edit .env file
nano .env

# Add your Fyers credentials:
FYERS_APP_ID=your_app_id_here
FYERS_SECRET_KEY=your_secret_key_here
FYERS_REDIRECT_URI=http://localhost:3000/api/auth/callback
```

### 2. Test Authentication

```bash
# Get login URL
curl http://localhost:8000/api/v1/auth/login-url

# Check auth status
curl http://localhost:8000/api/v1/auth/status
```

### 3. Collect Historical Data

```bash
# Collect 90 days of daily OHLC data
curl -X POST http://localhost:8000/api/v1/watchlist/collect \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "NSE:NIFTY50-INDEX",
    "timeframe": "D",
    "days_back": 90
  }'
```

### 4. View Available Endpoints

Visit http://localhost:8000/docs to see all available API endpoints.

---

## 🛠️ Common Commands

### Managing Services

```bash
# Stop all services
docker-compose stop

# Start all services
docker-compose start

# Restart services
docker-compose restart

# View logs
docker-compose logs -f backend

# Check service status
docker-compose ps
```

### Database Operations

```bash
# Access database shell
docker-compose exec timescaledb psql -U nifty_trader -d nifty_trading

# Backup database
docker-compose exec timescaledb pg_dump -U nifty_trader nifty_trading > backup.sql

# View database logs
docker-compose logs timescaledb
```

### Development

```bash
# Run tests
docker-compose exec backend pytest tests/ -v

# Access backend shell
docker-compose exec backend bash

# Check Python dependencies
docker-compose exec backend pip list
```

---

## 📊 Test the System

### 1. Health Check
```bash
curl http://localhost:8000/api/v1/health
# Expected: {"status":"healthy","database":true,"version":"0.1.0"}
```

### 2. Get Available Symbols
```bash
curl http://localhost:8000/api/v1/symbols
```

### 3. Get Watchlist
```bash
curl http://localhost:8000/api/v1/watchlist/symbols
```

### 4. Check System Monitoring
```bash
curl http://localhost:8000/api/v1/monitoring/health
```

---

## 🐛 Troubleshooting

### Backend not responding?
```bash
# Check backend logs
docker-compose logs backend

# Restart backend
docker-compose restart backend
```

### Database connection errors?
```bash
# Check if database is healthy
docker-compose ps timescaledb

# Check database logs
docker-compose logs timescaledb

# Verify credentials in .env
cat .env | grep DB_
```

### Port already in use?
```bash
# Check what's using the port
lsof -i :8000

# Change port in .env
APP_PORT=8001
```

---

## 📖 Documentation

- **Full Deployment Guide**: See [DEPLOYMENT.md](DEPLOYMENT.md)
- **API Documentation**: http://localhost:8000/docs
- **Project README**: See [README.md](README.md)
- **GitHub Repository**: https://github.com/ramc2012/Invest_manager

---

## 🎓 Learning Resources

### Key Files to Explore:
- `src/api/main.py` - FastAPI application entry point
- `src/data/collectors/` - Data collection modules
- `src/strategies/` - Trading strategies
- `src/risk/` - Risk management
- `tests/` - Test suite (723 tests)

### API Endpoints to Try:
1. Authentication: `/api/v1/auth/`
2. Market Data: `/api/v1/ohlc/`
3. Watchlist: `/api/v1/watchlist/`
4. Trading: `/api/v1/positions/`, `/api/v1/orders/`
5. Strategies: `/api/v1/strategies/`
6. Monitoring: `/api/v1/monitoring/`

---

## 🚀 Production Deployment

For production deployment with frontend and additional features:

1. **Fix frontend build** (optional - can use backend-only)
2. **Configure SSL/TLS**
3. **Set up monitoring** (Prometheus/Grafana)
4. **Enable backups**
5. **Configure secrets management**

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed production setup.

---

## 📞 Support

- **GitHub Issues**: https://github.com/ramc2012/Invest_manager/issues
- **Documentation**: Check docs/ directory
- **Logs**: `docker-compose logs -f`

---

## ✨ What's Included

### Backend Features:
- ✅ FastAPI REST API
- ✅ Real-time data collection
- ✅ 30+ technical indicators
- ✅ Multiple trading strategies
- ✅ Risk management system
- ✅ Order management (paper & live)
- ✅ Backtesting engine
- ✅ Comprehensive monitoring
- ✅ 723 automated tests

### Infrastructure:
- ✅ TimescaleDB (time-series database)
- ✅ Redis (caching & message broker)
- ✅ Docker containerization
- ✅ Health checks
- ✅ Structured logging
- ✅ Database migrations

---

## 🎉 You're All Set!

Your Nifty AI Trader is now running in Docker. Start exploring the API at:
**http://localhost:8000/docs**

**Next**: Configure your Fyers API credentials and start collecting data!

---

**Built with ❤️ for algorithmic traders**
