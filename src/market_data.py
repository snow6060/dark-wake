import yfinance as yf
import feedparser

def get_brent_price():
    try:
        ticker = yf.Ticker("BZ=F")
        todays_data = ticker.history(period="1d")
        if not todays_data.empty:
            return round(todays_data['Close'].iloc[-1], 2)
        return 100.00
    except Exception:
        return 100.00

def get_oil_news():
    rss_url = "https://news.google.com/rss/search?q=oil+prices+brent+crude&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)
    headlines = []
    for entry in feed.entries[:5]:
        headlines.append({
            "title": entry.title,
            "link": entry.link
        })
    return headlines