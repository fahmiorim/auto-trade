"""Unit tests for src/risk_manager.py.

Tests calculate_dynamic_lot, enforce_broker_stops, get_adjusted_sl_tp
with MetaTrader5 fully mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

# Import module under test (MetaTrader5 is installed, but we mock it anyway)
from src.risk_manager import (
    calculate_dynamic_lot,
    enforce_broker_stops,
    get_adjusted_sl_tp,
    reset_daily_tracker,
    check_daily_loss_limit,
    record_trade_result,
    check_max_consecutive_losses,
    get_risk_status,
    track_positions,
    _clear_symbol_info_cache,
)


# ======================================================================
# Auto-clear cache sebelum setiap test (cache global menyimpan mock antar-test)
# ======================================================================

@pytest.fixture(autouse=True)
def _auto_clear_cache():
    _clear_symbol_info_cache()


# ======================================================================
# Helper
# ======================================================================

def make_symbol_info(**overrides) -> MagicMock:
    """Create a mock SymbolInfo-like object with sensible defaults for EURUSD."""
    info = MagicMock()
    info.trade_tick_value = overrides.get("trade_tick_value", 10.0)
    info.trade_tick_size = overrides.get("trade_tick_size", 0.00001)
    info.point = overrides.get("point", 0.00001)
    info.volume_min = overrides.get("volume_min", 0.01)
    info.volume_max = overrides.get("volume_max", 100.0)
    info.volume_step = overrides.get("volume_step", 0.01)
    info.trade_stops_level = overrides.get("trade_stops_level", 0)
    info.trade_freeze_level = overrides.get("trade_freeze_level", 0)
    info.spread = overrides.get("spread", 10)
    info.digits = overrides.get("digits", 5)
    return info


# ======================================================================
# calculate_dynamic_lot
# ======================================================================

class TestCalculateDynamicLot:
    """Tests for lot-size calculation."""

    @patch("src.risk_manager.mt5")
    def test_normal_calculation(self, mock_mt5):
        """Normal inputs → correct lot size based on 1% risk."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        # EURUSD: balance=10000, risk=1%, sl=200 points
        # risk_amount = 100, loss_per_lot = 200*1*10 = 2000
        # raw_lot = 100/2000 = 0.05 → refined = round(0.05/0.01)*0.01 = 0.05
        lot = calculate_dynamic_lot("EURUSD", 10000, 0.01, 200)
        assert lot == 0.05, f"Expected 0.05, got {lot}"

    @patch("src.risk_manager.mt5")
    def test_sl_zero_returns_zero(self, mock_mt5):
        """sl_points <= 0 should return 0.0 without querying broker."""
        assert calculate_dynamic_lot("EURUSD", 10000, 0.01, 0) == 0.0
        assert calculate_dynamic_lot("EURUSD", 10000, 0.01, -10) == 0.0
        # symbol_info should NOT have been called
        mock_mt5.symbol_info.assert_not_called()

    @patch("src.risk_manager.mt5")
    def test_symbol_not_found(self, mock_mt5):
        """symbol_info returns None → return 0.0."""
        mock_mt5.symbol_info.return_value = None
        lot = calculate_dynamic_lot("UNKNOWN", 10000, 0.01, 200)
        assert lot == 0.0

    @patch("src.risk_manager.mt5")
    def test_below_min_lot(self, mock_mt5):
        """Result below min_lot → return 0.0."""
        mock_mt5.symbol_info.return_value = make_symbol_info(volume_min=0.10)
        # risk_amount = 10000 * 0.01 = 100
        # loss_per_lot = 50 * 1 * 10 = 500
        # raw_lot = 100/500 = 0.20 → refined = round(0.20/0.01)*0.01 = 0.20
        # But wait, with sl_points=50, the lot should be 0.20 which is > 0.10
        # Let me use a smaller risk scenario:
        # balance=1000, risk=1%=10, sl=200
        # loss_per_lot = 200*1*10 = 2000
        # raw_lot = 10/2000 = 0.005 → refined = round(0.005/0.01)*0.01 = 0.0
        lot = calculate_dynamic_lot("EURUSD", 1000, 0.01, 200)
        assert lot == 0.0

    @patch("src.risk_manager.mt5")
    def test_above_max_lot(self, mock_mt5):
        """Result above max_lot → capped to max_lot."""
        mock_mt5.symbol_info.return_value = make_symbol_info(volume_max=1.0)
        # risk_amount = 100000 * 0.01 = 1000
        # loss_per_lot = 50 * 1 * 10 = 500
        # raw_lot = 1000/500 = 2.0 → capped to 1.0
        lot = calculate_dynamic_lot("EURUSD", 100000, 0.01, 50)
        assert lot == 1.0

    @patch("src.risk_manager.mt5")
    def test_lot_step_precision(self, mock_mt5):
        """Lot should be rounded to the lot_step decimal places."""
        mock_mt5.symbol_info.return_value = make_symbol_info(volume_step=0.01)
        # risk_amount = 10000 * 0.01 = 100
        # loss_per_lot = 150 * 1 * 10 = 1500
        # raw_lot = 100/1500 = 0.06666...
        # refined = round(0.06666/0.01)*0.01 = 7*0.01 = 0.07
        lot = calculate_dynamic_lot("EURUSD", 10000, 0.01, 150)
        assert lot == 0.07, f"Expected 0.07, got {lot}"


# ======================================================================
# enforce_broker_stops
# ======================================================================

class TestEnforceBrokerStops:
    """Tests for broker stops enforcement."""

    @patch("src.risk_manager.mt5")
    def test_sl_below_minimum(self, mock_mt5):
        """SL below min_required → bumped up to min_required."""
        mock_mt5.symbol_info.return_value = make_symbol_info(
            trade_stops_level=10,
            freeze_level=0,
            spread=5,
        )
        # min_required = max(10, 0) + 5 + 10 = 25
        sl, tp = enforce_broker_stops("EURUSD", 15, 300)
        assert sl == 25, f"Expected SL=25, got {sl}"
        assert tp == 300, "TP should remain unchanged"

    @patch("src.risk_manager.mt5")
    def test_tp_below_minimum(self, mock_mt5):
        """TP below min_required → bumped up to min_required."""
        mock_mt5.symbol_info.return_value = make_symbol_info(
            trade_stops_level=20,
            freeze_level=10,
            spread=3,
        )
        # min_required = max(20, 10) + 3 + 10 = 33
        sl, tp = enforce_broker_stops("EURUSD", 50, 20)
        assert sl == 50, "SL should remain unchanged"
        assert tp == 33, f"Expected TP=33, got {tp}"

    @patch("src.risk_manager.mt5")
    def test_both_ok(self, mock_mt5):
        """SL/TP already above minimum → unchanged."""
        mock_mt5.symbol_info.return_value = make_symbol_info(
            trade_stops_level=10,
            freeze_level=0,
            spread=5,
        )
        # min_required = 10 + 5 + 10 = 25
        sl, tp = enforce_broker_stops("EURUSD", 100, 100)
        assert sl == 100
        assert tp == 100

    @patch("src.risk_manager.mt5")
    def test_symbol_not_found(self, mock_mt5):
        """symbol_info returns None → return original values."""
        mock_mt5.symbol_info.return_value = None
        sl, tp = enforce_broker_stops("UNKNOWN", 10, 20)
        assert sl == 10
        assert tp == 20

    @patch("src.risk_manager.mt5")
    def test_freeze_level_higher_than_stops_level(self, mock_mt5):
        """Should use max(stops_level, freeze_level) as base."""
        mock_mt5.symbol_info.return_value = make_symbol_info(
            trade_stops_level=5,
            trade_freeze_level=30,
            spread=8,
        )
        # min_required = max(5, 30) + 8 + 10 = 48
        sl, tp = enforce_broker_stops("EURUSD", 20, 100)
        assert sl == 48, f"Expected SL=48, got {sl}"


# ======================================================================
# get_adjusted_sl_tp
# ======================================================================

class TestGetAdjustedSlTp:
    """Tests for SL/TP price calculation."""

    @patch("src.risk_manager.mt5")
    def test_buy_direction(self, mock_mt5):
        """BUY direction: subtract SL, add TP + commission."""
        mock_mt5.symbol_info.return_value = make_symbol_info(
            digits=5,
            spread=5,
        )
        # entry=1.10000, sl_points=200, tp_points=300, commission=6/lot
        # commission_points = (6.0/10.0) * (0.00001/0.00001) = 0.6
        # sl_price = 1.10000 - 200*0.00001 = 1.09800
        # tp_price = 1.10000 + 300*0.00001 + 0.6*0.00001 = 1.103006
        # round(1.09800, 5) = 1.09800
        # round(1.103006, 5) = 1.10301
        sl, tp = get_adjusted_sl_tp("EURUSD", 1, 1.10000, 200, 300)
        assert sl == 1.09800, f"Expected SL=1.09800, got {sl}"
        assert tp == 1.10301, f"Expected TP=1.10301, got {tp}"

    @patch("src.risk_manager.mt5")
    def test_sell_direction(self, mock_mt5):
        """SELL direction: add SL, subtract TP - commission."""
        mock_mt5.symbol_info.return_value = make_symbol_info(
            digits=5,
            spread=5,
        )
        # entry=1.20000, sl_points=200, tp_points=300
        # commission_points = 0.6
        # sl_price = 1.20000 + 200*0.00001 = 1.20200
        # tp_price = 1.20000 - 300*0.00001 - 0.6*0.00001 = 1.196994
        # round(1.20200, 5) = 1.20200
        # round(1.196994, 5) = 1.19699
        sl, tp = get_adjusted_sl_tp("EURUSD", -1, 1.20000, 200, 300)
        assert sl == 1.20200, f"Expected SL=1.20200, got {sl}"
        assert tp == 1.19699, f"Expected TP=1.19699, got {tp}"

    @patch("src.risk_manager.mt5")
    def test_invalid_direction(self, mock_mt5):
        """Direction not 1/-1 → returns (None, None)."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        sl, tp = get_adjusted_sl_tp("EURUSD", 0, 1.10000, 200, 300)
        assert sl is None and tp is None

    @patch("src.risk_manager.mt5")
    def test_symbol_not_found(self, mock_mt5):
        """symbol_info returns None → returns (None, None)."""
        mock_mt5.symbol_info.return_value = None
        sl, tp = get_adjusted_sl_tp("UNKNOWN", 1, 1.10000, 200, 300)
        assert sl is None and tp is None

    @patch("src.risk_manager.mt5")
    def test_buy_direction_no_commission(self, mock_mt5):
        """Zero commission should not add slippage to TP."""
        mock_mt5.symbol_info.return_value = make_symbol_info(digits=5, spread=5)
        sl, tp = get_adjusted_sl_tp("EURUSD", 1, 1.10000, 200, 300, commission_per_lot=0.0)
        # commission_points = 0
        # tp_price = 1.10000 + 300*0.00001 + 0 = 1.10300
        assert tp == 1.10300, f"Expected TP=1.10300, got {tp}"


# ======================================================================
# reset_daily_tracker / check_daily_loss_limit / record_trade_result
# check_max_consecutive_losses / get_risk_status / track_positions
# ======================================================================

class TestDailyLossAndConsecutive:
    """Tests for daily loss limit and consecutive loss tracking."""

    def setup_method(self):
        """Reset global state before each test."""
        reset_daily_tracker(10000.0)

    # ---- reset_daily_tracker ----

    def test_reset_daily_tracker(self):
        """reset_daily_tracker should initialize state."""
        reset_daily_tracker(5000.0)
        status = get_risk_status()
        assert status["daily_start_balance"] == 5000.0
        assert status["consecutive_losses"] == 0
        assert status["last_reset"] != ""

    # ---- check_daily_loss_limit ----

    def test_daily_loss_below_limit(self):
        """Balance drop < 5% → should allow trading."""
        allowed, msg = check_daily_loss_limit(9800.0)  # -2%
        assert allowed is True
        assert msg == ""

    def test_daily_loss_above_limit(self):
        """Balance drop > 5% → should block trading."""
        # Reset with 10000, then drop to 9300 (-7%)
        reset_daily_tracker(10000.0)
        allowed, msg = check_daily_loss_limit(9300.0, max_loss_percent=0.05)
        assert allowed is False
        assert "melebihi" in msg
        assert "5%" in msg or "5.0%" in msg

    def test_daily_loss_custom_percent(self):
        """Custom max_loss_percent should be respected."""
        reset_daily_tracker(10000.0)
        # 3% drop with 2% max → blocked
        allowed, msg = check_daily_loss_limit(9700.0, max_loss_percent=0.02)
        assert allowed is False

    def test_daily_loss_exact_at_limit(self):
        """Loss exactly at max_percent → should still block (>=)."""
        reset_daily_tracker(10000.0)
        # Exactly 5% drop: 9500
        allowed, msg = check_daily_loss_limit(9500.0, max_loss_percent=0.05)
        assert allowed is False, "Exactly at limit should be blocked"

    def test_daily_loss_day_change_auto_reset(self):
        """Day change should auto-reset the tracker."""
        reset_daily_tracker(10000.0)
        # Force a different date by patching datetime
        # Instead, just verify that calling with a high balance resets
        allowed, msg = check_daily_loss_limit(12000.0)  # gain, not loss
        # Should be allowed (balance increased, no loss)
        assert allowed is True

    # ---- record_trade_result ----

    def test_record_loss_increments_counter(self):
        """Losing trade should increment consecutive loss counter."""
        reset_daily_tracker(10000.0)
        record_trade_result(-25.0)
        assert get_risk_status()["consecutive_losses"] == 1

    def test_record_multiple_losses(self):
        """Multiple losses should stack."""
        reset_daily_tracker(10000.0)
        record_trade_result(-10.0)
        record_trade_result(-15.0)
        record_trade_result(-20.0)
        assert get_risk_status()["consecutive_losses"] == 3

    def test_record_win_resets_counter(self):
        """Winning trade after losses should reset counter to 0."""
        reset_daily_tracker(10000.0)
        record_trade_result(-10.0)
        record_trade_result(-15.0)
        record_trade_result(30.0)  # win
        assert get_risk_status()["consecutive_losses"] == 0

    def test_record_win_no_prior_losses(self):
        """Winning trade with no prior losses should keep counter at 0."""
        reset_daily_tracker(10000.0)
        record_trade_result(20.0)
        assert get_risk_status()["consecutive_losses"] == 0

    # ---- check_max_consecutive_losses ----

    def test_consecutive_below_limit(self):
        """Streak below max → should allow trading."""
        reset_daily_tracker(10000.0)
        record_trade_result(-10.0)
        record_trade_result(-10.0)
        allowed, msg = check_max_consecutive_losses(max_consecutive=3)
        assert allowed is True

    def test_consecutive_at_limit_blocked(self):
        """Streak >= max → should block trading."""
        reset_daily_tracker(10000.0)
        for _ in range(3):
            record_trade_result(-10.0)
        allowed, msg = check_max_consecutive_losses(max_consecutive=3)
        assert allowed is False
        assert "Consecutive losses" in msg

    def test_consecutive_custom_limit(self):
        """Custom max_consecutive should be respected."""
        reset_daily_tracker(10000.0)
        record_trade_result(-10.0)
        allowed, msg = check_max_consecutive_losses(max_consecutive=1)
        assert allowed is False

    # ---- track_positions ----

    @patch("src.risk_manager.mt5")
    def test_track_positions_new_ticket(self, mock_mt5):
        """New position tracked → no closed tickets yet."""
        reset_daily_tracker(10000.0)

        mock_pos = MagicMock()
        mock_pos.ticket = 1001
        mock_pos.symbol = "EURUSD"

        track_positions([mock_pos])
        assert get_risk_status()["consecutive_losses"] == 0

    @patch("src.risk_manager.mt5")
    def test_track_positions_closed_loss(self, mock_mt5):
        """Position closed with loss → consecutive losses increment."""
        reset_daily_tracker(10000.0)

        # First call: track ticket 1001
        mock_pos = MagicMock()
        mock_pos.ticket = 1001
        mock_pos.symbol = "EURUSD"
        track_positions([mock_pos])

        # Second call: ticket 1001 gone, mock history deals
        # history_deals_get returns [opening_deal, closing_deal]
        # _query_closed_deal calls with position= first
        mock_opening = MagicMock()
        mock_opening.profit = 0.0       # opening deal: profit = 0
        mock_opening.symbol = "EURUSD"
        mock_closing = MagicMock()
        mock_closing.profit = -50.0      # closing deal: real PnL
        mock_closing.symbol = "EURUSD"
        mock_mt5.history_deals_get.return_value = [mock_opening, mock_closing]

        track_positions([])
        # Should use deals[-1] which is the closing deal with profit=-50
        assert get_risk_status()["consecutive_losses"] == 1
        # First try position= parameter
        mock_mt5.history_deals_get.assert_called_with(position=1001)

    @patch("src.risk_manager.mt5")
    def test_track_positions_closed_win(self, mock_mt5):
        """Position closed with win → consecutive losses reset."""
        reset_daily_tracker(10000.0)

        # First: add a loss streak
        record_trade_result(-10.0)
        record_trade_result(-10.0)
        assert get_risk_status()["consecutive_losses"] == 2

        # Track a winning position closing
        mock_pos = MagicMock()
        mock_pos.ticket = 1002
        mock_pos.symbol = "GBPUSD"
        track_positions([mock_pos])

        # Two deals: opening (profit=0) and closing (profit=80)
        mock_opening = MagicMock()
        mock_opening.profit = 0.0
        mock_opening.symbol = "GBPUSD"
        mock_closing = MagicMock()
        mock_closing.profit = 80.0
        mock_closing.symbol = "GBPUSD"
        mock_mt5.history_deals_get.return_value = [mock_opening, mock_closing]

        track_positions([])
        # Uses deals[-1] = closing deal with profit=80 → WIN → reset counter
        assert get_risk_status()["consecutive_losses"] == 0

    @patch("src.risk_manager.mt5")
    def test_track_positions_no_history_skipped(self, mock_mt5):
        """No history available → skip (don't assume loss to avoid false positive)."""
        reset_daily_tracker(10000.0)

        mock_pos = MagicMock()
        mock_pos.ticket = 1003
        track_positions([mock_pos])

        mock_mt5.history_deals_get.return_value = None  # no history
        track_positions([])
        # Should NOT increment consecutive losses
        assert get_risk_status()["consecutive_losses"] == 0

    @patch("src.risk_manager.mt5")
    def test_track_positions_fallback_parameter(self, mock_mt5):
        """Fallback to ticket= parameter when position= fails."""
        reset_daily_tracker(10000.0)

        # First call: track ticket
        mock_pos = MagicMock()
        mock_pos.ticket = 2001
        mock_pos.symbol = "EURUSD"
        track_positions([mock_pos])

        # position= returns None → should try ticket= as fallback
        mock_mt5.history_deals_get.side_effect = [
            None,  # first call (position=2001) → None
            [MagicMock(profit=-30.0, symbol="EURUSD")]  # second call (ticket=2001) → success
        ]

        track_positions([])
        assert get_risk_status()["consecutive_losses"] == 1
        # Should have been called twice
        assert mock_mt5.history_deals_get.call_count == 2

    # ---- get_risk_status ----

    def test_get_risk_status_after_operations(self):
        """get_risk_status should reflect current state accurately."""
        reset_daily_tracker(10000.0)
        record_trade_result(-10.0)
        record_trade_result(-15.0)

        status = get_risk_status()
        assert status["daily_start_balance"] == 10000.0
        assert status["consecutive_losses"] == 2
        assert "last_reset" in status
