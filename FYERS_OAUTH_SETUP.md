# Fyers OAuth Setup - Critical Configuration Required

## ⚠️ Important: Redirect URI Mismatch Detected

Your current OAuth flow is not working because the redirect URI in your Fyers App Dashboard doesn't match the callback URL in your application.

### Current Issue:
- **Fyers Dashboard Redirect URI**: `https://trade.fyers.in/api-login/redirect-uri/index.html` (Fyers default)
- **Application Callback URL**: `http://localhost:8000/api/v1/auth/callback` (Our backend)
- **Problem**: When you authorize, Fyers redirects to their default page instead of our backend

### Solution: Update Fyers App Dashboard

You need to update the Redirect URL in your Fyers App Dashboard to point to our backend callback.

## Step-by-Step Fix

### 1. Go to Fyers API Dashboard
Open: https://myapi.fyers.in/dashboard

### 2. Find Your App
- App ID: `XV2TQDA5K4-100`
- Click on your app to edit it

### 3. Update Redirect URL
**Change the Redirect URL to:**
```
http://localhost:8000/api/v1/auth/callback
```

**Important Notes:**
- ✅ Use `http://` (not `https://`) for localhost
- ✅ Include the full path `/api/v1/auth/callback`
- ✅ Port must be `8000` (backend port)
- ❌ Do NOT use `https://trade.fyers.in/api-login/redirect-uri/index.html`

### 4. Save Changes
Click "Save" or "Update" in the Fyers dashboard.

## After Updating Fyers Dashboard

### Test the OAuth Flow:

1. **Go to Settings**: http://localhost:3100/settings

2. **Disconnect** (if currently connected):
   - Click "Disconnect from Fyers" button

3. **Connect to Fyers**:
   - Click "Connect to Fyers" button
   - You'll be redirected to Fyers authorization page
   - Enter your Fyers credentials and authorize

4. **Automatic Redirect**:
   - After authorization, Fyers will redirect to: `http://localhost:8000/api/v1/auth/callback?auth_code=XXX`
   - Backend exchanges auth code for tokens (access token + refresh token)
   - Backend redirects you back to: `http://localhost:3100/settings?auth=success`
   - You should see success message: "Authentication successful!"

5. **Token Status Section Appears**:
   - Token Status section will now be visible
   - Shows access token expiry (24 hours)
   - Shows refresh token expiry (15 days)
   - PIN input for quick refresh

## Alternative: Manual Auth Code Entry (If You Can't Change Redirect URI)

If you cannot change the redirect URI in Fyers dashboard (e.g., production restrictions), we can implement a manual auth code input flow:

1. User clicks "Connect to Fyers"
2. Fyers redirects to default page with auth code displayed
3. User copies auth code
4. User pastes auth code in Settings page input field
5. Frontend sends auth code to backend
6. Backend exchanges code for tokens

**Let me know if you need this alternative implementation.**

## Current Configuration

### .env File (Already Updated):
```bash
FYERS_APP_ID=XV2TQDA5K4-100
FYERS_SECRET_KEY=5RD4GL5PCZ
FYERS_REDIRECT_URI=http://localhost:8000/api/v1/auth/callback
FYERS_REDIRECT_FRONTEND_URL=http://localhost:3100/settings
```

### Backend Callback Endpoint:
- URL: `http://localhost:8000/api/v1/auth/callback`
- Accepts: `?auth_code=XXX&s=ok`
- Returns: Redirect to Settings page with `?auth=success` or `?auth=failed`

## Troubleshooting

### "Invalid redirect URI" error from Fyers
→ The redirect URI in Fyers dashboard doesn't match the one in .env
→ Update Fyers dashboard to use `http://localhost:8000/api/v1/auth/callback`

### Redirects to Fyers default page showing auth code
→ Redirect URI is still set to `https://trade.fyers.in/api-login/redirect-uri/index.html`
→ Update in Fyers dashboard

### "Connection refused" after authorization
→ Backend is not running or port 8000 is blocked
→ Check backend: `docker compose ps backend`

### Redirect works but shows "Authentication failed"
→ Check backend logs: `docker compose logs backend --tail 50`
→ Auth code might have expired (valid for 5 minutes only)

## Production Deployment

For production, you'll need to:
1. Use a public domain: `https://yourdomain.com/api/v1/auth/callback`
2. Update Fyers dashboard with production redirect URI
3. Update .env with production URLs
4. Use HTTPS (required by Fyers for non-localhost)

---

**Next Step**: Update the Redirect URL in your Fyers App Dashboard, then try the OAuth flow again!
