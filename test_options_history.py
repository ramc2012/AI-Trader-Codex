import asyncio
import sys
from datetime import datetime, timedelta

# Need to ensure we can import src
sys.path.insert(0, ".")
from src.integrations.fyers_client import FyersClient

async def test():
    try:
        client = FyersClient()
        if not client.is_authenticated:
            print("Not authenticated!")
            return
            
        symbol = "NSE:ABB26APR5950CE"
        range_from = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
        range_to = datetime.now().strftime("%Y-%m-%d")
        
        print("Fetching history...")
        res = client.get_history(
            symbol=symbol,
            resolution="15",
            range_from=range_from,
            range_to=range_to,
            date_format=1
        )
        candles = res.get("candles", [])
        print("Candles found:", len(candles))
        if candles:
            print("Last close:", candles[-1][4])
    except Exception as e:
        print("Error:", repr(e))

if __name__ == "__main__":
    asyncio.run(test())
