"""Background service for ATM strike resolution and caching.

Resolves nearest-expiry ATM CE/PE symbols for all FNO underlyings
periodically to ensure the Options Watchlist loads instantly without
sequential broker API calls.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.config.fno_constants import ALL_FNO, get_instrument
from src.config.market_hours import IST
from src.integrations.fyers_client import FyersClient
from src.watchlist.options_data_service import OptionsDataService
from src.utils.logger import get_logger

logger = get_logger(__name__)

def _calc_ema(v: List[float], p: int) -> List[float]:
    if not v:
        return []
    k = 2 / (p + 1)
    ema = v[0]
    out = [ema]
    for x in v[1:]:
        ema = x * k + ema * (1 - k)
        out.append(ema)
    return out

def _calc_macd(c: List[float]) -> tuple[float, float]:
    if len(c) < 27:
        return 0.0, 0.0
    e12 = _calc_ema(c, 12)
    e26 = _calc_ema(c, 26)
    return e12[-1] - e26[-1], e12[-2] - e26[-2]

def _calc_rsi(c: List[float], p: int = 14) -> float:
    if len(c) < p + 1:
        return 50.0
    g, l = 0.0, 0.0
    for i in range(len(c) - p, len(c)):
        d = c[i] - c[i - 1]
        if d > 0:
            g += d
        else:
            l -= d
    if l == 0:
        return 100.0 if g > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + g / l)

@dataclass
class ATMMetadata:
    underlying: str
    ce_symbol: str
    pe_symbol: str
    strike: float
    spot: float
    expiry: str
    last_updated: datetime
    market: str = "NSE"
    ce_ltp: float = 0.0
    pe_ltp: float = 0.0
    ce_oi: int = 0
    pe_oi: int = 0
    ce_volume: int = 0
    pe_volume: int = 0
    ce_macd: float = 0.0
    ce_macd_prev: float = 0.0
    pe_macd: float = 0.0
    pe_macd_prev: float = 0.0
    ce_rsi: float = 0.0
    pe_rsi: float = 0.0

class ATMRegistryService:
    """Singleton service to keep 209 FNO ATM strikes resolved in memory."""

    def __init__(self, client: FyersClient):
        self._client = client
        self._options_service = OptionsDataService(client)
        self._cache: Dict[str, ATMMetadata] = {}
        self._is_running = False
        self._last_full_sync: Optional[datetime] = None
        self._sync_interval = timedelta(minutes=15) # ATM strikes don't change every second
        self._lock = asyncio.Lock()

    @property
    def is_warmed(self) -> bool:
        return len(self._cache) > 0

    def get_all_atm(self, market: Optional[str] = None) -> List[ATMMetadata]:
        """Return currently resolved ATM metadata, optionally filtered by market."""
        if market:
            return [v for v in self._cache.values() if v.market.upper() == market.upper()]
        return list(self._cache.values())

    async def start_background_sync(self):
        """Start the periodic background sync loop."""
        if self._is_running:
            return
        
        self._is_running = True
        logger.info("atm_registry_sync_started")
        
        while self._is_running:
            try:
                await self.sync_all()
            except Exception as e:
                logger.error("atm_registry_sync_loop_error", error=str(e))
            
            # Sleep until next interval (15 mins)
            await asyncio.sleep(self._sync_interval.total_seconds())

    async def stop(self):
        self._is_running = False

    async def sync_all(self):
        """Perform a full resolution of NSE, US, and Crypto ATM symbols."""
        async with self._lock:
            start_time = datetime.now(tz=IST)
            
            # 1. NSE FNO (Equities + Indices)
            nse_underlyings = list(ALL_FNO.keys())
            batch_size = 5
            for i in range(0, len(nse_underlyings), batch_size):
                batch = nse_underlyings[i : i + batch_size]
                tasks = [self._resolve_one(sym) for sym in batch]
                await asyncio.gather(*tasks)
                await asyncio.sleep(0.5)

            # 2. US Top Stocks
            from src.config.agent_universe import DEFAULT_AGENT_US_SYMBOLS
            us_symbols = [s.split(":")[-1] for s in DEFAULT_AGENT_US_SYMBOLS if "US:" in s]
            for sym in us_symbols:
                await self._resolve_us_one(sym)
                await asyncio.sleep(0.2)
            
            # 3. Crypto Top Pairs
            from src.config.agent_universe import DEFAULT_AGENT_CRYPTO_SYMBOLS
            crypto_symbols = [s for s in DEFAULT_AGENT_CRYPTO_SYMBOLS]
            for sym in crypto_symbols:
                await self._resolve_crypto_one(sym)
                await asyncio.sleep(0.1)

            self._last_full_sync = datetime.now(tz=IST)
            elapsed = (self._last_full_sync - start_time).total_seconds()
            logger.info("atm_registry_full_sync_complete", 
                        symbols=len(self._cache), 
                        duration_sec=round(elapsed, 2))

    async def _resolve_one(self, sym: str):
        """Resolve ATM for a single NSE underlying and update cache."""
        try:
            inst = get_instrument(sym)
            if inst and inst.instrument_type == "INDEX":
                if sym == "NIFTY":
                    underlying_sym = "NSE:NIFTY50-INDEX"
                elif sym == "BANKNIFTY":
                    underlying_sym = "NSE:NIFTYBANK-INDEX"
                elif sym == "SENSEX" or sym == "BANKEX":
                    underlying_sym = f"BSE:{sym}-INDEX"
                else:
                    underlying_sym = f"NSE:{sym}-INDEX"
            else:
                underlying_sym = f"NSE:{sym}-EQ"
                
            chain_data = await asyncio.to_thread(
                self._options_service.get_canonical_chain, 
                underlying_sym, 
                strike_count=20, 
                include_expiries=1
            )
            
            expiries = chain_data.get("data", {}).get("expiryData", [])
            if not expiries:
                return
            
            near_expiry = expiries[0]
            spot = near_expiry.get("spot", 0.0)
            strikes = near_expiry.get("strikes", [])
            
            if not strikes or spot <= 0:
                return
                
            is_index = inst and inst.instrument_type == "INDEX"
            tolerance = 0.01 if is_index else 0.03
            
            # Find bounds
            valid_strikes = [s for s in strikes if abs(s["strike"] - spot) / spot <= tolerance]
            if not valid_strikes:
                valid_strikes = strikes
            
            # Find max combo OI
            def _combo_oi(s):
                coi = int(s.get("ce", {}).get("oi", 0))
                poi = int(s.get("pe", {}).get("oi", 0))
                return coi + poi
                
            atm_row = max(valid_strikes, key=_combo_oi)
            atm_strike = atm_row["strike"]
            expiry = near_expiry.get("expiry", "N/A")
            
            ce_entry = atm_row.get("ce", {})
            pe_entry = atm_row.get("pe", {})
            ce_symbol = ce_entry.get("symbol")
            pe_symbol = pe_entry.get("symbol")
            
            ce_macd, ce_macd_prev, ce_rsi = 0.0, 0.0, 0.0
            pe_macd, pe_macd_prev, pe_rsi = 0.0, 0.0, 0.0
            
            ce_ltp_fallback = float(ce_entry.get("ltp") or 0.0)
            pe_ltp_fallback = float(pe_entry.get("ltp") or 0.0)

            if ce_symbol and pe_symbol:
                range_from = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
                range_to = datetime.now().strftime("%Y-%m-%d")
                
                try:
                    ce_hist = await asyncio.to_thread(
                        self._client.get_history,
                        symbol=ce_symbol,
                        resolution="15",
                        range_from=range_from,
                        range_to=range_to,
                        date_format=1
                    )
                    ce_closes = [c[4] for c in ce_hist.get("candles", [])]
                    if ce_closes:
                        ce_macd, ce_macd_prev = _calc_macd(ce_closes)
                        ce_rsi = _calc_rsi(ce_closes)
                        if ce_ltp_fallback <= 0:
                            ce_ltp_fallback = float(ce_closes[-1])
                except Exception as e:
                    logger.debug("atm_ce_history_failed", symbol=ce_symbol, error=str(e))

                try:
                    pe_hist = await asyncio.to_thread(
                        self._client.get_history,
                        symbol=pe_symbol,
                        resolution="15",
                        range_from=range_from,
                        range_to=range_to,
                        date_format=1
                    )
                    pe_closes = [c[4] for c in pe_hist.get("candles", [])]
                    if pe_closes:
                        pe_macd, pe_macd_prev = _calc_macd(pe_closes)
                        pe_rsi = _calc_rsi(pe_closes)
                        if pe_ltp_fallback <= 0:
                            pe_ltp_fallback = float(pe_closes[-1])
                except Exception as e:
                    logger.debug("atm_pe_history_failed", symbol=pe_symbol, error=str(e))

                self._cache[f"NSE:{sym}"] = ATMMetadata(
                    underlying=sym,
                    ce_symbol=ce_symbol,
                    pe_symbol=pe_symbol,
                    strike=atm_strike,
                    expiry=expiry,
                    last_updated=datetime.now(tz=IST),
                    market="NSE",
                    spot=spot,
                    ce_ltp=ce_ltp_fallback,
                    pe_ltp=pe_ltp_fallback,
                    ce_oi=int(ce_entry.get("oi") or 0),
                    pe_oi=int(pe_entry.get("oi") or 0),
                    ce_volume=int(ce_entry.get("volume") or 0),
                    pe_volume=int(pe_entry.get("volume") or 0),
                    ce_macd=ce_macd,
                    ce_macd_prev=ce_macd_prev,
                    pe_macd=pe_macd,
                    pe_macd_prev=pe_macd_prev,
                    ce_rsi=ce_rsi,
                    pe_rsi=pe_rsi
                )
        except Exception as e:
            logger.debug("atm_resolution_failed_nse", symbol=sym, error=str(e))

    async def _resolve_us_one(self, sym: str):
        """Resolve ATM for a US symbol using yfinance."""
        try:
            import yfinance as yf
            import pandas as pd
            
            def _fetch_yf():
                ticker = yf.Ticker(sym)
                expiries = ticker.options
                if not expiries:
                    return None
                near_exp = expiries[0]
                chain = ticker.option_chain(near_exp)
                # yfinance ticker.info might be slow or empty reliably. 
                # Alternatively, we can use fast_info:
                spot = getattr(ticker.fast_info, 'last_price', 0.0)
                if not spot:
                    spot = ticker.info.get("regularMarketPrice") or 0.0
                return spot, near_exp, chain.calls, chain.puts

            data = await asyncio.to_thread(_fetch_yf)
            if not data: return
            spot, expiry_str, calls, puts = data
            if spot <= 0 or calls.empty or puts.empty: return
            
            calls_list = calls.to_dict('records')
            puts_list = puts.to_dict('records')
            calls_by_strike = {c['strike']: c for c in calls_list}
            puts_by_strike = {p['strike']: p for p in puts_list}
            common_strikes = set(calls_by_strike.keys()).intersection(set(puts_by_strike.keys()))
            
            if not common_strikes: return
            
            tolerance = 0.03
            valid_strikes = [s for s in common_strikes if abs(s - spot) / spot <= tolerance]
            if not valid_strikes:
                valid_strikes = list(common_strikes)
                
            def _combo_oi(s):
                # Ensure we handle NaN if openInterest is missing from Yahoo API
                import math
                coi = calls_by_strike.get(s, {}).get('openInterest', 0)
                poi = puts_by_strike.get(s, {}).get('openInterest', 0)
                if math.isnan(coi): coi = 0
                if math.isnan(poi): poi = 0
                return coi + poi
                
            atm_strike = max(valid_strikes, key=_combo_oi)
            atm_call = calls_by_strike.get(atm_strike, {})
            atm_put = puts_by_strike.get(atm_strike, {})
            
            # Expiry usually comes in 'YYYY-MM-DD'
            self._cache[f"US:{sym}"] = ATMMetadata(
                underlying=sym,
                ce_symbol=atm_call.get("contractSymbol", ""),
                pe_symbol=atm_put.get("contractSymbol", ""),
                strike=atm_strike,
                spot=spot,
                expiry=expiry_str,
                last_updated=datetime.now(tz=IST),
                market="US",
                ce_ltp=float(atm_call.get("lastPrice") or 0.0),
                pe_ltp=float(atm_put.get("lastPrice") or 0.0),
                ce_oi=int(atm_call.get("openInterest") or 0) if not pd.isna(atm_call.get("openInterest")) else 0,
                pe_oi=int(atm_put.get("openInterest") or 0) if not pd.isna(atm_put.get("openInterest")) else 0
            )

        except Exception as e:
            logger.debug("atm_resolution_failed_us", symbol=sym, error=str(e))

    async def _resolve_crypto_one(self, pair: str):
        """Mock/Simulated ATM resolution for Crypto momentum tracking."""
        try:
            # For crypto, we'll project a 'Simulated' option to allow momentum tracking
            # in the same UI structure until a dedicated options broker is integrated.
            from src.integrations.binance_client import BinanceClient
            binance = BinanceClient()
            ticker = await binance.get_ticker(pair)
            spot = float(ticker.get("lastPrice", 0.0))
            if spot <= 0: return

            # Simulated monthly expiry (last Friday)
            now = datetime.now(tz=IST)
            last_day = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            last_friday = last_day - timedelta(days=(last_day.weekday() - 4) % 7)
            
            clean_name = pair.replace("USDT", "")
            
            self._cache[f"CRYPTO:{pair}"] = ATMMetadata(
                underlying=clean_name,
                ce_symbol=f"CRYPTO:{pair}-CE-ATM",
                pe_symbol=f"CRYPTO:{pair}-PE-ATM",
                strike=spot,
                spot=spot,
                expiry=last_friday.date().isoformat(),
                last_updated=datetime.now(tz=IST),
                market="CRYPTO",
            )
        except Exception as e:
            logger.debug("atm_resolution_failed_crypto", symbol=pair, error=str(e))
