# Nifty AI Trader iOS App

This folder contains a separate SwiftUI iOS client for the existing FastAPI backend.

What it covers:

- Login and token lifecycle for Fyers
- Watchlist monitoring
- Open positions
- Portfolio summary and instrument contribution
- AI agent runtime status, controls, and recent events
- In-app Fyers OAuth launch using Safari, with manual redirect URL or `auth_code` submission back to the backend

Default backend URL:

- `http://127.0.0.1:8000` for a locally started FastAPI server
- `http://127.0.0.1:8201` for the current Docker-backed workspace stack

For a physical device, change the URL in the Login tab to your Mac's LAN IP, for example `http://192.168.1.12:8201`.

Build from the repo root:

```bash
xcodebuild -project "ios/NiftyAITraderMobile.xcodeproj" -target NiftyAITraderMobile -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO build
```
