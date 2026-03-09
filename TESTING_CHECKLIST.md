# 🧪 Bloomberg Terminal Watchlist - Testing Checklist

## Quick Start

1. **Ensure all containers are running:**
```bash
docker compose ps
```
All 4 services should show "Up (healthy)"

2. **Open the application:**
```
http://localhost:3000
```

3. **Authenticate with Fyers (if not already done):**
   - Go to Settings (⚙️ in sidebar)
   - Enter Fyers credentials and authenticate

---

## ✅ Testing Checklist

### Backend API Endpoints

#### Test 1: List All Indices
```bash
curl http://localhost:8000/api/v1/watchlist/indices | jq '.'
```
**Expected:** JSON array with 5 indices (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX)

#### Test 2: Get Watchlist Summary
```bash
curl http://localhost:8000/api/v1/watchlist/summary | jq '.indices[0]'
```
**Expected:** Real-time quotes for all indices with spot and futures data

#### Test 3: Get Historical Data
```bash
curl "http://localhost:8000/api/v1/watchlist/historical/NSE:NIFTY50-INDEX?days=30&resolution=D" | jq '.count'
```
**Expected:** Count of candles (should be ~23 for 30 days)

#### Test 4: Calculate Option Greeks
```bash
curl "http://localhost:8000/api/v1/watchlist/options/greeks?spot=21500&strike=21500&days_to_expiry=7&volatility=0.15&option_type=CE" | jq '.delta'
```
**Expected:** Delta value around 0.53 (ATM call)

#### Test 5: Get Options Chain
```bash
curl "http://localhost:8000/api/v1/watchlist/options/chain/NIFTY" | jq '.data.expiryData | length'
```
**Expected:** Number of available expiries (usually 3-4)

---

### Frontend Pages

#### Page 1: Indices Overview (`/indices`)

**Access:** http://localhost:3000/indices

**Checklist:**
- [ ] Page loads without errors
- [ ] 5 index cards displayed (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX)
- [ ] Each card shows:
  - [ ] Index name and display name
  - [ ] Current LTP (spot price)
  - [ ] Change % in green (positive) or red (negative)
  - [ ] OHLC values (Open, High, Low)
  - [ ] Futures price and premium
  - [ ] Open Interest for futures
  - [ ] Spot volume
- [ ] Market statistics panel shows:
  - [ ] Total Indices: 5
  - [ ] Gainers count
  - [ ] Losers count
  - [ ] Average Change %
- [ ] "Live" indicator pulsing in top-right
- [ ] Data updates automatically (wait 5 seconds, observe changes)
- [ ] Clicking a card navigates to index detail page

**Screenshot Locations:**
- Take screenshot of full page
- Note any visual issues or missing data

---

#### Page 2: Index Detail (`/indices/nifty`)

**Access:** http://localhost:3000/indices/nifty

**Checklist:**
- [ ] Page loads without errors
- [ ] Back button works (returns to /indices)
- [ ] Header shows "Nifty 50" title
- [ ] Current price section shows:
  - [ ] Large LTP display
  - [ ] Change % with up/down arrow
  - [ ] Change amount in INR
  - [ ] OHLC grid (4 cards: Open, High, Low, Close)
- [ ] Futures & Volume section shows:
  - [ ] Futures price
  - [ ] Premium amount and percentage
  - [ ] Open Interest
  - [ ] Spot volume
- [ ] Candlestick chart displays:
  - [ ] Chart renders without errors
  - [ ] Candles visible (green for up, red for down)
  - [ ] Volume bars at bottom
  - [ ] Crosshair works on hover
  - [ ] Time axis shows dates
  - [ ] Price axis shows values
- [ ] Timeframe selector works:
  - [ ] Try clicking: 1m, 5m, 15m, 1H, 1D
  - [ ] Chart updates when timeframe changes
  - [ ] Active timeframe highlighted in green
- [ ] "View Full Options Chain" button visible
- [ ] Last updated timestamp at bottom

**Test Each Index:**
- [ ] /indices/nifty
- [ ] /indices/banknifty
- [ ] /indices/finnifty
- [ ] /indices/midcpnifty
- [ ] /indices/sensex

---

#### Page 3: Options Chain (`/indices/nifty/options`)

**Access:** http://localhost:3000/indices/nifty/options

**Checklist:**
- [ ] Page loads without errors
- [ ] Back button returns to /indices/nifty
- [ ] Header shows "Nifty 50 - Options Chain"
- [ ] Spot price card displays:
  - [ ] Current LTP
  - [ ] Change % with trend arrow
- [ ] Expiry selector dropdown:
  - [ ] Shows available expiries
  - [ ] Dates formatted as "DD Mon YYYY"
  - [ ] Can select different expiries
  - [ ] Table updates when expiry changes
- [ ] PCR & Stats section shows:
  - [ ] Put-Call Ratio (decimal value)
  - [ ] Total Call OI (green)
  - [ ] Total Put OI (red)
- [ ] Options table displays:
  - [ ] Header row with CE and PE labels
  - [ ] Column headers: OI, Volume, IV, LTP, Greeks, Strike Price
  - [ ] Multiple strike rows visible
  - [ ] ATM strike highlighted in green/emerald
  - [ ] ITM calls in green
  - [ ] ITM puts in red
  - [ ] Greeks displayed (Δ, Γ, Θ)
  - [ ] All numbers formatted correctly
  - [ ] Data aligns properly in columns
- [ ] Greeks legend at bottom:
  - [ ] Delta, Gamma, Theta explanations
  - [ ] ITM/ATM indicators explained
- [ ] Data updates automatically (wait 10 seconds)

**Test Options Chain for:**
- [ ] NIFTY
- [ ] BANKNIFTY
- [ ] At least one other index

---

### Navigation & Layout

**Sidebar Navigation:**
- [ ] "Indices" item visible in sidebar
- [ ] Indices icon is TrendingUp arrow
- [ ] Clicking "Indices" navigates to /indices
- [ ] Active page highlighted in green
- [ ] All navigation items work correctly

**Overall Layout:**
- [ ] Sidebar fixed on left side
- [ ] Content area properly spaced from sidebar
- [ ] No horizontal scrollbars (unless intended)
- [ ] Dark theme consistent across all pages
- [ ] Colors: emerald green for positive, red for negative
- [ ] Loading states show skeleton screens
- [ ] Error states handled gracefully

---

### Real-time Updates

**Test Auto-Refresh:**

1. **Open Indices page** (http://localhost:3000/indices)
   - [ ] Note the LTP of Nifty 50
   - [ ] Wait 5 seconds
   - [ ] Check if LTP updated (should change if market is open)

2. **Open Index Detail page** (http://localhost:3000/indices/nifty)
   - [ ] Note the current LTP
   - [ ] Wait 5 seconds
   - [ ] Check if LTP updated

3. **Open Options Chain** (http://localhost:3000/indices/nifty/options)
   - [ ] Note a strike's LTP
   - [ ] Wait 10 seconds
   - [ ] Check if LTPs updated

**During Market Hours:**
- [ ] Prices update automatically
- [ ] No need to refresh page
- [ ] Changes animate smoothly

**Outside Market Hours:**
- [ ] Last available data displayed
- [ ] No errors shown
- [ ] Timestamp shows last update time

---

### Responsiveness & Performance

**Desktop (1920x1080):**
- [ ] All pages render correctly
- [ ] Charts fill available space
- [ ] Grid layouts use full width
- [ ] No layout issues

**Laptop (1366x768):**
- [ ] Pages still usable
- [ ] Charts resize appropriately
- [ ] No horizontal scrolling (except charts)

**Tablet (768px):**
- [ ] Sidebar still functional
- [ ] Cards stack appropriately
- [ ] Charts responsive

**Performance:**
- [ ] Pages load in < 2 seconds
- [ ] Charts render in < 1 second
- [ ] No lag when switching timeframes
- [ ] Smooth scrolling
- [ ] No console errors

---

### Error Handling

**Test Error States:**

1. **Without Fyers Authentication:**
   - [ ] Pages load but show "No data" states
   - [ ] Helpful error messages displayed
   - [ ] Link to Settings page provided

2. **Network Issues** (disconnect internet briefly):
   - [ ] React Query retry mechanism works
   - [ ] Error messages shown
   - [ ] Data doesn't crash the app

3. **Invalid Routes:**
   - [ ] /indices/invalid → Shows "Index Not Found"
   - [ ] Back button works

---

### Cross-Browser Testing

**Chrome/Edge (Chromium):**
- [ ] All features work
- [ ] Charts render correctly
- [ ] No console errors

**Firefox:**
- [ ] All features work
- [ ] Charts render correctly

**Safari (if available):**
- [ ] All features work
- [ ] Charts render correctly

---

### Data Accuracy

**Verify Data Matches Backend:**

1. **Get backend data:**
```bash
curl http://localhost:8000/api/v1/watchlist/summary | jq '.indices[0].spot.ltp'
```

2. **Compare with frontend:**
   - Open http://localhost:3000/indices
   - Check if Nifty LTP matches

3. **Greeks Calculation:**
   - Manually calculate Greeks with same inputs
   - Compare with frontend display
   - Values should be very close (within 0.01)

---

### Console & Network

**Browser Developer Tools:**

1. **Open Console:**
   - [ ] No red errors
   - [ ] No warnings about failed requests
   - [ ] React Query devtools work (if installed)

2. **Network Tab:**
   - [ ] API calls to `/api/v1/watchlist/*` successful
   - [ ] Status codes 200
   - [ ] Response times reasonable (< 500ms)
   - [ ] Auto-refresh calls every 5-10 seconds

---

## 🐛 Known Issues / Limitations

### Current Limitations
1. **Greeks calculations:**
   - Use simplified Black-Scholes model
   - Default to 7 DTE and 15% IV for display
   - More accurate Greeks available via API

2. **Options chain:**
   - Availability depends on Fyers API
   - May not show during non-market hours
   - Some indices may have limited options data

3. **Historical data:**
   - Limited to Fyers API history (typically 30 days for intraday)
   - Daily data available for longer periods

4. **Real-time updates:**
   - Poll-based (5-10 seconds)
   - Not true WebSocket streaming
   - May have slight delay during high volatility

---

## ✅ Success Criteria

**Minimum Requirements:**
- [ ] All 5 indices display correctly
- [ ] Charts render for at least 1 index
- [ ] Options chain loads for NIFTY
- [ ] Greeks calculations work
- [ ] No critical console errors
- [ ] Data refreshes automatically

**Ideal State:**
- [ ] All pages load instantly
- [ ] Real-time data for all indices
- [ ] Charts smooth and responsive
- [ ] Options chain for all indices
- [ ] Zero console errors/warnings
- [ ] Beautiful Bloomberg-style interface

---

## 📸 Screenshots to Capture

Please take screenshots of:
1. Indices overview page
2. Nifty 50 detail page with chart
3. Bank Nifty options chain
4. Any errors or issues encountered

---

## 🆘 Troubleshooting

### Issue: "No data available"
**Solution:** Check Fyers authentication in Settings

### Issue: Charts not rendering
**Solution:**
```bash
# Rebuild frontend
docker compose build frontend --no-cache
docker compose up -d frontend
```

### Issue: Old data showing
**Solution:** Hard refresh browser (Ctrl+Shift+R or Cmd+Shift+R)

### Issue: Container not healthy
**Solution:**
```bash
docker compose logs frontend
docker compose restart frontend
```

---

## 📊 Final Verification

After testing everything above:

- [ ] All API endpoints working ✅
- [ ] All frontend pages loading ✅
- [ ] Real-time updates working ✅
- [ ] Charts rendering correctly ✅
- [ ] Options chain displaying ✅
- [ ] Navigation working ✅
- [ ] No critical errors ✅

**Overall Status:** ✅ READY FOR PRODUCTION USE

---

**Testing Completed By:** _______________
**Date:** _______________
**Issues Found:** _______________
**Overall Rating:** ⭐⭐⭐⭐⭐
