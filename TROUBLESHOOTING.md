# Troubleshooting Guide

## Docker Port Conflicts and API Issues

### Issue: Backend Port 8000 Already Allocated

**Symptoms:**
- Error: `Bind for 0.0.0.0:8000 failed: port is already allocated`
- Backend container fails to start
- Frontend cannot connect to backend API

**Solution 1: Restart Docker Desktop (Recommended)**
1. Click the Docker Desktop icon in your menu bar
2. Select "Quit Docker Desktop"
3. Wait 10-15 seconds
4. Open Docker Desktop from Applications
5. Wait for Docker to fully start (whale icon should be steady)
6. Run: `cd /Users/chinnadurairamachandran/Downloads/nifty-ai-trader`
7. Run: `docker-compose up -d timescaledb redis backend`
8. Verify: `curl http://localhost:8000/api/v1/health`

**Solution 2: Use Different Port**
If port 8000 is genuinely used by another application:

1. Check what's using the port:
   ```bash
   lsof -i :8000
   ```

2. Edit `.env` file and change the port:
   ```bash
   APP_PORT=8001
   ```

3. Restart services:
   ```bash
   docker-compose down
   docker-compose up -d timescaledb redis backend
   ```

4. Update frontend environment to use new port:
   ```bash
   cd frontend
   # Edit .env.local and change API_URL to http://localhost:8001
   ```

### Issue: Docker API Returns 500 Internal Server Error

**Symptoms:**
- `request returned 500 Internal Server Error for API route`
- Docker commands hang or fail
- Docker Desktop icon may show "starting" state

**Solution:**
1. **Force quit Docker Desktop:**
   ```bash
   killall Docker
   ```

2. **Clear Docker socket:**
   ```bash
   rm -f ~/Library/Containers/com.docker.docker/Data/docker.sock
   rm -f ~/.docker/run/docker.sock
   ```

3. **Restart Docker Desktop from Applications folder**
   - Open Finder → Applications
   - Double-click Docker
   - Wait 30-40 seconds for full startup

4. **Verify Docker is running:**
   ```bash
   docker info
   ```

### Issue: Frontend Shows "No queryFn was passed" Error

**Symptoms:**
- Console error: `No queryFn was passed as an option, and no default queryFn was found`
- Frontend pages show loading state indefinitely
- Safari/browser shows "can't connect to server"

**Root Cause:**
Backend API is not running or not accessible.

**Solution:**
1. **Check backend status:**
   ```bash
   docker-compose ps backend
   ```

2. **Check backend logs:**
   ```bash
   docker-compose logs backend --tail 50
   ```

3. **Verify backend health:**
   ```bash
   curl http://localhost:8000/api/v1/health
   ```
   Expected response: `{"status":"healthy","database":true,"version":"0.1.0"}`

4. **If backend is not running:**
   ```bash
   docker-compose up -d backend
   ```

5. **Refresh frontend:**
   - Refresh browser (Cmd+R or F5)
   - Clear browser cache if needed (Cmd+Shift+R)

### Issue: Backend Container Keeps Stopping

**Symptoms:**
- Backend starts but stops after a few seconds
- `docker-compose ps` shows backend as "Exited"

**Solution:**
1. **Check backend logs for errors:**
   ```bash
   docker-compose logs backend --tail 100
   ```

2. **Common causes:**
   - Database not ready: Wait for TimescaleDB to be healthy
   - Configuration error: Check `.env` file has all required variables
   - Port conflict: Follow "Backend Port Already Allocated" solution above

3. **Restart with fresh database connection:**
   ```bash
   docker-compose restart timescaledb redis
   sleep 10
   docker-compose up -d backend
   ```

### Issue: Frontend Not Loading or Showing Blank Page

**Symptoms:**
- Browser shows blank page
- localhost:3000 not responding
- Frontend dev server not running

**Solution:**
1. **Check if frontend dev server is running:**
   ```bash
   ps aux | grep "next dev"
   ```

2. **Restart frontend:**
   ```bash
   cd /Users/chinnadurairamachandran/Downloads/nifty-ai-trader/frontend
   npm run dev
   ```

3. **Check for port conflicts:**
   ```bash
   lsof -i :3000
   ```

4. **If port 3000 is in use, kill the process:**
   ```bash
   kill -9 $(lsof -t -i:3000)
   npm run dev
   ```

## Quick Status Check Commands

```bash
# Check all container status
docker-compose ps

# Check backend health
curl http://localhost:8000/api/v1/health

# Check frontend (should return HTML)
curl http://localhost:3000

# View all service logs
docker-compose logs --tail 20

# View specific service logs
docker-compose logs backend --tail 50
docker-compose logs timescaledb --tail 50
docker-compose logs redis --tail 50
```

## Complete Reset (Nuclear Option)

If nothing else works:

```bash
# Stop all services
docker-compose down

# Remove all volumes (WARNING: Deletes all data!)
docker-compose down -v

# Clean Docker system
docker system prune -a --volumes

# Restart Docker Desktop manually

# Rebuild and start
docker-compose build --no-cache
docker-compose up -d
```

## Getting Help

1. Check logs: `docker-compose logs --tail 100`
2. Check GitHub issues: https://github.com/ramc2012/Invest_manager/issues
3. Review DEPLOYMENT.md for setup instructions
4. Review QUICK_START.md for access URLs
