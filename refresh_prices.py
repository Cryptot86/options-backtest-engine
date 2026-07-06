from src.otbt.data.prices import get_prices
for s in ["^VIX","SPY","AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AMD",
          "NFLX","AVGO","JPM","COST","LLY","UNH","HD"]:
    df = get_prices(s, "2017-01-01", "2026-06-30", refresh=True)
    print(s, df.index.max().date(), flush=True)
print("PRICES REFRESHED")
