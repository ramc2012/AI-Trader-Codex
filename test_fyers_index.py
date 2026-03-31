import asyncio
import os
from src.integrations.fyers_client import FyersClient
from src.watchlist.options_data_service import OptionsDataService

async def main():
    service = OptionsDataService()
    # Test for NIFTY50
    chain = await asyncio.to_thread(service.get_canonical_chain, "NSE:NIFTY50-INDEX", strike_count=2, include_expiries=1)
    if not chain.get("data", {}).get("expiryData"):
        print("Failed NIFTY50-INDEX, trying NSE:NIFTY-INDEX")
        chain = await asyncio.to_thread(service.get_canonical_chain, "NSE:NIFTY-INDEX", strike_count=2, include_expiries=1)
    
    print("NIFTY Spot:", chain.get("data", {}).get("expiryData", [{}])[0].get("spot"))
    
    # Test for BANKNIFTY
    chain2 = await asyncio.to_thread(service.get_canonical_chain, "NSE:NIFTYBANK-INDEX", strike_count=2, include_expiries=1)
    print("BANKNIFTY Spot:", chain2.get("data", {}).get("expiryData", [{}])[0].get("spot"))

asyncio.run(main())
