import asyncio
from src.integrations.fyers_client import FyersClient
from src.watchlist.options_data_service import OptionsDataService

async def main():
    service = OptionsDataService()
    tests = [
        "NSE:NIFTY50-INDEX", 
        "NSE:NIFTY-INDEX", 
        "NSE:NIFTYBANK-INDEX", 
        "NSE:BANKNIFTY-INDEX"
    ]
    for t in tests:
        try:
            chain = await asyncio.to_thread(service.get_canonical_chain, t, strike_count=2, include_expiries=1)
            spots = chain.get("data", {}).get("expiryData", [])
            if spots:
                print(f"SUCCESS: {t} -> Spot: {spots[0].get('spot')}")
            else:
                print(f"FAILED: {t} empty expiryData")
        except Exception as e:
            print(f"ERROR: {t} -> {e}")

asyncio.run(main())
