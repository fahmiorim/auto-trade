"""
Unit tests for all 5 trading strategy functions.

Each strategy is tested with:
  - BUY signal data   → expects signal == 1
  - SELL signal data  → expects signal == -1
  - Flat/noise data   → expects signal == 0
  - Insufficient data → expects signal == 0  (edge case)
"""

import pandas as pd
import numpy as np
import pytest

from src.strategies import (
    strategy_a_triple_ema_stochastic,
    strategy_b_bollinger_bands_stochastic,
    strategy_c_heikin_ashi_atr,
    strategy_d_fvg_smc,
    strategy_e_hma_rsi,
)
from tests.conftest import _deterministic_ohlc


# ======================================================================
# Strategy A — Triple EMA + Stochastic  (M1 + M5)
# ======================================================================

class TestStrategyA:
    def test_buy_signal(self, strat_a_buy):
        """Should return 1 (BUY) for engineered bullish pattern."""
        df_m5, df_m1 = strat_a_buy
        signal = strategy_a_triple_ema_stochastic(df_m1, df_m5)
        assert signal == 1, f"Expected BUY (1), got {signal}"

    def test_sell_signal(self, strat_a_sell):
        """Should return -1 (SELL) for engineered bearish pattern."""
        df_m5, df_m1 = strat_a_sell
        signal = strategy_a_triple_ema_stochastic(df_m1, df_m5)
        assert signal == -1, f"Expected SELL (-1), got {signal}"

    def test_no_signal_flat(self, flat_m5, flat_m1):
        """Flat random data should NOT produce a signal."""
        signal = strategy_a_triple_ema_stochastic(flat_m1, flat_m5)
        assert signal == 0, f"Expected no signal (0), got {signal}"

    def test_insufficient_data_m1(self):
        """Less than 250 bars on M1 should return 0."""
        df_m1 = _deterministic_ohlc(np.full(100, 1.1000), "1min", spread=5)
        df_m5 = _deterministic_ohlc(np.full(300, 1.1000))
        signal = strategy_a_triple_ema_stochastic(df_m1, df_m5)
        assert signal == 0

    def test_insufficient_data_m5(self):
        """Less than 250 bars on M5 should return 0."""
        df_m1 = _deterministic_ohlc(np.full(300, 1.1000), "1min", spread=5)
        df_m5 = _deterministic_ohlc(np.full(100, 1.1000))
        signal = strategy_a_triple_ema_stochastic(df_m1, df_m5)
        assert signal == 0

    def test_empty_dataframe(self):
        """Empty DataFrames should be handled gracefully → no signal."""
        signal = strategy_a_triple_ema_stochastic(pd.DataFrame(), pd.DataFrame())
        assert signal == 0


# ======================================================================
# Strategy B — Bollinger Bands + Stochastic
# ======================================================================

class TestStrategyB:
    def test_buy_signal(self, strat_b_buy):
        """Should return 1 (BUY) when price touches lower band + stoch cross up."""
        signal = strategy_b_bollinger_bands_stochastic(strat_b_buy)
        assert signal == 1, f"Expected BUY (1), got {signal}"

    def test_sell_signal(self, strat_b_sell):
        """Should return -1 (SELL) when price touches upper band + stoch cross down."""
        signal = strategy_b_bollinger_bands_stochastic(strat_b_sell)
        assert signal == -1, f"Expected SELL (-1), got {signal}"

    def test_no_signal_flat(self, flat_m5):
        """Flat data should NOT produce a signal."""
        signal = strategy_b_bollinger_bands_stochastic(flat_m5)
        assert signal == 0, f"Expected no signal (0), got {signal}"

    def test_insufficient_data(self):
        """Less than 30 bars should return 0."""
        df = _deterministic_ohlc(np.full(20, 1.1000))
        signal = strategy_b_bollinger_bands_stochastic(df)
        assert signal == 0

    def test_empty_dataframe(self):
        """Empty DataFrame should be handled gracefully."""
        signal = strategy_b_bollinger_bands_stochastic(pd.DataFrame())
        assert signal == 0


# ======================================================================
# Strategy C — Heikin Ashi + ATR
# ======================================================================

class TestStrategyC:
    def test_buy_signal(self, strat_c_buy):
        """Should return 1 (BUY) for 3 green HA candles + ATR expansion."""
        signal = strategy_c_heikin_ashi_atr(strat_c_buy)
        assert signal == 1, f"Expected BUY (1), got {signal}"

    def test_sell_signal(self, strat_c_sell):
        """Should return -1 (SELL) for 3 red HA candles + ATR expansion."""
        signal = strategy_c_heikin_ashi_atr(strat_c_sell)
        assert signal == -1, f"Expected SELL (-1), got {signal}"

    def test_no_signal_flat(self, flat_m5):
        """Flat data should NOT produce a signal."""
        signal = strategy_c_heikin_ashi_atr(flat_m5)
        assert signal == 0, f"Expected no signal (0), got {signal}"

    def test_insufficient_data(self):
        """Less than 70 bars should return 0."""
        df = _deterministic_ohlc(np.full(50, 1.1000))
        signal = strategy_c_heikin_ashi_atr(df)
        assert signal == 0

    def test_empty_dataframe(self):
        """Empty DataFrame should be handled gracefully."""
        signal = strategy_c_heikin_ashi_atr(pd.DataFrame())
        assert signal == 0


# ======================================================================
# Strategy D — Fair Value Gap / SMC
# ======================================================================

class TestStrategyD:
    def test_buy_signal(self, strat_d_buy):
        """Should return 1 (BUY) for Bullish FVG with trend confirmation."""
        signal = strategy_d_fvg_smc(strat_d_buy)
        assert signal == 1, f"Expected BUY (1), got {signal}"

    def test_sell_signal(self, strat_d_sell):
        """Should return -1 (SELL) for Bearish FVG with trend confirmation."""
        signal = strategy_d_fvg_smc(strat_d_sell)
        assert signal == -1, f"Expected SELL (-1), got {signal}"

    def test_no_signal_flat(self, flat_m5):
        """Flat data should NOT produce a signal."""
        signal = strategy_d_fvg_smc(flat_m5)
        assert signal == 0, f"Expected no signal (0), got {signal}"

    def test_insufficient_data(self):
        """Less than 250 bars should return 0."""
        df = _deterministic_ohlc(np.full(100, 1.1000))
        signal = strategy_d_fvg_smc(df)
        assert signal == 0

    def test_empty_dataframe(self):
        """Empty DataFrame should be handled gracefully."""
        signal = strategy_d_fvg_smc(pd.DataFrame())
        assert signal == 0


# ======================================================================
# Strategy E — HMA + RSI-2
# ======================================================================

class TestStrategyE:
    def test_buy_signal(self, strat_e_buy):
        """Should return 1 (BUY) when close > HMA55 and RSI(2) < 10."""
        signal = strategy_e_hma_rsi(strat_e_buy)
        assert signal == 1, f"Expected BUY (1), got {signal}"

    def test_sell_signal(self, strat_e_sell):
        """Should return -1 (SELL) when close < HMA55 and RSI(2) > 90."""
        signal = strategy_e_hma_rsi(strat_e_sell)
        assert signal == -1, f"Expected SELL (-1), got {signal}"

    def test_no_signal_flat(self, flat_m5):
        """Flat data should NOT produce a signal."""
        signal = strategy_e_hma_rsi(flat_m5)
        assert signal == 0, f"Expected no signal (0), got {signal}"

    def test_insufficient_data(self):
        """Less than 70 bars should return 0."""
        df = _deterministic_ohlc(np.full(50, 1.1000))
        signal = strategy_e_hma_rsi(df)
        assert signal == 0

    def test_empty_dataframe(self):
        """Empty DataFrame should be handled gracefully."""
        signal = strategy_e_hma_rsi(pd.DataFrame())
        assert signal == 0
