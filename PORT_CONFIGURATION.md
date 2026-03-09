# Port Configuration - No More Conflicts! 🎯

## ✅ Updated Port Assignments

To avoid conflicts with other running services, all ports have been configured via environment variables:

### Production Ports (Current)
```
Frontend:      http://localhost:3100  (was 3000)
Backend API:   http://localhost:8000  (no change)
TimescaleDB:   localhost:5433         (was 5432)
Redis:         localhost:6379         (no change)
```

### Why Change Ports?

**Before:**
- Port 3000: Conflict with `trading-frontend` container
- Port 5432: Conflict with local PostgreSQL installation
- Services failed to start due to "port already allocated" errors

**After:**
- Port 3100: Frontend runs without conflicts
- Port 5433: Database runs without conflicts
- All services start cleanly

---

## 🔧 Configuration Files Updated

### 1. `.env` File
Added port configuration section:

```bash
# -----------------------------------------------------------------------------
# Docker Port Configuration (to avoid conflicts with other services)
# -----------------------------------------------------------------------------
FRONTEND_PORT=3100
# DB_PORT uses 5433 externally to avoid conflict with local postgres on 5432

# -----------------------------------------------------------------------------
# Database Configuration
# -----------------------------------------------------------------------------
DB_HOST=localhost
DB_PORT=5433
DB_NAME=nifty_trader
DB_USER=trader
DB_PASSWORD=change_me_in_production
```

### 2. `docker-compose.yml`
Already configured to use environment variables:

```yaml
frontend:
  ports:
    - "${FRONTEND_PORT:-3000}:3000"  # Now uses FRONTEND_PORT=3100

timescaledb:
  ports:
    - "${DB_PORT:-5432}:5432"  # Now uses DB_PORT=5433
```

---

## 🚀 How to Access

### Main Application
```bash
# Fyers-Style Indices Dashboard
http://localhost:3100/indices

# Dashboard Overview
http://localhost:3100/

# Positions
http://localhost:3100/positions

# Strategies
http://localhost:3100/strategies

# Risk Management
http://localhost:3100/risk

# Settings (Fyers Auth)
http://localhost:3100/settings
```

### Backend API
```bash
# API Documentation
http://localhost:8000/docs

# Health Check
http://localhost:8000/api/v1/health

# Watchlist API
http://localhost:8000/api/v1/watchlist/indices
```

### Database Connection
```bash
# From host machine
psql -h localhost -p 5433 -U trader -d nifty_trader

# From within Docker network
psql -h timescaledb -p 5432 -U trader -d nifty_trader
```

---

## 📝 Service Status

All services are now running healthy:

```
NAME                STATUS                  PORTS
nifty-frontend      Up (healthy)            0.0.0.0:3100->3000/tcp
nifty-backend       Up (healthy)            0.0.0.0:8000->8000/tcp
nifty-timescaledb   Up (healthy)            0.0.0.0:5433->5432/tcp
nifty-redis         Up (healthy)            0.0.0.0:6379->6379/tcp
```

---

## 🔄 Changing Ports in Future

### To change any port:

1. **Edit `.env` file:**
   ```bash
   FRONTEND_PORT=3200  # Change to any available port
   DB_PORT=5434        # Change to any available port
   APP_PORT=8001       # Change backend port if needed
   ```

2. **Restart services:**
   ```bash
   docker compose down
   docker compose up -d
   ```

3. **Verify new ports:**
   ```bash
   docker compose ps
   ```

### Port Selection Guidelines:
- **Frontend**: Use 3000-3999 range
- **Backend**: Use 8000-8999 range
- **Database**: Use 5432-5439 range
- **Redis**: Use 6379-6389 range

Always check for conflicts first:
```bash
lsof -i :3100  # Check if port is free
```

---

## 🎯 Key Benefits

1. **No More Conflicts**: Services can coexist with other projects
2. **Flexible Configuration**: Easy to change ports via `.env`
3. **Consistent Approach**: All ports managed in one place
4. **Docker Best Practice**: Using environment variables for configuration
5. **Development Friendly**: Can run multiple projects simultaneously

---

## 🐛 Troubleshooting

### Frontend not accessible on 3100?
```bash
# Check if frontend is running
docker compose logs frontend --tail 20

# Check if port is actually bound
lsof -i :3100

# Restart frontend only
docker compose restart frontend
```

### Backend API not responding?
```bash
# Check backend logs
docker compose logs backend --tail 20

# Test health endpoint
curl http://localhost:8000/api/v1/health
```

### Database connection refused?
```bash
# Check if TimescaleDB is healthy
docker compose ps timescaledb

# Check database logs
docker compose logs timescaledb --tail 20

# Test connection
pg_isready -h localhost -p 5433
```

---

## 📊 Complete System Map

```
┌─────────────────────────────────────────────────────────┐
│                    User's Browser                        │
│                                                          │
│  http://localhost:3100 (Indices Dashboard)              │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│              nifty-frontend (Port 3100)                  │
│                  Next.js 16.1.6                         │
│                                                          │
│  • Fyers-style layout                                   │
│  • Top navigation tabs                                  │
│  • 3-column data display                                │
│  • Real-time updates (3s polling)                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼ API Proxy (/api/v1/*)
┌─────────────────────────────────────────────────────────┐
│              nifty-backend (Port 8000)                   │
│                  FastAPI + Uvicorn                      │
│                                                          │
│  • REST API endpoints                                   │
│  • WebSocket support                                    │
│  • Automatic data collection                            │
│  • Fyers API integration                                │
└────────┬────────────────────────────────┬───────────────┘
         │                                │
         ▼                                ▼
┌────────────────────┐         ┌─────────────────────────┐
│ nifty-timescaledb  │         │    nifty-redis          │
│   (Port 5433)      │         │    (Port 6379)          │
│                    │         │                         │
│ • OHLC candles     │         │ • Session cache         │
│ • Tick data        │         │ • Fyers tokens          │
│ • Historical data  │         │ • Task queue            │
└────────────────────┘         └─────────────────────────┘
```

---

## ✅ Verification Checklist

- [x] Frontend accessible at http://localhost:3100
- [x] Backend API responding at http://localhost:8000
- [x] TimescaleDB running on port 5433
- [x] Redis running on port 6379
- [x] All containers healthy
- [x] No port conflicts
- [x] `.env` file updated with new ports
- [x] Documentation updated

---

**Updated**: 2026-02-13
**Status**: ✅ All services running on conflict-free ports
**Frontend URL**: http://localhost:3100/indices
