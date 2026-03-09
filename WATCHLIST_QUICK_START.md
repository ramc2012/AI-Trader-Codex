# 🚀 Watchlist API - Quick Start Guide

## Getting Started

### Prerequisites
1. Fyers API authentication configured
2. Backend container running: `docker compose up -d backend`
3. API available at: `http://localhost:8000`

## 📋 Quick Reference

### 1. List All Supported Indices

**Request:**
```bash
curl http://localhost:8000/api/v1/watchlist/indices | jq '.'
```

**Response:**
```json
[
  {
    "name": "NIFTY",
    "display_name": "Nifty 50",
    "spot_symbol": "NSE:NIFTY50-INDEX",
    "futures_symbol": "NSE:NIFTY25FEBFUT",
    "sector": "Broad Market",
    "lot_size": 25
  },
  {
    "name": "BANKNIFTY",
    "display_name": "Bank Nifty",
    "spot_symbol": "NSE:NIFTYBANK-INDEX",
    "futures_symbol": "NSE:BANKNIFTY25FEBFUT",
    "sector": "Banking",
    "lot_size": 15
  }
  // ... FINNIFTY, MIDCPNIFTY, SENSEX
]
```

### 2. Get Real-time Quote

**Request:**
```bash
curl http://localhost:8000/api/v1/watchlist/quote/NSE:NIFTY50-INDEX | jq '.'
```

**Response:**
```json
{
  "symbol": "NSE:NIFTY50-INDEX",
  "name": "Nifty 50",
  "ltp": 21500.00,
  "open": 21450.00,
  "high": 21550.00,
  "low": 21400.00,
  "close": 21480.00,
  "volume": 5000000,
  "change": 20.00,
  "change_pct": 0.09,
  "timestamp": "2026-02-13T19:30:00"
}
```

### 3. Get Historical OHLC Data

**Request:**
```bash
# Last 30 days of daily data
curl "http://localhost:8000/api/v1/watchlist/historical/NSE:NIFTY50-INDEX?days=30&resolution=D" | jq '.data[0:3]'

# Last 5 days of 15-minute data
curl "http://localhost:8000/api/v1/watchlist/historical/NSE:NIFTY50-INDEX?days=5&resolution=15" | jq '.data[0:3]'
```

**Response:**
```json
{
  "symbol": "NSE:NIFTY50-INDEX",
  "resolution": "D",
  "from_date": "2026-01-14T00:00:00",
  "to_date": "2026-02-13T00:00:00",
  "count": 23,
  "data": [
    {
      "timestamp": "2026-01-14T09:15:00",
      "open": 21450.00,
      "high": 21550.00,
      "low": 21400.00,
      "close": 21500.00,
      "volume": 5000000
    }
    // ... more candles
  ]
}
```

**Supported Resolutions:**
- `D` - Daily
- `60` - 1 Hour
- `30` - 30 Minutes
- `15` - 15 Minutes
- `5` - 5 Minutes
- `1` - 1 Minute

### 4. Get Watchlist Summary (All Indices)

**Request:**
```bash
curl http://localhost:8000/api/v1/watchlist/summary | jq '.'
```

**Response:**
```json
{
  "timestamp": "2026-02-13T19:30:00",
  "total_count": 5,
  "indices": [
    {
      "name": "NIFTY",
      "display_name": "Nifty 50",
      "spot": {
        "symbol": "NSE:NIFTY50-INDEX",
        "ltp": 21500.00,
        "change_pct": 0.09
      },
      "futures": {
        "symbol": "NSE:NIFTY25FEBFUT",
        "ltp": 21520.00,
        "oi": 2500000
      }
    }
    // ... other indices
  ]
}
```

### 5. Calculate Option Greeks

**Request:**
```bash
# ATM Call Option, 7 DTE, 15% IV
curl "http://localhost:8000/api/v1/watchlist/options/greeks?spot=21500&strike=21500&days_to_expiry=7&volatility=0.15&option_type=CE" | jq '.'

# OTM Put Option, 14 DTE, 18% IV
curl "http://localhost:8000/api/v1/watchlist/options/greeks?spot=21500&strike=21000&days_to_expiry=14&volatility=0.18&option_type=PE" | jq '.'
```

**Response:**
```json
{
  "spot": 21500.0,
  "strike": 21500.0,
  "time_to_expiry_days": 7,
  "volatility": 0.15,
  "option_type": "CE",
  "delta": 0.5299,
  "gamma": 0.0009,
  "theta": -14.84,
  "vega": 11.84,
  "rho": 2.15
}
```

**Greeks Interpretation:**
- **Delta (0.5299):** 53% chance of expiring ITM, moves ₹0.53 per ₹1 spot move
- **Gamma (0.0009):** Delta changes by 0.0009 per ₹1 spot move
- **Theta (-14.84):** Loses ₹14.84 per day due to time decay
- **Vega (11.84):** Gains ₹11.84 per 1% increase in IV
- **Rho (2.15):** Gains ₹2.15 per 1% increase in interest rate

### 6. Get Options Chain

**Request:**
```bash
curl http://localhost:8000/api/v1/watchlist/options/chain/NIFTY | jq '.data.expiryData[0]'

curl http://localhost:8000/api/v1/watchlist/options/chain/BANKNIFTY | jq '.data.expiryData[0]'
```

**Response:**
```json
{
  "data": {
    "expiryData": [
      {
        "expiry": "2026-02-20",
        "strikes": [
          {
            "strike": 21000,
            "ce": {
              "symbol": "NSE:NIFTY2620021000CE",
              "ltp": 550.00,
              "iv": 15.5,
              "oi": 1000000,
              "volume": 50000
            },
            "pe": {
              "symbol": "NSE:NIFTY2620021000PE",
              "ltp": 25.00,
              "iv": 16.2,
              "oi": 800000,
              "volume": 30000
            }
          }
          // ... more strikes
        ]
      }
      // ... more expiries
    ]
  }
}
```

### 7. Test Data Availability

**Request:**
```bash
curl http://localhost:8000/api/v1/watchlist/test-data | jq '.summary'
```

**Response:**
```json
{
  "timestamp": "2026-02-13T19:30:00",
  "summary": {
    "total_indices": 5,
    "spot_data_available": 5,
    "futures_data_available": 5,
    "historical_data_available": 5
  },
  "indices": {
    "NIFTY": {
      "spot": {
        "symbol": "NSE:NIFTY50-INDEX",
        "available": true,
        "ltp": 21500.00
      },
      "futures": {
        "symbol": "NSE:NIFTY25FEBFUT",
        "available": true,
        "ltp": 21520.00,
        "oi": 2500000
      },
      "historical": {
        "available": true,
        "days": 30,
        "from": "2026-01-14",
        "to": "2026-02-13"
      }
    }
    // ... other indices
  }
}
```

## 🎯 Common Use Cases

### Use Case 1: Get Current Market Overview

```bash
# Get all indices with current prices
curl http://localhost:8000/api/v1/watchlist/summary | \
  jq '.indices[] | {name: .display_name, ltp: .spot.ltp, change: .spot.change_pct}'
```

### Use Case 2: Fetch Data for Technical Analysis

```bash
# Get 90 days of daily data for indicator calculation
curl "http://localhost:8000/api/v1/watchlist/historical/NSE:NIFTY50-INDEX?days=90&resolution=D" | \
  jq '.data[] | {date: .timestamp, close: .close, volume: .volume}' > nifty_data.json
```

### Use Case 3: Calculate Greeks for Option Strategy

```bash
# Long Straddle: ATM Call + ATM Put
SPOT=21500
STRIKE=21500
DTE=7
IV=0.15

# Call Greeks
curl -s "http://localhost:8000/api/v1/watchlist/options/greeks?spot=$SPOT&strike=$STRIKE&days_to_expiry=$DTE&volatility=$IV&option_type=CE" | \
  jq '{call_delta: .delta, call_theta: .theta, call_vega: .vega}'

# Put Greeks
curl -s "http://localhost:8000/api/v1/watchlist/options/greeks?spot=$SPOT&strike=$STRIKE&days_to_expiry=$DTE&volatility=$IV&option_type=PE" | \
  jq '{put_delta: .delta, put_theta: .theta, put_vega: .vega}'
```

### Use Case 4: Monitor Intraday Price Action

```bash
# Get last 1 day of 5-minute candles
curl "http://localhost:8000/api/v1/watchlist/historical/NSE:NIFTY50-INDEX?days=1&resolution=5" | \
  jq '.data[-10:] | .[] | {time: .timestamp, close: .close, volume: .volume}'
```

### Use Case 5: Compare Spot vs Futures

```bash
# Get spot and futures quotes
curl http://localhost:8000/api/v1/watchlist/summary | \
  jq '.indices[] | {
    name: .display_name,
    spot_ltp: .spot.ltp,
    futures_ltp: .futures.ltp,
    premium: (.futures.ltp - .spot.ltp),
    premium_pct: ((.futures.ltp - .spot.ltp) / .spot.ltp * 100)
  }'
```

## 🧪 Testing in Python

```python
import requests
import pandas as pd

BASE_URL = "http://localhost:8000/api/v1"

# 1. Get all indices
response = requests.get(f"{BASE_URL}/watchlist/indices")
indices = response.json()
print(f"Found {len(indices)} indices")

# 2. Get historical data
response = requests.get(
    f"{BASE_URL}/watchlist/historical/NSE:NIFTY50-INDEX",
    params={"days": 30, "resolution": "D"}
)
data = response.json()
df = pd.DataFrame(data["data"])
df['timestamp'] = pd.to_datetime(df['timestamp'])
print(df.tail())

# 3. Calculate option Greeks
response = requests.get(
    f"{BASE_URL}/watchlist/options/greeks",
    params={
        "spot": 21500,
        "strike": 21500,
        "days_to_expiry": 7,
        "volatility": 0.15,
        "option_type": "CE"
    }
)
greeks = response.json()
print(f"Delta: {greeks['delta']:.4f}")
print(f"Theta: {greeks['theta']:.2f}")
print(f"Vega: {greeks['vega']:.2f}")

# 4. Get options chain
response = requests.get(f"{BASE_URL}/watchlist/options/chain/NIFTY")
chain = response.json()
print(f"Expiries: {len(chain['data']['expiryData'])}")
```

## 📊 API Documentation

**Interactive API Docs:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🔍 Troubleshooting

### Common Issues

**1. 404 Not Found**
```bash
# Verify backend is running
docker compose ps backend

# Check logs
docker compose logs backend | tail -20
```

**2. Authentication Required**
```bash
# Check Fyers auth status
curl http://localhost:8000/api/v1/auth/status
```

**3. No Historical Data**
```bash
# Test data availability
curl http://localhost:8000/api/v1/watchlist/test-data | jq '.summary'
```

## 📚 Additional Resources

- **Full Documentation:** `WATCHLIST_IMPLEMENTATION.md`
- **Completion Summary:** `WATCHLIST_COMPLETE.md`
- **API Schema:** http://localhost:8000/openapi.json

---

**Quick Start Guide** | Last Updated: February 13, 2026
