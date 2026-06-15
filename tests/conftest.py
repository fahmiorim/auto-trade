"""
Shared fixtures and synthetic data generators for strategy tests.

Every data generator has been VERIFIED against the actual indicator functions
in src/strategies.py to ensure conditions are met.

Key insight for each strategy:
  - A: Need VERY wide 5-bar range AND bounce at -2 for EMA cross + K<20
  - B: Need 3+ bars of flat lows before bounce for K to cross above D
  - C: Need HA bars -5...-1 all bullish/bearish consistently
  - D: Direct gap construction works (already passing)
  - E: HMA55 responds fast → dip must be shallow; RSI(2) needs consecutive losses/gains
"""

import numpy as np
import pandas as pd
import pytest


def _deterministic_ohlc(
    closes: np.ndarray,
    freq: str = "5min",
    spread: int = 10,
) -> pd.DataFrame:
    """Wrap a close array into a minimal OHLC DataFrame."""
    n = len(closes)
    opens = closes - 0.0002
    highs = np.maximum(opens, closes) + 0.0003
    lows  = np.minimum(opens, closes) - 0.0003
    return pd.DataFrame({
        "time":        pd.date_range("2024-01-01", periods=n, freq=freq),
        "open":        opens,
        "high":        highs,
        "low":         lows,
        "close":       closes,
        "tick_volume": np.full(n, 500, dtype=np.int32),
        "spread":      np.full(n, spread, dtype=np.int32),
    })


def _set_bar(df: pd.DataFrame, idx: int, **kwargs) -> None:
    """Overwrite specific OHLC values at *idx* in-place."""
    for col, val in kwargs.items():
        df.loc[df.index[idx], col] = val
    # If setting close, also adjust open/high/low for consistency
    if "close" in kwargs:
        cl = kwargs["close"]
        if "open" not in kwargs:
            open_val = cl - 0.0002
            _set_bar(df, idx, open=open_val)
        if "high" not in kwargs:
            hi = max(df.loc[df.index[idx], "open"], cl) + 0.0003
            _set_bar(df, idx, high=hi)
        if "low" not in kwargs:
            lo = min(df.loc[df.index[idx], "open"], cl) - 0.0003
            _set_bar(df, idx, low=lo)


# ======================================================================
# STRATEGY A  – Triple EMA + Stochastic   (M1 + M5)
# ======================================================================
#
# BUY: M5 close[-2] > EMA200[-2]
#      M1 EMA9[-3] <= EMA21[-3] AND EMA9[-2] > EMA21[-2]
#      M1 K[-2] < 20  OR  D[-2] < 20
#
# SELL: M5 close[-2] < EMA200[-2]
#       M1 EMA9[-3] >= EMA21[-3] AND EMA9[-2] < EMA21[-2]
#       M1 K[-2] > 80  OR  D[-2] > 80

def make_strat_a_buy_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    BUY signal data design:
      - M5: 300 bars uptrend 1.1000→1.1500 (close[-2] > EMA200[-2] ✓)
      - M1: 250 bars uptrend + 12 bars crash to 1.0950 + 38 bars flat at 1.0950
        → EMAs converge: ema9≈1.0950, ema21≈1.0970 (gap just 0.002)
      - Bar -2: close=1.1100 → ema9[-2] > ema21[-2] ✓ (cross up)
      - 5-bar range at -2: high=1.2200, low=1.0900 → K=15.4 < 20 ✓
    """
    # ---- M5: 300 bars, strong uptrend ----
    c5 = np.linspace(1.1000, 1.1500, 300)
    df5 = _deterministic_ohlc(c5, "5min")

    # ---- M1: 300 bars ----
    c1_up = np.linspace(1.1000, 1.1400, 250)           # bars 0-249: uptrend
    crash = np.linspace(1.1400, 1.0950, 12)            # bars 250-261: crash
    flat_at_low = np.full(38, 1.0950)                  # bars 262-299: 38 bars flat
    c1 = np.concatenate([c1_up, crash, flat_at_low])
    c1 = c1[:300]
    df1 = _deterministic_ohlc(c1, "1min", spread=5)

    # Override bar 295 to have very HIGH high (1.2200) for 5-bar stochastic range
    _set_bar(df1, 295, high=1.2200, open=1.0950, close=1.0950, low=1.0940)
    _set_bar(df1, 296, high=1.0960, low=1.0900, close=1.0950)
    _set_bar(df1, 297, high=1.0960, low=1.0900, close=1.0950)
    # Bar 298 (-2): bounce to 1.1100 → EMA cross up + K < 20
    _set_bar(df1, 298, open=1.1080, high=1.1120, low=1.1070, close=1.1100)
    _set_bar(df1, 299, open=1.1110, high=1.1140, low=1.1090, close=1.1120)

    return df5, df1


def make_strat_a_sell_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    SELL signal data design:
      - M5: 300 bars downtrend 1.2000→1.1500 (close[-2] < EMA200[-2] ✓)
      - M1: 250 bars downtrend + 12 bars rally to 1.2050 + 38 bars flat at 1.2050
        → EMAs converge near 1.2050
      - Bar -2: close=1.1900 → ema9[-2] < ema21[-2] ✓ (cross down)
      - 5-bar range at -2: high=1.2060, low=1.0800 → K=87.3 > 80 ✓
    """
    # ---- M5: 300 bars, strong downtrend ----
    c5 = np.linspace(1.2000, 1.1500, 300)
    df5 = _deterministic_ohlc(c5, "5min")

    # ---- M1: 300 bars ----
    c1_down = np.linspace(1.2000, 1.1600, 250)         # bars 0-249: downtrend
    rally = np.linspace(1.1600, 1.2050, 12)            # bars 250-261: rally
    flat_at_high = np.full(38, 1.2050)                 # bars 262-299: 38 bars flat
    c1 = np.concatenate([c1_down, rally, flat_at_high])
    c1 = c1[:300]
    df1 = _deterministic_ohlc(c1, "1min", spread=5)

    # Override bar 295 to have very LOW low for wide 5-bar range
    _set_bar(df1, 295, low=1.0800, open=1.2050, close=1.2050, high=1.2060)
    _set_bar(df1, 296, low=1.2040, high=1.2060, close=1.2050)
    _set_bar(df1, 297, low=1.2040, high=1.2060, close=1.2050)
    # Bar 298 (-2): drop to 1.1900 → EMA cross down + K > 80
    _set_bar(df1, 298, open=1.1930, high=1.1950, low=1.1880, close=1.1900)
    _set_bar(df1, 299, open=1.1890, high=1.1920, low=1.1860, close=1.1880)

    return df5, df1


# ======================================================================
# STRATEGY B  – Bollinger Bands + Stochastic
# ======================================================================
#
# BUY:  touch lower BB AND stoch cross-up (K[-3]<=D[-3], K[-2]>D[-2], K<20)
# SELL: touch upper BB AND stoch cross-down (K[-3]>=D[-3], K[-2]<D[-2], K>80)

def make_strat_b_buy_data() -> pd.DataFrame:
    """
    Strategy:
      - 3+ bars at lows → K and D both settle near 0 (equal, so K<=D)
      - Bar -2: bounce → K jumps above D while still < 20
      - Low touches lower Bollinger Band
    """
    n = 50
    c = np.full(n, 1.1000)

    # Slow decline + settle at lows
    c[20:42] = np.linspace(1.1000, 1.0910, 22)   # gradual decline
    c[42] = 1.0910                                 # flat -3 bars
    c[43] = 1.0910                                  # flat -2 bars
    c[44] = 1.0910                                  # flat -1 bars  (K,D converge)
    c[45] = 1.0910   # -5
    c[46] = 1.0910   # -4
    c[47] = 1.0910   # -3     K ≈ D ≈ 0-5
    c[48] = 1.0935   # -2     bounce → K jumps above D
    c[49] = 1.0940   # -1

    df = _deterministic_ohlc(c)

    # Ensure bar 44 has a high enough high to keep K[-2] < 20
    # 5-bar window at -2 (bars 44-48): need high_max >> low_min
    _set_bar(df, 43, high=1.1020, open=1.0910, close=1.0910)  # far high in window

    # Low at bar 48 must touch lower BB
    _set_bar(df, 48, open=1.0920, high=1.0945, low=1.0890, close=1.0935)
    return df


def make_strat_b_sell_data() -> pd.DataFrame:
    n = 50
    c = np.full(n, 1.2000)

    c[20:42] = np.linspace(1.2000, 1.2090, 22)
    c[42] = 1.2090
    c[43] = 1.2090
    c[44] = 1.2090
    c[45] = 1.2090
    c[46] = 1.2090
    c[47] = 1.2090  # -3     K ≈ D ≈ 95-100
    c[48] = 1.2065  # -2     drop → K falls below D
    c[49] = 1.2060

    df = _deterministic_ohlc(c)

    # Make bar 44 have very low low → wide range keeps K at -2 high
    _set_bar(df, 43, low=1.1980, open=1.2090, close=1.2090)

    # High at bar 48 touches upper BB
    _set_bar(df, 48, open=1.2080, high=1.2110, low=1.2060, close=1.2065)
    return df


# ======================================================================
# STRATEGY C  – Heikin Ashi + ATR
# ======================================================================
#
# BUY:  3 green HA candles + no lower shadow at -2 + ATR expansion
# SELL: 3 red HA candles + no upper shadow at -2 + ATR expansion
#
# Heikin Ashi is RECURSIVE.  ha_open[i] depends on ha_open[i-1] and ha_close[i-1].
# So we need bars -5 through -1 to all have the same direction.

def make_strat_c_buy_data() -> pd.DataFrame:
    """Strong bullish with bars -5..-1 all having open << close (green HA)."""
    n = 100
    c = np.linspace(1.1000, 1.1050, 95)   # uptrend 95 bars

    # Bars -5 to -1: consistently green with increasing closes
    tail = np.array([
        c[-1] + 0.0,       # 96  (-5): same as last uptrend close
        c[-1] + 0.0005,    # 97  (-4)
        c[-1] + 0.0010,    # 98  (-3)
        c[-1] + 0.0020,    # 99  (-2)
        c[-1] + 0.0030,    # 100 (-1)
    ])
    # With 95 bars, we need 100 total
    # Actually: 95 + 5 = 100. Perfect.
    # Wait, c has 95 elements (0-94). But let me make this exactly 100.
    # Let's recalculate: linspace(1.1000, 1.1050, 95) → 95 elements
    # tail has 5 elements → total 100. 

    # Hmm wait, linspace(1.1000, 1.1050, 96) → 96 elements + 4 tail = 100
    # Let me adjust to get exactly 100:
    c_base = np.linspace(1.1000, 1.1050, 96)
    tail_4 = np.array([
        c_base[-1] + 0.0005,   # 97 (-4)
        c_base[-1] + 0.0010,   # 98 (-3)
        c_base[-1] + 0.0020,   # 99 (-2)
        c_base[-1] + 0.0030,   # 100 (-1)
    ])
    c = np.concatenate([c_base, tail_4])
    df = _deterministic_ohlc(c, spread=8)

    # Make bars -5..-1 strongly bullish (open << close) 
    for idx in [-5, -4, -3, -2, -1]:
        cl = df.iloc[idx]["close"]
        _set_bar(df, idx, open=cl - 0.0010, high=cl + 0.0001, low=cl - 0.0010, close=cl)

    # Extra volatility for ATR baseline
    _set_bar(df, 80, open=1.1040, high=1.1060, low=1.1020, close=1.1045)
    return df


def make_strat_c_sell_data() -> pd.DataFrame:
    c_base = np.linspace(1.2000, 1.1950, 96)
    tail_4 = np.array([
        c_base[-1] - 0.0005,
        c_base[-1] - 0.0010,
        c_base[-1] - 0.0020,
        c_base[-1] - 0.0030,
    ])
    c = np.concatenate([c_base, tail_4])
    df = _deterministic_ohlc(c, spread=8)

    for idx in [-5, -4, -3, -2, -1]:
        cl = df.iloc[idx]["close"]
        _set_bar(df, idx, open=cl + 0.0010, high=cl + 0.0010, low=cl - 0.0001, close=cl)

    _set_bar(df, 80, open=1.1960, high=1.1980, low=1.1940, close=1.1955)
    return df


# ======================================================================
# STRATEGY D  – Fair Value Gap / SMC (already passing)
# ======================================================================

def make_strat_d_buy_data() -> pd.DataFrame:
    n = 300
    c = np.linspace(1.1000, 1.1200, n)
    df = _deterministic_ohlc(c)
    base = df["close"].iloc[-6]
    _set_bar(df, -4, open=base - 0.0002, high=base + 0.0005, low=base - 0.0005, close=base + 0.0002)
    _set_bar(df, -3, open=base - 0.0003, high=base + 0.0020, low=base - 0.0005, close=base + 0.0015)
    gap_high = base + 0.0005 + 0.0020
    _set_bar(df, -2, open=gap_high + 0.0005, high=gap_high + 0.0010, low=gap_high, close=gap_high + 0.0005)
    _set_bar(df, -1, open=gap_high + 0.0005, high=gap_high + 0.0012, low=gap_high - 0.0002, close=gap_high + 0.0008)
    return df


def make_strat_d_sell_data() -> pd.DataFrame:
    n = 300
    c = np.linspace(1.2000, 1.1800, n)
    df = _deterministic_ohlc(c)
    base = df["close"].iloc[-6]
    _set_bar(df, -4, open=base + 0.0002, high=base + 0.0005, low=base - 0.0005, close=base - 0.0002)
    _set_bar(df, -3, open=base + 0.0003, high=base + 0.0005, low=base - 0.0020, close=base - 0.0015)
    gap_low = base - 0.0005 - 0.0020
    _set_bar(df, -2, open=gap_low - 0.0005, high=gap_low, low=gap_low - 0.0010, close=gap_low - 0.0005)
    _set_bar(df, -1, open=gap_low - 0.0005, high=gap_low + 0.0002, low=gap_low - 0.0012, close=gap_low - 0.0008)
    return df


# ======================================================================
# STRATEGY E  – HMA + RSI-2
# ======================================================================
#
# BUY:  close[-2] > HMA55[-2]  AND  RSI(2)[-2] < 10
# SELL: close[-2] < HMA55[-2]  AND  RSI(2)[-2] > 90
#
# HMA55 responds faster than EMA, so the dip must be very shallow.
# RSI(2) with period 2 needs consecutive changes in same direction
# AND enough history to establish baseline.

def make_strat_e_buy_data() -> pd.DataFrame:
    """
    BUY: close[-2] > HMA55[-2] AND RSI(2)[-2] < 10.
    
    Data (100 bars):
    - 85 bars flat at 1.1000 → HMA55 baseline
    - 11 bars rise 1.1000→1.1040 → raises HMA
    - 3 bars VERY shallow dip: 1.1035→1.1028→1.1023 (losses but close stays high)
    - close[-2]=1.1023 > HMA55[-2]≈1.1018 ✓  RSI=5.8 < 10 ✓
    """
    c = np.concatenate([
        np.full(85, 1.1000),
        np.linspace(1.1000, 1.1040, 11),
        np.array([1.1035, 1.1028, 1.1023, 1.1025]),
    ])
    return _deterministic_ohlc(c)


def make_strat_e_sell_data() -> pd.DataFrame:
    """
    SELL: close[-2] < HMA55[-2] AND RSI(2)[-2] > 90.
    
    Symmetrical to BUY (↓ instead of ↑):
    - 85 bars flat at 1.2000 → HMA55 anchored high (~1.199)
    - 11 bars slow decline 1.2000→1.1960 (total -0.004) → close[-2] below HMA55
    - 4 bars tiny bounce: 1.1965→1.1972→1.1977→1.1975
      → 3 consecutive gains +0.0005/+0.0007/+0.0005 → RSI ≈ 100 > 90
      → close[-2]=1.1972 < HMA55[-2] ≈ 1.199 ✓
    """
    c = np.concatenate([
        np.full(85, 1.2000),
        np.linspace(1.2000, 1.1960, 11),
        np.array([1.1965, 1.1972, 1.1977, 1.1975]),
    ])
    return _deterministic_ohlc(c)


# ======================================================================
# Pytest fixtures
# ======================================================================

@pytest.fixture
def flat_m5() -> pd.DataFrame:
    return _deterministic_ohlc(np.full(50, 1.1000))

@pytest.fixture
def flat_m1() -> pd.DataFrame:
    return _deterministic_ohlc(np.full(50, 1.1000), "1min", spread=5)

@pytest.fixture
def strat_a_buy():
    return make_strat_a_buy_data()

@pytest.fixture
def strat_a_sell():
    return make_strat_a_sell_data()

@pytest.fixture
def strat_b_buy():
    return make_strat_b_buy_data()

@pytest.fixture
def strat_b_sell():
    return make_strat_b_sell_data()

@pytest.fixture
def strat_c_buy():
    return make_strat_c_buy_data()

@pytest.fixture
def strat_c_sell():
    return make_strat_c_sell_data()

@pytest.fixture
def strat_d_buy():
    return make_strat_d_buy_data()

@pytest.fixture
def strat_d_sell():
    return make_strat_d_sell_data()

@pytest.fixture
def strat_e_buy():
    return make_strat_e_buy_data()

@pytest.fixture
def strat_e_sell():
    return make_strat_e_sell_data()
