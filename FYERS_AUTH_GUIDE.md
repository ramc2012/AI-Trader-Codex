# Fyers Authentication Setup Guide

This guide explains how to set up Fyers API authentication using the intuitive web interface - no manual configuration file editing required!

## Quick Start (Recommended)

### Step 1: Get Your Fyers API Credentials

1. Visit the [Fyers API Portal](https://myapi.fyers.in/dashboard)
2. Log in with your Fyers account
3. Create a new app or use an existing one
4. Note down:
   - **App ID** (e.g., `ABC123XYZ-100`)
   - **Secret Key** (keep this secure!)
5. In your app settings, add this redirect URI:
   ```
   http://localhost:8000/api/v1/auth/callback
   ```

### Step 2: Enter Credentials in the Web Interface

1. Start the application:
   ```bash
   docker compose up -d
   ```

2. Open the frontend: http://localhost:3000

3. Navigate to **Settings** page (click Settings in sidebar)

4. You'll see the Fyers API credentials form automatically

5. Fill in the form:
   - **Fyers App ID**: Your app ID from Step 1
   - **Fyers Secret Key**: Your secret key from Step 1
   - **Redirect URI**: Leave as default (`http://localhost:8000/api/v1/auth/callback`)

6. Click **"Save & Login"** button

7. A new browser tab will open with Fyers login page

8. Log in with your Fyers credentials and authorize the app

9. You'll be redirected back to the Settings page with a success message

10. Done! You're now authenticated with Fyers ✅

## Features

### 🔐 Automatic Credential Management
- Credentials are automatically saved to `.env` file
- Backup `.env.backup` file created before any updates
- No manual file editing required
- No backend restart needed

### ✅ Real-time Validation
- Click "Validate Only" to test credentials without saving
- Instant feedback on credential validity
- Shows login URL if credentials are valid

### 🔄 One-Click Login Flow
- "Save & Login" button handles everything:
  1. Saves credentials to `.env`
  2. Validates credentials
  3. Opens Fyers OAuth login page
  4. Redirects back after authentication

### 👁️ Security Features
- Secret key hidden by default (toggle to show)
- Secret key never displayed in API responses
- Credentials validated before saving
- OAuth token stored securely on backend

### 📝 Update Anytime
- "Update Credentials" button available when configured
- Can change credentials without disconnecting
- Previous values backed up automatically

## API Endpoints

The following REST API endpoints are available for credential management:

### 1. Get Current Credentials
```bash
GET /api/v1/auth/credentials
```

Response:
```json
{
  "app_id": "ABC123XYZ-100",
  "redirect_uri": "http://localhost:8000/api/v1/auth/callback",
  "configured": true
}
```

**Note:** Secret key is never exposed in responses for security.

### 2. Save Credentials
```bash
POST /api/v1/auth/credentials
Content-Type: application/json

{
  "app_id": "ABC123XYZ-100",
  "secret_key": "your-secret-key",
  "redirect_uri": "http://localhost:8000/api/v1/auth/callback"
}
```

Response:
```json
{
  "app_id": "ABC123XYZ-100",
  "redirect_uri": "http://localhost:8000/api/v1/auth/callback",
  "configured": true
}
```

### 3. Validate Credentials
```bash
POST /api/v1/auth/validate
Content-Type: application/json

{
  "app_id": "ABC123XYZ-100",
  "secret_key": "your-secret-key",
  "redirect_uri": "http://localhost:8000/api/v1/auth/callback"
}
```

Response:
```json
{
  "valid": true,
  "message": "Credentials are valid",
  "login_url": "https://api.fyers.in/api/v2/generate-authcode?..."
}
```

### 4. Save and Login (Convenience Endpoint)
```bash
POST /api/v1/auth/save-and-login
Content-Type: application/json

{
  "app_id": "ABC123XYZ-100",
  "secret_key": "your-secret-key",
  "redirect_uri": "http://localhost:8000/api/v1/auth/callback"
}
```

Response:
```json
{
  "success": true,
  "message": "Credentials saved successfully",
  "login_url": "https://api.fyers.in/api/v2/generate-authcode?...",
  "next_step": "Open the login_url in a browser to complete authentication"
}
```

### 5. Check Authentication Status
```bash
GET /api/v1/auth/status
```

Response:
```json
{
  "authenticated": true,
  "app_configured": true,
  "profile": {
    "name": "John Doe",
    "email_id": "john@example.com",
    "fy_id": "XYZ12345",
    "broker": "fyers"
  }
}
```

### 6. Logout
```bash
POST /api/v1/auth/logout
```

Response:
```json
{
  "message": "Logged out successfully"
}
```

## Manual Setup (Alternative Method)

If you prefer to configure credentials manually:

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   ```bash
   FYERS_APP_ID=your_app_id_here
   FYERS_SECRET_KEY=your_secret_key_here
   FYERS_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback
   ```

3. Restart the backend:
   ```bash
   docker compose restart backend
   ```

4. Visit http://localhost:3000/settings and click "Connect to Fyers"

## Troubleshooting

### "Invalid credentials" error

**Causes:**
- Incorrect App ID or Secret Key
- App ID doesn't match the format (should be like `ABC123XYZ-100`)
- Credentials contain extra spaces or special characters

**Solution:**
1. Double-check credentials in Fyers API portal
2. Copy-paste carefully to avoid extra characters
3. Use "Validate Only" button to test before saving

### Redirect URI mismatch

**Error:** `redirect_uri_mismatch` or similar OAuth error

**Solution:**
1. Go to Fyers API portal
2. Edit your app settings
3. Add `http://localhost:8000/api/v1/auth/callback` as an authorized redirect URI
4. Save and try again

### Authentication successful but not persisting

**Causes:**
- `.fyers_token.json` file permissions issue
- Backend restarted after authentication

**Solution:**
1. Check backend logs: `docker compose logs backend --tail 50`
2. Ensure backend container has write permissions
3. Re-authenticate if needed

### "App not configured" even after saving credentials

**Causes:**
- Backend didn't reload settings
- `.env` file update failed

**Solution:**
1. Check if `.env` file was updated:
   ```bash
   cat .env | grep FYERS
   ```
2. Check if backup was created:
   ```bash
   ls -la .env.backup
   ```
3. Restart backend:
   ```bash
   docker compose restart backend
   ```

### Can't access Settings page

**Causes:**
- Frontend not running
- Backend not running

**Solution:**
1. Check services:
   ```bash
   docker compose ps
   ```
2. Ensure backend is healthy:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```
3. Ensure frontend is accessible:
   ```bash
   curl -I http://localhost:3000
   ```

## Security Best Practices

### 🔒 Keep Credentials Secure

1. **Never commit `.env` file to git**
   - Already in `.gitignore` by default
   - Check: `git status` should not show `.env`

2. **Rotate credentials regularly**
   - Generate new credentials every 90 days
   - Use "Update Credentials" button to change

3. **Use separate credentials for development/production**
   - Create different apps in Fyers portal
   - Use different App IDs for each environment

4. **Protect `.env.backup` files**
   - Contain same sensitive data as `.env`
   - Delete old backups periodically
   - Add to `.gitignore` if not already there

### 🌐 Production Deployment

For production environments:

1. **Use environment variables instead of `.env` file**
   ```bash
   export FYERS_APP_ID=your_app_id
   export FYERS_SECRET_KEY=your_secret_key
   ```

2. **Update redirect URI for production domain**
   ```bash
   export FYERS_REDIRECT_URI=https://yourdomain.com/api/v1/auth/callback
   ```

3. **Use secrets management service**
   - AWS Secrets Manager
   - HashiCorp Vault
   - Kubernetes Secrets

4. **Enable HTTPS**
   - OAuth requires HTTPS in production
   - Use reverse proxy (nginx, Caddy)
   - Get SSL certificate (Let's Encrypt)

## Advanced Usage

### Using curl to Automate Authentication

1. Save credentials:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/credentials \
     -H "Content-Type: application/json" \
     -d '{
       "app_id": "ABC123XYZ-100",
       "secret_key": "your-secret-key",
       "redirect_uri": "http://localhost:8000/api/v1/auth/callback"
     }'
   ```

2. Get login URL:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/save-and-login \
     -H "Content-Type: application/json" \
     -d '{
       "app_id": "ABC123XYZ-100",
       "secret_key": "your-secret-key",
       "redirect_uri": "http://localhost:8000/api/v1/auth/callback"
     }' | jq -r '.login_url'
   ```

3. Open the returned URL in a browser to complete OAuth

### Programmatic Access

Use the Python API client:

```python
import requests

# Save credentials
response = requests.post(
    "http://localhost:8000/api/v1/auth/credentials",
    json={
        "app_id": "ABC123XYZ-100",
        "secret_key": "your-secret-key",
        "redirect_uri": "http://localhost:8000/api/v1/auth/callback"
    }
)
print(response.json())

# Check status
status = requests.get("http://localhost:8000/api/v1/auth/status")
print(status.json())
```

## FAQs

### Q: Do I need to restart the backend after saving credentials?
**A:** No! Credentials are automatically reloaded. Just save and click "Connect to Fyers".

### Q: Can I use multiple Fyers accounts?
**A:** Only one account can be connected at a time. To switch accounts, disconnect and reconnect with different credentials.

### Q: Where is the OAuth token stored?
**A:** In `.fyers_token.json` file in the project root. This file is automatically managed and should not be edited manually.

### Q: What happens if I delete .fyers_token.json?
**A:** You'll need to re-authenticate by clicking "Connect to Fyers" again. Your API credentials remain saved.

### Q: Can I share my credentials with team members?
**A:** No, credentials are personal. Each team member should create their own Fyers app and use their own credentials.

### Q: Is this secure?
**A:** Yes. Secret keys are never exposed in API responses, credentials are stored locally, and OAuth tokens use industry-standard security.

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review logs: `docker compose logs backend --tail 100`
3. Open an issue on GitHub: https://github.com/ramc2012/Invest_manager/issues
4. Check Fyers API documentation: https://myapi.fyers.in/docsv3

## Next Steps

Once authenticated:

1. **Add Watchlists** - Track your favorite stocks
2. **Collect Market Data** - Start gathering historical and real-time data
3. **Run Backtests** - Test trading strategies on historical data
4. **Enable Live Trading** - Execute trades automatically (use with caution!)

---

**Last Updated:** February 12, 2026
**Version:** 1.0.0
