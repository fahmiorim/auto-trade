import pandas as pd
import numpy as np
from .data_fetcher import get_heikin_ashi
from . import config

# ==========================================
# FUNGSI PERHITUNGAN INDIKATOR TEKNIKAL
# ==========================================

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Menghitung Exponential Moving Average (EMA)."""
    return series.ewm(span=period, adjust=False).mean()

def calculate_stochastic(df: pd.DataFrame, k_period: int = 5, d_period: int = 3, slowing: int = 3) -> tuple:
    """
    Menghitung Stochastic Oscillator (%K dan %D).
    """
    df_temp = df.copy()
    
    low_min = df_temp['low'].rolling(window=k_period).min()
    high_max = df_temp['high'].rolling(window=k_period).max()
    
    raw_k = 100 * (df_temp['close'] - low_min) / (high_max - low_min + 1e-9)
    k_line = raw_k.rolling(window=slowing).mean()
    d_line = k_line.rolling(window=d_period).mean()
    
    return k_line, d_line

def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, deviation: float = 2.0) -> tuple:
    """
    Menghitung Bollinger Bands (Upper, Middle, Lower).
    """
    middle_band = df['close'].rolling(window=period).mean()
    std_dev = df['close'].rolling(window=period).std()
    
    upper_band = middle_band + (deviation * std_dev)
    lower_band = middle_band - (deviation * std_dev)
    
    return upper_band, middle_band, lower_band

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Menghitung Average True Range (ATR) menggunakan penghalusan Wilder.
    """
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    
    atr = true_range.ewm(alpha=1.0/period, adjust=False).mean()
    return atr

def calculate_wma(series: pd.Series, period: int) -> pd.Series:
    """Menghitung Weighted Moving Average (WMA) teroptimasi dengan NumPy stride tricks."""
    if len(series) < period:
        return pd.Series(np.nan, index=series.index)
        
    weights = np.arange(1, period + 1)
    sum_weights = weights.sum()
    
    x = np.ascontiguousarray(series.values, dtype=np.float64)
    shape = (x.size - period + 1, period)
    strides = (x.strides[0], x.strides[0])
    rolling_matrix = np.lib.stride_tricks.as_strided(x, shape=shape, strides=strides)
    
    wma_values = np.dot(rolling_matrix, weights) / sum_weights
    
    padded = np.empty(series.size)
    padded[:period - 1] = np.nan
    padded[period - 1:] = wma_values
    
    return pd.Series(padded, index=series.index)


def calculate_hma(series: pd.Series, period: int) -> pd.Series:
    """Menghitung Hull Moving Average (HMA)."""
    half_period = int(period / 2)
    sqrt_period = int(np.sqrt(period))
    
    wma_half = calculate_wma(series, half_period)
    wma_full = calculate_wma(series, period)
    
    diff = 2 * wma_half - wma_full
    hma = calculate_wma(diff, sqrt_period)
    return hma

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Menghitung Relative Strength Index (RSI) dengan penghalusan Wilder."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    
    # Wilder's smoothing via ewm
    avg_gain = gain.ewm(alpha=1.0/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/period, adjust=False).mean()
    
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi

# ==========================================
# LOGIKA STRATEGI TRADING (METODE A, B, C, D, E)
# ==========================================

def strategy_a_triple_ema_stochastic(df_m1: pd.DataFrame, df_m5: pd.DataFrame) -> int:
    """
    Metode A: Triple EMA + Stochastic Momentum Filter.
    - Filter Tren Utama (M5): Close > EMA 200 (Tren Naik), Close < EMA 200 (Tren Turun).
    - Pemicu Tren (M1): Persilangan EMA 9 & EMA 21.
    - Pemicu Entry (M1): Stochastic (5,3,3) berada di Oversold (<30) untuk Buy, atau Overbought (>70) untuk Sell.
    """
    if len(df_m1) < 250 or len(df_m5) < 250:
        return 0  # Data belum cukup untuk indikator
        
    m5_close = df_m5['close']
    m5_ema_slow = calculate_ema(m5_close, 200)
    
    is_trend_up = m5_close.iloc[-2] > m5_ema_slow.iloc[-2]
    is_trend_down = m5_close.iloc[-2] < m5_ema_slow.iloc[-2]
    
    m1_close = df_m1['close']
    m1_ema_fast = calculate_ema(m1_close, 9)
    m1_ema_med = calculate_ema(m1_close, 21)
    
    k_line, d_line = calculate_stochastic(df_m1, 5, 3, 3)
    
    m1_cross_up = (m1_ema_fast.iloc[-3] <= m1_ema_med.iloc[-3]) and (m1_ema_fast.iloc[-2] > m1_ema_med.iloc[-2])
    m1_cross_down = (m1_ema_fast.iloc[-3] >= m1_ema_med.iloc[-3]) and (m1_ema_fast.iloc[-2] < m1_ema_med.iloc[-2])
    
    stoch_oversold = k_line.iloc[-2] < config.cfg.STO_OVERSOLD or d_line.iloc[-2] < config.cfg.STO_OVERSOLD
    stoch_overbought = k_line.iloc[-2] > config.cfg.STO_OVERBOUGHT or d_line.iloc[-2] > config.cfg.STO_OVERBOUGHT
    
    if is_trend_up and m1_cross_up and stoch_oversold:
        return 1  # BUY SIGNAL
    elif is_trend_down and m1_cross_down and stoch_overbought:
        return -1 # SELL SIGNAL
        
    return 0  # NO SIGNAL


def strategy_b_bollinger_bands_stochastic(df_m5: pd.DataFrame) -> int:
    """
    Metode B: Bollinger Bands + Stochastic Mean Reversion.
    - Cocok untuk pasar mendatar (sideway/ranging) di timeframe M5.
    - BUY: Lilin menyentuh/menembus Lower Band & Stochastic cross up di area Oversold (<30).
    - SELL: Lilin menyentuh/menembus Upper Band & Stochastic cross down di area Overbought (>70).
    """
    if len(df_m5) < 30:
        return 0
        
    upper_band, middle_band, lower_band = calculate_bollinger_bands(df_m5, 20, 2.0)
    k_line, d_line = calculate_stochastic(df_m5, 5, 3, 3)
    
    close_price = df_m5['close'].iloc[-2]
    high_price = df_m5['high'].iloc[-2]
    low_price = df_m5['low'].iloc[-2]
    
    stoch_cross_up = (k_line.iloc[-3] <= d_line.iloc[-3]) and (k_line.iloc[-2] > d_line.iloc[-2]) and (k_line.iloc[-2] < config.cfg.STO_OVERSOLD or k_line.iloc[-3] < config.cfg.STO_OVERSOLD)
    stoch_cross_down = (k_line.iloc[-3] >= d_line.iloc[-3]) and (k_line.iloc[-2] < d_line.iloc[-2]) and (k_line.iloc[-2] > config.cfg.STO_OVERBOUGHT or k_line.iloc[-3] > config.cfg.STO_OVERBOUGHT)
    
    touch_lower = (low_price <= lower_band.iloc[-2]) or (close_price <= lower_band.iloc[-2])
    touch_upper = (high_price >= upper_band.iloc[-2]) or (close_price >= upper_band.iloc[-2])
    
    if touch_lower and stoch_cross_up:
        return 1  # BUY SIGNAL
    elif touch_upper and stoch_cross_down:
        return -1 # SELL SIGNAL
        
    return 0


def strategy_c_heikin_ashi_atr(df_m5: pd.DataFrame) -> int:
    """
    Metode C: Heikin Ashi + ATR Breakout Momentum (Timeframe M5).
    - BUY: 3 lilin Heikin Ashi hijau berturut-turut, tanpa bayangan bawah, ATR > ATR SMA.
    - SELL: 3 lilin Heikin Ashi merah berturut-turut, tanpa bayangan atas, ATR > ATR SMA.
    """
    if len(df_m5) < 70:
        return 0
        
    df_ha = get_heikin_ashi(df_m5)
    
    atr = calculate_atr(df_m5, 14)
    atr_sma = atr.rolling(window=50).mean()
    
    ha_open = df_ha['ha_open']
    ha_high = df_ha['ha_high']
    ha_low = df_ha['ha_low']
    ha_close = df_ha['ha_close']
    
    is_3_green = (ha_close.iloc[-4] > ha_open.iloc[-4]) and \
                 (ha_close.iloc[-3] > ha_open.iloc[-3]) and \
                 (ha_close.iloc[-2] > ha_open.iloc[-2])
                 
    is_3_red = (ha_close.iloc[-4] < ha_open.iloc[-4]) and \
               (ha_close.iloc[-3] < ha_open.iloc[-3]) and \
               (ha_close.iloc[-2] < ha_open.iloc[-2])
               
    tolerance = 1e-6
    no_lower_shadow = ha_low.iloc[-2] >= (ha_open.iloc[-2] - tolerance)
    no_upper_shadow = ha_high.iloc[-2] <= (ha_open.iloc[-2] + tolerance)
    
    volatility_expansion = atr.iloc[-2] > atr_sma.iloc[-2]
    
    if is_3_green and no_lower_shadow and volatility_expansion:
        return 1  # BUY SIGNAL
    elif is_3_red and no_upper_shadow and volatility_expansion:
        return -1 # SELL SIGNAL
        
    return 0


def strategy_d_fvg_smc(df_m5: pd.DataFrame) -> int:
    """
    Metode D: Fair Value Gap (FVG) / Smart Money Concepts (SMC) (Timeframe M5).
    - BUY: Bullish FVG terbentuk di candle [-4], [-3], [-2], close > EMA 200, dan gap > 0.5 * ATR.
    - SELL: Bearish FVG terbentuk di candle [-4], [-3], [-2], close < EMA 200, dan gap > 0.5 * ATR.
    """
    if len(df_m5) < 250:
        return 0
        
    close = df_m5['close']
    open_p = df_m5['open']
    high = df_m5['high']
    low = df_m5['low']
    
    ema200 = calculate_ema(close, 200)
    atr = calculate_atr(df_m5, 14)
    
    # Lilin ke-3 (-2), lilin ke-2 (-3), lilin ke-1 (-4)
    is_bullish_fvg = (low.iloc[-2] > high.iloc[-4]) and (close.iloc[-3] > open_p.iloc[-3])
    is_bearish_fvg = (high.iloc[-2] < low.iloc[-4]) and (close.iloc[-3] < open_p.iloc[-3])
    
    atr_val = atr.iloc[-2]
    ema_val = ema200.iloc[-2]
    close_val = close.iloc[-2]
    
    if is_bullish_fvg and (close_val > ema_val):
        gap = low.iloc[-2] - high.iloc[-4]
        if gap > 0.5 * atr_val:
            return 1
            
    elif is_bearish_fvg and (close_val < ema_val):
        gap = low.iloc[-4] - high.iloc[-2]
        if gap > 0.5 * atr_val:
            return -1
            
    return 0


def strategy_e_hma_rsi(df_m5: pd.DataFrame) -> int:
    """
    Metode E: Hull Moving Average (HMA) + RSI-2 Mean Reversion (Timeframe M5).
    - BUY: Close > HMA 55 (Trend Up) dan RSI(2) < 10 (Oversold).
    - SELL: Close < HMA 55 (Trend Down) dan RSI(2) > 90 (Overbought).
    """
    if len(df_m5) < 70:
        return 0
        
    close = df_m5['close']
    hma55 = calculate_hma(close, 55)
    rsi2 = calculate_rsi(close, 2)
    
    close_val = close.iloc[-2]
    hma_val = hma55.iloc[-2]
    rsi_val = rsi2.iloc[-2]
    
    if (close_val > hma_val) and (rsi_val < 10):
        return 1
    elif (close_val < hma_val) and (rsi_val > 90):
        return -1
        
    return 0
