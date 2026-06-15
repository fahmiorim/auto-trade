import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def fetch_history(symbol: str, timeframe: int, count: int) -> pd.DataFrame:
    """
    Mengambil data harga historis (candlestick) dari MT5 dan mengonversinya ke Pandas DataFrame.
    Asumsi MT5 sudah diinisialisasi oleh pemanggil (misal main.py).
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
        
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread']]
    
    return df

def get_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    Mengonversi data candlestick standar (OHLC) menjadi Heikin Ashi.
    """
    if df.empty:
        return df
        
    df_ha = df.copy()
    df_ha['ha_close'] = (df['open'] + df['high'] + df['low'] + df['close']) / 4.0
    
    ha_open = np.zeros(len(df))
    ha_open[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2.0
    for i in range(1, len(df)):
        ha_open[i] = (ha_open[i-1] + df_ha['ha_close'].iloc[i-1]) / 2.0
        
    df_ha['ha_open'] = ha_open
    df_ha['ha_high'] = df_ha[['high', 'ha_open', 'ha_close']].max(axis=1)
    df_ha['ha_low'] = df_ha[['low', 'ha_open', 'ha_close']].min(axis=1)
    
    return df_ha
