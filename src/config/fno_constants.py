"""FnO instrument constants for NSE derivatives.

Contains the 209 FnO-eligible stocks along with major indices,
their lot sizes, strike intervals, and sector classifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FnOInstrument:
    """Definition of an FnO-eligible instrument."""

    symbol: str
    name: str
    lot_size: int
    strike_interval: int | float
    instrument_type: Literal["INDEX", "EQUITY"]
    sector: str
    exchange: str = "NSE"


# ── Major Indices ────────────────────────────────────────────────────────
INDEX_FNO: dict[str, FnOInstrument] = {
    "NIFTY": FnOInstrument("NIFTY", "Nifty 50", 25, 50, "INDEX", "Index"),
    "BANKNIFTY": FnOInstrument("BANKNIFTY", "Bank Nifty", 15, 100, "INDEX", "Index"),
    "FINNIFTY": FnOInstrument("FINNIFTY", "Fin Nifty", 25, 50, "INDEX", "Index"),
    "MIDCPNIFTY": FnOInstrument("MIDCPNIFTY", "Midcap Nifty", 50, 25, "INDEX", "Index"),
    "SENSEX": FnOInstrument("SENSEX", "BSE Sensex", 10, 100, "INDEX", "Index/BSE"),
    "BANKEX": FnOInstrument("BANKEX", "BSE Bankex", 15, 100, "INDEX", "Index/BSE"),
}

# ── Equity FnO stocks (209 instruments) ──────────────────────────────────
# Sorted alphabetically. Lot sizes and strike intervals as of 2026.
EQUITY_FNO: dict[str, FnOInstrument] = {
    "ABB": FnOInstrument("ABB", "ABB India", 250, 100, "EQUITY", "Capital Goods"),
    "ABBOTINDIA": FnOInstrument("ABBOTINDIA", "Abbott India", 25, 200, "EQUITY", "Pharma"),
    "ABCAPITAL": FnOInstrument("ABCAPITAL", "Aditya Birla Capital", 3800, 2.5, "EQUITY", "Finance"),
    "ABFRL": FnOInstrument("ABFRL", "Aditya Birla Fashion", 2600, 5, "EQUITY", "Consumer"),
    "ACC": FnOInstrument("ACC", "ACC Ltd", 400, 10, "EQUITY", "Cement"),
    "ADANIENT": FnOInstrument("ADANIENT", "Adani Enterprises", 250, 25, "EQUITY", "Diversified"),
    "ADANIPORTS": FnOInstrument("ADANIPORTS", "Adani Ports", 500, 10, "EQUITY", "Infrastructure"),
    "ALKEM": FnOInstrument("ALKEM", "Alkem Labs", 150, 25, "EQUITY", "Pharma"),
    "AMBUJACEM": FnOInstrument("AMBUJACEM", "Ambuja Cements", 1000, 5, "EQUITY", "Cement"),
    "APOLLOHOSP": FnOInstrument("APOLLOHOSP", "Apollo Hospitals", 125, 50, "EQUITY", "Healthcare"),
    "APOLLOTYRE": FnOInstrument("APOLLOTYRE", "Apollo Tyres", 1250, 5, "EQUITY", "Auto"),
    "ASHOKLEY": FnOInstrument("ASHOKLEY", "Ashok Leyland", 4500, 2.5, "EQUITY", "Auto"),
    "ASIANPAINT": FnOInstrument("ASIANPAINT", "Asian Paints", 300, 10, "EQUITY", "Consumer"),
    "ASTRAL": FnOInstrument("ASTRAL", "Astral Ltd", 375, 10, "EQUITY", "Building Materials"),
    "ATUL": FnOInstrument("ATUL", "Atul Ltd", 100, 50, "EQUITY", "Chemicals"),
    "AUBANK": FnOInstrument("AUBANK", "AU Small Finance Bank", 1000, 5, "EQUITY", "Banking"),
    "AUROPHARMA": FnOInstrument("AUROPHARMA", "Aurobindo Pharma", 500, 10, "EQUITY", "Pharma"),
    "AXISBANK": FnOInstrument("AXISBANK", "Axis Bank", 625, 10, "EQUITY", "Banking"),
    "BAJAJ-AUTO": FnOInstrument("BAJAJ-AUTO", "Bajaj Auto", 75, 100, "EQUITY", "Auto"),
    "BAJAJFINSV": FnOInstrument("BAJAJFINSV", "Bajaj Finserv", 500, 10, "EQUITY", "Finance"),
    "BAJFINANCE": FnOInstrument("BAJFINANCE", "Bajaj Finance", 125, 50, "EQUITY", "Finance"),
    "BALKRISIND": FnOInstrument("BALKRISIND", "Balkrishna Ind", 250, 20, "EQUITY", "Auto"),
    "BANDHANBNK": FnOInstrument("BANDHANBNK", "Bandhan Bank", 3600, 2.5, "EQUITY", "Banking"),
    "BANKBARODA": FnOInstrument("BANKBARODA", "Bank of Baroda", 2925, 2.5, "EQUITY", "Banking"),
    "BATAINDIA": FnOInstrument("BATAINDIA", "Bata India", 375, 10, "EQUITY", "Consumer"),
    "BEL": FnOInstrument("BEL", "Bharat Electronics", 2250, 5, "EQUITY", "Defence"),
    "BERGEPAINT": FnOInstrument("BERGEPAINT", "Berger Paints", 1100, 5, "EQUITY", "Consumer"),
    "BHARATFORG": FnOInstrument("BHARATFORG", "Bharat Forge", 500, 10, "EQUITY", "Auto"),
    "BHARTIARTL": FnOInstrument("BHARTIARTL", "Bharti Airtel", 475, 10, "EQUITY", "Telecom"),
    "BHEL": FnOInstrument("BHEL", "BHEL", 2750, 2.5, "EQUITY", "Capital Goods"),
    "BIOCON": FnOInstrument("BIOCON", "Biocon", 2300, 2.5, "EQUITY", "Pharma"),
    "BOSCHLTD": FnOInstrument("BOSCHLTD", "Bosch Ltd", 25, 250, "EQUITY", "Auto"),
    "BPCL": FnOInstrument("BPCL", "BPCL", 1800, 5, "EQUITY", "Oil & Gas"),
    "BRITANNIA": FnOInstrument("BRITANNIA", "Britannia", 100, 50, "EQUITY", "FMCG"),
    "BSE": FnOInstrument("BSE", "BSE Ltd", 200, 25, "EQUITY", "Finance"),
    "BSOFT": FnOInstrument("BSOFT", "Birlasoft", 1500, 5, "EQUITY", "IT"),
    "CANBK": FnOInstrument("CANBK", "Canara Bank", 5400, 1, "EQUITY", "Banking"),
    "CANFINHOME": FnOInstrument("CANFINHOME", "Can Fin Homes", 975, 5, "EQUITY", "Finance"),
    "CHAMBLFERT": FnOInstrument("CHAMBLFERT", "Chambal Fertilisers", 1500, 5, "EQUITY", "Chemicals"),
    "CHOLAFIN": FnOInstrument("CHOLAFIN", "Cholamandalam Finance", 500, 10, "EQUITY", "Finance"),
    "CIPLA": FnOInstrument("CIPLA", "Cipla", 500, 10, "EQUITY", "Pharma"),
    "COALINDIA": FnOInstrument("COALINDIA", "Coal India", 1500, 5, "EQUITY", "Mining"),
    "COFORGE": FnOInstrument("COFORGE", "Coforge", 100, 50, "EQUITY", "IT"),
    "COLPAL": FnOInstrument("COLPAL", "Colgate Palmolive", 275, 20, "EQUITY", "FMCG"),
    "CONCOR": FnOInstrument("CONCOR", "Container Corp", 1000, 5, "EQUITY", "Logistics"),
    "COROMANDEL": FnOInstrument("COROMANDEL", "Coromandel Intl", 500, 10, "EQUITY", "Chemicals"),
    "CROMPTON": FnOInstrument("CROMPTON", "Crompton Greaves CE", 1500, 5, "EQUITY", "Consumer"),
    "CUB": FnOInstrument("CUB", "City Union Bank", 3600, 2.5, "EQUITY", "Banking"),
    "CUMMINSIND": FnOInstrument("CUMMINSIND", "Cummins India", 200, 25, "EQUITY", "Capital Goods"),
    "DABUR": FnOInstrument("DABUR", "Dabur India", 1000, 5, "EQUITY", "FMCG"),
    "DALBHARAT": FnOInstrument("DALBHARAT", "Dalmia Bharat", 325, 10, "EQUITY", "Cement"),
    "DEEPAKNTR": FnOInstrument("DEEPAKNTR", "Deepak Nitrite", 250, 20, "EQUITY", "Chemicals"),
    "DELTACORP": FnOInstrument("DELTACORP", "Delta Corp", 4400, 2.5, "EQUITY", "Hospitality"),
    "DIVISLAB": FnOInstrument("DIVISLAB", "Divis Labs", 125, 50, "EQUITY", "Pharma"),
    "DIXON": FnOInstrument("DIXON", "Dixon Tech", 75, 100, "EQUITY", "Electronics"),
    "DLF": FnOInstrument("DLF", "DLF Ltd", 825, 5, "EQUITY", "Realty"),
    "DRREDDY": FnOInstrument("DRREDDY", "Dr Reddys Labs", 125, 50, "EQUITY", "Pharma"),
    "EICHERMOT": FnOInstrument("EICHERMOT", "Eicher Motors", 150, 50, "EQUITY", "Auto"),
    "ESCORTS": FnOInstrument("ESCORTS", "Escorts Kubota", 200, 25, "EQUITY", "Auto"),
    "EXIDEIND": FnOInstrument("EXIDEIND", "Exide Industries", 1800, 5, "EQUITY", "Auto"),
    "FEDERALBNK": FnOInstrument("FEDERALBNK", "Federal Bank", 5000, 1, "EQUITY", "Banking"),
    "GAIL": FnOInstrument("GAIL", "GAIL India", 4575, 2.5, "EQUITY", "Oil & Gas"),
    "GLENMARK": FnOInstrument("GLENMARK", "Glenmark Pharma", 500, 10, "EQUITY", "Pharma"),
    "GMRINFRA": FnOInstrument("GMRINFRA", "GMR Airports Infra", 5000, 1, "EQUITY", "Infrastructure"),
    "GNFC": FnOInstrument("GNFC", "GNFC", 1000, 5, "EQUITY", "Chemicals"),
    "GODREJCP": FnOInstrument("GODREJCP", "Godrej Consumer", 500, 10, "EQUITY", "FMCG"),
    "GODREJPROP": FnOInstrument("GODREJPROP", "Godrej Properties", 250, 20, "EQUITY", "Realty"),
    "GRANULES": FnOInstrument("GRANULES", "Granules India", 1600, 5, "EQUITY", "Pharma"),
    "GRASIM": FnOInstrument("GRASIM", "Grasim Industries", 250, 20, "EQUITY", "Cement"),
    "GUJGASLTD": FnOInstrument("GUJGASLTD", "Gujarat Gas", 1250, 5, "EQUITY", "Oil & Gas"),
    "HAL": FnOInstrument("HAL", "Hindustan Aeronautics", 150, 50, "EQUITY", "Defence"),
    "HAVELLS": FnOInstrument("HAVELLS", "Havells India", 500, 10, "EQUITY", "Consumer"),
    "HCLTECH": FnOInstrument("HCLTECH", "HCL Technologies", 350, 20, "EQUITY", "IT"),
    "HDFCAMC": FnOInstrument("HDFCAMC", "HDFC AMC", 150, 25, "EQUITY", "Finance"),
    "HDFCBANK": FnOInstrument("HDFCBANK", "HDFC Bank", 550, 10, "EQUITY", "Banking"),
    "HDFCLIFE": FnOInstrument("HDFCLIFE", "HDFC Life", 1100, 5, "EQUITY", "Insurance"),
    "HEROMOTOCO": FnOInstrument("HEROMOTOCO", "Hero MotoCorp", 150, 50, "EQUITY", "Auto"),
    "HINDALCO": FnOInstrument("HINDALCO", "Hindalco", 1075, 5, "EQUITY", "Metals"),
    "HINDCOPPER": FnOInstrument("HINDCOPPER", "Hindustan Copper", 2150, 5, "EQUITY", "Metals"),
    "HINDPETRO": FnOInstrument("HINDPETRO", "HPCL", 1850, 5, "EQUITY", "Oil & Gas"),
    "HINDUNILVR": FnOInstrument("HINDUNILVR", "Hindustan Unilever", 300, 10, "EQUITY", "FMCG"),
    "ICICIBANK": FnOInstrument("ICICIBANK", "ICICI Bank", 700, 10, "EQUITY", "Banking"),
    "ICICIGI": FnOInstrument("ICICIGI", "ICICI Lombard", 425, 10, "EQUITY", "Insurance"),
    "ICICIPRULI": FnOInstrument("ICICIPRULI", "ICICI Prudential Life", 1000, 5, "EQUITY", "Insurance"),
    "IDEA": FnOInstrument("IDEA", "Vodafone Idea", 50000, 0.5, "EQUITY", "Telecom"),
    "IDFC": FnOInstrument("IDFC", "IDFC Ltd", 5000, 1, "EQUITY", "Finance"),
    "IDFCFIRSTB": FnOInstrument("IDFCFIRSTB", "IDFC First Bank", 7500, 1, "EQUITY", "Banking"),
    "IEX": FnOInstrument("IEX", "Indian Energy Exchange", 3750, 2.5, "EQUITY", "Energy"),
    "IGL": FnOInstrument("IGL", "Indraprastha Gas", 1375, 5, "EQUITY", "Oil & Gas"),
    "INDHOTEL": FnOInstrument("INDHOTEL", "Indian Hotels", 1125, 5, "EQUITY", "Hospitality"),
    "INDIACEM": FnOInstrument("INDIACEM", "India Cements", 2700, 2.5, "EQUITY", "Cement"),
    "INDIAMART": FnOInstrument("INDIAMART", "IndiaMART", 200, 25, "EQUITY", "IT"),
    "INDIANB": FnOInstrument("INDIANB", "Indian Bank", 1250, 5, "EQUITY", "Banking"),
    "INDIGO": FnOInstrument("INDIGO", "InterGlobe Aviation", 175, 25, "EQUITY", "Aviation"),
    "INDUSINDBK": FnOInstrument("INDUSINDBK", "IndusInd Bank", 500, 10, "EQUITY", "Banking"),
    "INDUSTOWER": FnOInstrument("INDUSTOWER", "Indus Towers", 2100, 5, "EQUITY", "Telecom"),
    "INFY": FnOInstrument("INFY", "Infosys", 400, 20, "EQUITY", "IT"),
    "IOC": FnOInstrument("IOC", "Indian Oil Corp", 4875, 1, "EQUITY", "Oil & Gas"),
    "IPCALAB": FnOInstrument("IPCALAB", "IPCA Labs", 500, 10, "EQUITY", "Pharma"),
    "IRCTC": FnOInstrument("IRCTC", "IRCTC", 875, 10, "EQUITY", "Travel"),
    "ITC": FnOInstrument("ITC", "ITC Ltd", 1600, 5, "EQUITY", "FMCG"),
    "JINDALSTEL": FnOInstrument("JINDALSTEL", "Jindal Steel", 750, 10, "EQUITY", "Metals"),
    "JKCEMENT": FnOInstrument("JKCEMENT", "JK Cement", 125, 25, "EQUITY", "Cement"),
    "JSL": FnOInstrument("JSL", "Jindal Stainless", 750, 5, "EQUITY", "Metals"),
    "JSWSTEEL": FnOInstrument("JSWSTEEL", "JSW Steel", 675, 10, "EQUITY", "Metals"),
    "JUBLFOOD": FnOInstrument("JUBLFOOD", "Jubilant FoodWorks", 1250, 5, "EQUITY", "Consumer"),
    "KOTAKBANK": FnOInstrument("KOTAKBANK", "Kotak Mahindra Bank", 400, 10, "EQUITY", "Banking"),
    "LALPATHLAB": FnOInstrument("LALPATHLAB", "Dr Lal PathLabs", 250, 20, "EQUITY", "Healthcare"),
    "LAURUSLABS": FnOInstrument("LAURUSLABS", "Laurus Labs", 1500, 5, "EQUITY", "Pharma"),
    "LICHSGFIN": FnOInstrument("LICHSGFIN", "LIC Housing Finance", 1000, 5, "EQUITY", "Finance"),
    "LICI": FnOInstrument("LICI", "LIC of India", 750, 10, "EQUITY", "Insurance"),
    "LT": FnOInstrument("LT", "Larsen & Toubro", 150, 25, "EQUITY", "Capital Goods"),
    "LTIM": FnOInstrument("LTIM", "LTIMindtree", 150, 50, "EQUITY", "IT"),
    "LTTS": FnOInstrument("LTTS", "L&T Technology", 125, 25, "EQUITY", "IT"),
    "LUPIN": FnOInstrument("LUPIN", "Lupin", 425, 10, "EQUITY", "Pharma"),
    "M&M": FnOInstrument("M&M", "Mahindra & Mahindra", 350, 20, "EQUITY", "Auto"),
    "M&MFIN": FnOInstrument("M&MFIN", "M&M Financial Services", 2000, 5, "EQUITY", "Finance"),
    "MANAPPURAM": FnOInstrument("MANAPPURAM", "Manappuram Finance", 3000, 2.5, "EQUITY", "Finance"),
    "MARICO": FnOInstrument("MARICO", "Marico", 1200, 5, "EQUITY", "FMCG"),
    "MARUTI": FnOInstrument("MARUTI", "Maruti Suzuki", 50, 100, "EQUITY", "Auto"),
    "MAXHEALTH": FnOInstrument("MAXHEALTH", "Max Healthcare", 700, 10, "EQUITY", "Healthcare"),
    "MCX": FnOInstrument("MCX", "MCX", 200, 25, "EQUITY", "Finance"),
    "METROPOLIS": FnOInstrument("METROPOLIS", "Metropolis Healthcare", 400, 10, "EQUITY", "Healthcare"),
    "MFSL": FnOInstrument("MFSL", "Max Financial Services", 500, 10, "EQUITY", "Insurance"),
    "MGL": FnOInstrument("MGL", "Mahanagar Gas", 500, 10, "EQUITY", "Oil & Gas"),
    "MOTHERSON": FnOInstrument("MOTHERSON", "Motherson Sumi Wiring", 4000, 2.5, "EQUITY", "Auto"),
    "MPHASIS": FnOInstrument("MPHASIS", "Mphasis", 275, 20, "EQUITY", "IT"),
    "MRF": FnOInstrument("MRF", "MRF Ltd", 5, 1000, "EQUITY", "Auto"),
    "MUTHOOTFIN": FnOInstrument("MUTHOOTFIN", "Muthoot Finance", 375, 10, "EQUITY", "Finance"),
    "NATIONALUM": FnOInstrument("NATIONALUM", "National Aluminium", 3750, 2.5, "EQUITY", "Metals"),
    "NAUKRI": FnOInstrument("NAUKRI", "Info Edge (Naukri)", 100, 50, "EQUITY", "IT"),
    "NAVINFLUOR": FnOInstrument("NAVINFLUOR", "Navin Fluorine", 175, 25, "EQUITY", "Chemicals"),
    "NESTLEIND": FnOInstrument("NESTLEIND", "Nestle India", 200, 25, "EQUITY", "FMCG"),
    "NMDC": FnOInstrument("NMDC", "NMDC", 3350, 2.5, "EQUITY", "Mining"),
    "NTPC": FnOInstrument("NTPC", "NTPC", 1800, 5, "EQUITY", "Power"),
    "OBEROIRLTY": FnOInstrument("OBEROIRLTY", "Oberoi Realty", 375, 10, "EQUITY", "Realty"),
    "OFSS": FnOInstrument("OFSS", "Oracle Financial Services", 75, 100, "EQUITY", "IT"),
    "ONGC": FnOInstrument("ONGC", "ONGC", 3075, 2.5, "EQUITY", "Oil & Gas"),
    "PAGEIND": FnOInstrument("PAGEIND", "Page Industries", 15, 500, "EQUITY", "Consumer"),
    "PEL": FnOInstrument("PEL", "Piramal Enterprises", 500, 10, "EQUITY", "Finance"),
    "PERSISTENT": FnOInstrument("PERSISTENT", "Persistent Systems", 100, 50, "EQUITY", "IT"),
    "PETRONET": FnOInstrument("PETRONET", "Petronet LNG", 3000, 2.5, "EQUITY", "Oil & Gas"),
    "PFC": FnOInstrument("PFC", "Power Finance Corp", 1500, 5, "EQUITY", "Finance"),
    "PIDILITIND": FnOInstrument("PIDILITIND", "Pidilite Industries", 250, 20, "EQUITY", "Chemicals"),
    "PIIND": FnOInstrument("PIIND", "PI Industries", 175, 25, "EQUITY", "Chemicals"),
    "PNB": FnOInstrument("PNB", "Punjab National Bank", 6000, 1, "EQUITY", "Banking"),
    "POLYCAB": FnOInstrument("POLYCAB", "Polycab India", 100, 50, "EQUITY", "Capital Goods"),
    "POWERGRID": FnOInstrument("POWERGRID", "Power Grid Corp", 2700, 2.5, "EQUITY", "Power"),
    "PVRINOX": FnOInstrument("PVRINOX", "PVR INOX", 407, 10, "EQUITY", "Media"),
    "RAMCOCEM": FnOInstrument("RAMCOCEM", "Ramco Cements", 750, 10, "EQUITY", "Cement"),
    "RBLBANK": FnOInstrument("RBLBANK", "RBL Bank", 2700, 2.5, "EQUITY", "Banking"),
    "RECLTD": FnOInstrument("RECLTD", "REC Ltd", 1250, 5, "EQUITY", "Finance"),
    "RELIANCE": FnOInstrument("RELIANCE", "Reliance Industries", 250, 20, "EQUITY", "Oil & Gas"),
    "SAIL": FnOInstrument("SAIL", "SAIL", 4250, 2.5, "EQUITY", "Metals"),
    "SBICARD": FnOInstrument("SBICARD", "SBI Cards", 700, 10, "EQUITY", "Finance"),
    "SBILIFE": FnOInstrument("SBILIFE", "SBI Life Insurance", 500, 10, "EQUITY", "Insurance"),
    "SBIN": FnOInstrument("SBIN", "State Bank of India", 750, 10, "EQUITY", "Banking"),
    "SHREECEM": FnOInstrument("SHREECEM", "Shree Cement", 25, 250, "EQUITY", "Cement"),
    "SHRIRAMFIN": FnOInstrument("SHRIRAMFIN", "Shriram Finance", 250, 20, "EQUITY", "Finance"),
    "SIEMENS": FnOInstrument("SIEMENS", "Siemens", 75, 100, "EQUITY", "Capital Goods"),
    "SRF": FnOInstrument("SRF", "SRF Ltd", 250, 20, "EQUITY", "Chemicals"),
    "SUNPHARMA": FnOInstrument("SUNPHARMA", "Sun Pharma", 350, 10, "EQUITY", "Pharma"),
    "SUNTV": FnOInstrument("SUNTV", "Sun TV Network", 1000, 5, "EQUITY", "Media"),
    "SYNGENE": FnOInstrument("SYNGENE", "Syngene Intl", 800, 5, "EQUITY", "Pharma"),
    "TATACHEM": FnOInstrument("TATACHEM", "Tata Chemicals", 500, 10, "EQUITY", "Chemicals"),
    "TATACOMM": FnOInstrument("TATACOMM", "Tata Communications", 375, 10, "EQUITY", "Telecom"),
    "TATACONSUM": FnOInstrument("TATACONSUM", "Tata Consumer Products", 600, 10, "EQUITY", "FMCG"),
    "TATAMOTORS": FnOInstrument("TATAMOTORS", "Tata Motors", 550, 10, "EQUITY", "Auto"),
    "TATAPOWER": FnOInstrument("TATAPOWER", "Tata Power", 1350, 5, "EQUITY", "Power"),
    "TATASTEEL": FnOInstrument("TATASTEEL", "Tata Steel", 5500, 1, "EQUITY", "Metals"),
    "TCS": FnOInstrument("TCS", "Tata Consultancy Services", 175, 25, "EQUITY", "IT"),
    "TECHM": FnOInstrument("TECHM", "Tech Mahindra", 600, 10, "EQUITY", "IT"),
    "TITAN": FnOInstrument("TITAN", "Titan Company", 175, 25, "EQUITY", "Consumer"),
    "TORNTPHARM": FnOInstrument("TORNTPHARM", "Torrent Pharma", 250, 20, "EQUITY", "Pharma"),
    "TORNTPOWER": FnOInstrument("TORNTPOWER", "Torrent Power", 750, 5, "EQUITY", "Power"),
    "TRENT": FnOInstrument("TRENT", "Trent Ltd", 100, 50, "EQUITY", "Consumer"),
    "TVSMOTOR": FnOInstrument("TVSMOTOR", "TVS Motor", 175, 25, "EQUITY", "Auto"),
    "UBL": FnOInstrument("UBL", "United Breweries", 350, 10, "EQUITY", "Consumer"),
    "ULTRACEMCO": FnOInstrument("ULTRACEMCO", "UltraTech Cement", 50, 100, "EQUITY", "Cement"),
    "UNIONBANK": FnOInstrument("UNIONBANK", "Union Bank", 5000, 1, "EQUITY", "Banking"),
    "UNITDSPR": FnOInstrument("UNITDSPR", "United Spirits", 350, 10, "EQUITY", "Consumer"),
    "UPL": FnOInstrument("UPL", "UPL Ltd", 1300, 5, "EQUITY", "Chemicals"),
    "VEDL": FnOInstrument("VEDL", "Vedanta", 1550, 5, "EQUITY", "Metals"),
    "VOLTAS": FnOInstrument("VOLTAS", "Voltas", 400, 10, "EQUITY", "Consumer"),
    "WIPRO": FnOInstrument("WIPRO", "Wipro", 1500, 5, "EQUITY", "IT"),
    "ZEEL": FnOInstrument("ZEEL", "Zee Entertainment", 3000, 2.5, "EQUITY", "Media"),
    "ZYDUSLIFE": FnOInstrument("ZYDUSLIFE", "Zydus Lifesciences", 700, 5, "EQUITY", "Pharma"),
}

# ── Combined lookup ───────────────────────────────────────────────────────
ALL_FNO: dict[str, FnOInstrument] = {**INDEX_FNO, **EQUITY_FNO}

# ── Convenience lists ─────────────────────────────────────────────────────
FNO_SYMBOLS: list[str] = sorted(EQUITY_FNO.keys())
INDEX_NAMES: list[str] = sorted(INDEX_FNO.keys())

# ── Sector groupings ─────────────────────────────────────────────────────
SECTORS: dict[str, list[str]] = {}
for _sym, _inst in EQUITY_FNO.items():
    SECTORS.setdefault(_inst.sector, []).append(_sym)
for _sector in SECTORS:
    SECTORS[_sector].sort()


def get_instrument(symbol: str) -> FnOInstrument | None:
    """Look up an FnO instrument by symbol."""
    return ALL_FNO.get(symbol)


def get_lot_size(symbol: str) -> int:
    """Return lot size for a symbol, default 1 if not found."""
    inst = ALL_FNO.get(symbol)
    return inst.lot_size if inst else 1


def get_strike_interval(symbol: str) -> float:
    """Return strike interval for a symbol."""
    inst = ALL_FNO.get(symbol)
    return inst.strike_interval if inst else 50.0


def get_sector_symbols(sector: str) -> list[str]:
    """Return all symbols in a given sector."""
    return SECTORS.get(sector, [])
