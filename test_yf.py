import yfinance as yf

def test_yf_options():
    try:
        ticker = yf.Ticker("AAPL")
        expiries = ticker.options
        if not expiries:
            print("No expiries found.")
            return
        
        nearest_expiry = expiries[0]
        chain = ticker.option_chain(nearest_expiry)
        
        print("Spot:", ticker.info.get("regularMarketPrice"))
        calls = chain.calls
        puts = chain.puts
        print(f"Nearest expiry {nearest_expiry} has {len(calls)} calls and {len(puts)} puts")
        print("First call:", calls.iloc[0].to_dict() if not calls.empty else "None")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_yf_options()
