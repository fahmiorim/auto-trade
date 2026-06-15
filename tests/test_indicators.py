"""
Unit tests for technical indicator functions in src/strategies.py.

Tests: calculate_ema, calculate_stochastic, calculate_bollinger_bands,
       calculate_atr, calculate_wma, calculate_hma, calculate_rsi.
"""

import numpy as np
import pandas as pd
import pytest

from src.strategies import (
    calculate_ema,
    calculate_stochastic,
    calculate_bollinger_bands,
    calculate_atr,
    calculate_wma,
    calculate_hma,
    calculate_rsi,
)

# Use the deterministic helper so tests are reproducible
from tests.conftest import _deterministic_ohlc


# ======================================================================
# calculate_ema
# ======================================================================

class TestCalculateEma:
    def test_ema_known_values(self):
        """EMA with span=3 and known input [1,2,3,4,5]."""
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        alpha = 2.0 / (3 + 1)  # 0.5

        expected = np.array([
            1.0,                          # first value
            1.0 * (1 - alpha) + 2.0 * alpha,  # = 1.5
            1.5 * (1 - alpha) + 3.0 * alpha,  # = 2.25
            2.25 * (1 - alpha) + 4.0 * alpha, # = 3.125
            3.125 * (1 - alpha) + 5.0 * alpha, # = 4.0625
        ])
        result = calculate_ema(series, 3).values
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_ema_constant_series(self):
        """EMA of a constant series equals the constant."""
        series = pd.Series([10.0] * 20)
        result = calculate_ema(series, 10)
        assert abs(result.iloc[-1] - 10.0) < 1e-10

    def test_ema_short_data(self):
        """Short series returns values without error."""
        series = pd.Series([1.0, 2.0])
        result = calculate_ema(series, 5)
        assert len(result) == 2
        assert not np.isnan(result.iloc[0])
        assert not np.isnan(result.iloc[1])


# ======================================================================
# calculate_stochastic
# ======================================================================

class TestCalculateStochastic:
    def test_stochastic_oversold_after_dip(self):
        """Stochastic %K should be < 20 after a deep dip in price."""
        n = 30
        closes = np.full(n, 1.1000)
        # Sharp dip at bars 10-14 (price drops to 1.0940)
        for i in range(10, 15):
            closes[i] = 1.0940
        # Return to normal
        for i in range(15, 20):
            closes[i] = 1.1020

        highs = closes + 0.001
        lows = closes - 0.001
        # Widen the 5-bar range: set high at bar 10 to create wider range
        highs[10] = 1.1000
        lows[10] = 1.0930
        df = pd.DataFrame({"high": highs, "low": lows, "close": closes})

        k, d = calculate_stochastic(df, 5, 3, 3)

        # After the dip at index 14, %K should be very low (< 20)
        assert k.iloc[14] < 20, f"Expected oversold after dip, got K={k.iloc[14]:.2f}"

        # After recovery at index 19, %K should be > 20
        assert k.iloc[19] >= 20, f"Expected recovery, got K={k.iloc[19]:.2f}"

    def test_stochastic_overbought_after_rally(self):
        """Stochastic %K should be > 80 after a sharp rally."""
        n = 30
        closes = np.full(n, 1.1000)
        for i in range(10, 15):
            closes[i] = 1.1050  # rally 50 pips
        for i in range(15, 20):
            closes[i] = 1.0980  # back down

        highs = closes + 0.001
        lows = closes - 0.001
        # Widen 5-bar range: low at bar 10
        lows[10] = 1.0970
        highs[10] = 1.1060
        df = pd.DataFrame({"high": highs, "low": lows, "close": closes})

        k, d = calculate_stochastic(df, 5, 3, 3)
        assert k.iloc[14] > 80, f"Expected overbought after rally, got K={k.iloc[14]:.2f}"

    def test_stochastic_bounds(self):
        """Stochastic values stay in [0, 100]."""
        df = _deterministic_ohlc(np.full(100, 1.1000))
        k, d = calculate_stochastic(df, 5, 3, 3)
        for arr in [k.dropna(), d.dropna()]:
            assert (arr >= 0).all() and (arr <= 100).all()


# ======================================================================
# calculate_bollinger_bands
# ======================================================================

class TestCalculateBollingerBands:
    def test_bb_middle_is_sma(self):
        """Middle band should equal rolling mean."""
        df = _deterministic_ohlc(np.linspace(1.1000, 1.1050, 50))
        upper, middle, lower = calculate_bollinger_bands(df, 20, 2.0)
        expected_middle = df["close"].rolling(20).mean()
        pd.testing.assert_series_equal(middle, expected_middle, check_names=False)

    def test_bb_symmetric(self):
        """Upper and lower bands are symmetric around the middle band."""
        df = _deterministic_ohlc(np.linspace(1.1000, 1.1050, 50))
        upper, middle, lower = calculate_bollinger_bands(df, 20, 2.0)
        diff_up = (upper - middle).dropna()
        diff_low = (middle - lower).dropna()
        np.testing.assert_allclose(diff_up, diff_low, rtol=1e-8)


# ======================================================================
# calculate_atr
# ======================================================================

class TestCalculateAtr:
    def test_atr_zero_range(self):
        """ATR of constant prices should be 0."""
        df = pd.DataFrame({
            "high":  [1.1000] * 30,
            "low":   [1.1000] * 30,
            "close": [1.1000] * 30,
        })
        atr = calculate_atr(df, 14)
        assert abs(atr.iloc[-1]) < 1e-10

    def test_atr_positive(self):
        """ATR should always be >= 0."""
        df = _deterministic_ohlc(np.linspace(1.1000, 1.1100, 100))
        atr = calculate_atr(df, 14)
        assert (atr.dropna() >= 0).all()


# ======================================================================
# calculate_wma  (Weighted Moving Average)
# ======================================================================

class TestCalculateWma:
    def test_wma_known_values(self):
        """WMA with period=3 on [1,2,3,4,5]."""
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        # WMA(3) weights: [1,2,3] / sum(6)
        # index 2: (1*1 + 2*2 + 3*3) / 6 = 14/6 = 2.333...
        # index 3: (2*1 + 3*2 + 4*3) / 6 = 20/6 = 3.333...
        # index 4: (3*1 + 4*2 + 5*3) / 6 = 26/6 = 4.333...
        result = calculate_wma(series, 3)
        expected = [np.nan, np.nan, 14 / 6, 20 / 6, 26 / 6]
        np.testing.assert_allclose(result, expected, rtol=1e-10, equal_nan=True)


# ======================================================================
# calculate_hma  (Hull Moving Average)
# ======================================================================

class TestCalculateHma:
    def test_hma_constant(self):
        """HMA of a constant series should equal the constant."""
        series = pd.Series([5.0] * 100)
        hma = calculate_hma(series, 55)
        assert abs(hma.iloc[-1] - 5.0) < 1e-6

    def test_hma_length(self):
        """HMA output has the same length as input."""
        series = pd.Series(np.random.default_rng(42).random(200) + 1.10)
        hma = calculate_hma(series, 55)
        assert len(hma) == len(series)


# ======================================================================
# calculate_rsi
# ======================================================================

class TestCalculateRsi:
    def test_rsi_constant(self):
        """
        RSI of an all-constant series.
        With zero deltas, gain=loss=0 → rs=0 → RSI=100-100/(1+0)=0.
        This is the correct mathematical result for RSI with no price movement.
        """
        series = pd.Series([10.0] * 30)
        rsi = calculate_rsi(series, 14)
        # RSI should be exactly 0 (no movement → avg_gain=avg_loss=0 → rs=0)
        assert abs(rsi.dropna().iloc[-1] - 0.0) < 1e-6

    def test_rsi_uptrend(self):
        """RSI should be > 50 during strong uptrend."""
        series = pd.Series(np.linspace(1.0, 2.0, 50))
        rsi = calculate_rsi(series, 14)
        assert rsi.dropna().iloc[-1] > 50

    def test_rsi_downtrend(self):
        """RSI should be < 50 during strong downtrend."""
        series = pd.Series(np.linspace(2.0, 1.0, 50))
        rsi = calculate_rsi(series, 14)
        assert rsi.dropna().iloc[-1] < 50

    def test_rsi_bounds(self):
        """RSI should always be in [0, 100]."""
        series = pd.Series(np.random.default_rng(42).random(200))
        rsi = calculate_rsi(series, 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()
