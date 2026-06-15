import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import pandas as pd
from datetime import datetime, timezone, timedelta
from . import config

_news_cache = None
_last_fetch_time = None

def fetch_economic_calendar() -> list:
    """
    Mengambil data kalender berita ekonomi mingguan dalam format JSON.
    """
    global _news_cache, _last_fetch_time
    
    current_time = datetime.now(timezone.utc)
    
    if _news_cache is not None and _last_fetch_time is not None:
        if (current_time - _last_fetch_time) < timedelta(hours=1):
            return _news_cache
            
    try:
        response = requests.get(config.cfg.ECONOMIC_CALENDAR_URL, timeout=10, verify=False)
        if response.status_code == 200:
            res_json = response.json()
            if isinstance(res_json, list):
                _news_cache = res_json
                _last_fetch_time = current_time
                return _news_cache
            else:
                print(f"[NewsFilter] Format JSON tidak valid: Diharapkan list, mendapat {type(res_json)}")
    except Exception as e:
        print(f"Gagal mengambil kalender berita: {e}. Mengabaikan filter berita.")
        
    return _news_cache if _news_cache is not None else []

def is_news_blocked(symbol: str) -> bool:
    """
    Memeriksa apakah saat ini berada dalam jendela waktu pemblokiran berita High Impact.
    """
    calendar = fetch_economic_calendar()
    if not calendar:
        return False
        
    base_currency = symbol[:3]
    quote_currency = symbol[3:6]
    relevant_currencies = {base_currency, quote_currency}
    
    current_utc = datetime.now(timezone.utc)
    
    for event in calendar:
        if event.get("impact") != "High":
            continue
            
        event_currency = event.get("country")
        if event_currency and event_currency.lower() != "all" and event_currency not in relevant_currencies:
            continue
            
        event_time_str = event.get("date")
        if not event_time_str:
            continue
            
        try:
            event_utc = pd.to_datetime(event_time_str).to_pydatetime()
            if event_utc.tzinfo is None:
                event_utc = event_utc.replace(tzinfo=timezone.utc)
            else:
                event_utc = event_utc.astimezone(timezone.utc)
                
            block_start = event_utc - timedelta(minutes=config.cfg.NEWS_BLOCK_BEFORE)
            block_end = event_utc + timedelta(minutes=config.cfg.NEWS_BLOCK_AFTER)
            
            if block_start <= current_utc <= block_end:
                print(f"[News Filter] BLOKIR: Berita High Impact ({event.get('title')}) untuk {event_currency} pada {event_utc.strftime('%H:%M')} UTC")
                return True
                
        except Exception as e:
            continue
            
    return False
