"""Unit tests for src/executor.py.

Tests: get_filling_mode, open_market_order, close_position_by_ticket,
       get_active_positions, modify_position_sl.
MetaTrader5 is fully mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.executor import (
    get_filling_mode,
    open_market_order,
    close_position_by_ticket,
    get_active_positions,
    modify_position_sl,
)
from src import config


# ======================================================================
# Helpers
# ======================================================================

# Known MT5 constant values
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_INVALID_FILLING = 10030


def make_symbol_info(filling_mode: int = 1, **overrides) -> MagicMock:
    """Create a mock SymbolInfo object."""
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
    info.filling_mode = filling_mode
    return info


def make_tick(ask: float = 1.10010, bid: float = 1.10000) -> MagicMock:
    """Create a mock Tick object."""
    tick = MagicMock()
    tick.ask = ask
    tick.bid = bid
    return tick


def make_position(
    ticket: int = 1001,
    symbol: str = "EURUSD",
    volume: float = 0.1,
    pos_type: int = POSITION_TYPE_BUY,
    sl: float = 1.09500,
    tp: float = 1.10500,
    magic: int = None,
) -> MagicMock:
    """Create a mock Position object."""
    pos = MagicMock()
    pos.ticket = ticket
    pos.symbol = symbol
    pos.volume = volume
    pos.type = pos_type
    pos.sl = sl
    pos.tp = tp
    pos.magic = magic or config.MAGIC_NUMBER
    return pos


def make_order_result(retcode: int = TRADE_RETCODE_DONE, order: int = 1001, comment: str = "") -> MagicMock:
    """Create a mock OrderSendResult object."""
    result = MagicMock()
    result.retcode = retcode
    result.order = order
    result.comment = comment
    return result


# ======================================================================
# get_filling_mode
# ======================================================================

class TestGetFillingMode:
    """Tests for auto-detection of filling mode."""

    @patch("src.executor.mt5")
    def test_fok_mode(self, mock_mt5):
        """When FOK bit is set, return ORDER_FILLING_FOK."""
        # SYMBOL_FILLING_FOK = 1
        mock_mt5.symbol_info.return_value = make_symbol_info(filling_mode=1)
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        mode = get_filling_mode("EURUSD")
        assert mode == 0, f"Expected FOK (0), got {mode}"

    @patch("src.executor.mt5")
    def test_ioc_mode(self, mock_mt5):
        """When IOC bit is set (FOK not), return ORDER_FILLING_IOC."""
        # SYMBOL_FILLING_IOC = 2
        mock_mt5.symbol_info.return_value = make_symbol_info(filling_mode=2)
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        mode = get_filling_mode("EURUSD")
        assert mode == 1, f"Expected IOC (1), got {mode}"

    @patch("src.executor.mt5")
    def test_return_mode(self, mock_mt5):
        """When neither FOK nor IOC, return ORDER_FILLING_RETURN."""
        mock_mt5.symbol_info.return_value = make_symbol_info(filling_mode=0)
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        mode = get_filling_mode("EURUSD")
        assert mode == 2, f"Expected RETURN (2), got {mode}"

    @patch("src.executor.mt5")
    def test_symbol_not_found(self, mock_mt5):
        """symbol_info returns None → default ORDER_FILLING_RETURN."""
        mock_mt5.symbol_info.return_value = None
        mock_mt5.ORDER_FILLING_RETURN = 2

        mode = get_filling_mode("UNKNOWN")
        assert mode == 2, f"Expected RETURN (2), got {mode}"


# ======================================================================
# open_market_order
# ======================================================================

class TestOpenMarketOrder:
    """Tests for market order execution."""

    @patch("src.executor.mt5")
    def test_buy_success(self, mock_mt5):
        """Successful BUY market order."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick(ask=1.10010, bid=1.10000)
        mock_mt5.order_send.return_value = make_order_result(
            retcode=TRADE_RETCODE_DONE, order=1001
        )
        # Set up constants
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2
        mock_mt5.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE

        result = open_market_order(
            "EURUSD", 1, 0.1, 1.09500, 1.10500, comment="Test BUY"
        )
        assert result is True, "BUY order should succeed"

        # Verify the request was formed correctly
        request = mock_mt5.order_send.call_args[0][0]
        assert request["action"] == 1  # TRADE_ACTION_DEAL
        assert request["symbol"] == "EURUSD"
        assert request["volume"] == 0.1
        assert request["type"] == ORDER_TYPE_BUY
        assert request["price"] == 1.10010  # ask price for BUY
        assert request["sl"] == 1.09500
        assert request["tp"] == 1.10500

    @patch("src.executor.mt5")
    def test_sell_success(self, mock_mt5):
        """Successful SELL market order."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick(ask=1.10010, bid=1.10000)
        mock_mt5.order_send.return_value = make_order_result(
            retcode=TRADE_RETCODE_DONE, order=1002
        )
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2
        mock_mt5.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE

        result = open_market_order(
            "EURUSD", -1, 0.2, 1.20000, 1.19000, comment="Test SELL"
        )
        assert result is True, "SELL order should succeed"

        # Verify: uses bid price for SELL
        request = mock_mt5.order_send.call_args[0][0]
        assert request["type"] == ORDER_TYPE_SELL
        assert request["price"] == 1.10000  # bid price for SELL
        assert request["volume"] == 0.2

    @patch("src.executor.mt5")
    def test_no_symbol_info(self, mock_mt5):
        """symbol_info returns None → return False."""
        mock_mt5.symbol_info.return_value = None
        result = open_market_order("EURUSD", 1, 0.1, 1.09500, 1.10500)
        assert result is False

    @patch("src.executor.mt5")
    def test_invalid_direction(self, mock_mt5):
        """Invalid direction (0) → return False."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        result = open_market_order("EURUSD", 0, 0.1, 1.09500, 1.10500)
        assert result is False

    @patch("src.executor.mt5")
    def test_order_failure(self, mock_mt5):
        """Order fails with non-DONE retcode → return False."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick()
        mock_mt5.order_send.return_value = make_order_result(
            retcode=10014, comment="Market closed"
        )
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        result = open_market_order("EURUSD", 1, 0.1, 1.09500, 1.10500)
        assert result is False

    @patch("src.executor.mt5")
    def test_auto_fallback_filling_mode(self, mock_mt5):
        """Retcode 10030 triggers fallback to alternate filling modes."""
        mock_mt5.symbol_info.return_value = make_symbol_info(filling_mode=1)
        mock_mt5.symbol_info_tick.return_value = make_tick()

        # First call returns 10030, fallback call succeeds
        def order_send_side_effect(request):
            if request["type_filling"] == 0:  # FOK failed
                return make_order_result(retcode=TRADE_RETCODE_INVALID_FILLING)
            elif request["type_filling"] == 1:  # IOC succeeded
                return make_order_result(retcode=TRADE_RETCODE_DONE, order=1003)
            return make_order_result(retcode=TRADE_RETCODE_DONE)

        mock_mt5.order_send.side_effect = order_send_side_effect
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2
        mock_mt5.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE

        result = open_market_order("EURUSD", 1, 0.1, 1.09500, 1.10500)
        assert result is True, "Should succeed after fallback to IOC"

        # Should have called order_send at least twice (FOK failed, IOC succeeded)
        assert mock_mt5.order_send.call_count >= 2

    @patch("src.executor.mt5")
    def test_auto_fallback_all_fail(self, mock_mt5):
        """All filling modes fail → return False."""
        mock_mt5.symbol_info.return_value = make_symbol_info(filling_mode=1)
        mock_mt5.symbol_info_tick.return_value = make_tick()
        mock_mt5.order_send.return_value = make_order_result(
            retcode=TRADE_RETCODE_INVALID_FILLING
        )
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        result = open_market_order("EURUSD", 1, 0.1, 1.09500, 1.10500)
        assert result is False

    @patch("src.executor.mt5")
    def test_order_send_returns_none(self, mock_mt5):
        """order_send returns None → return False."""
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick()
        mock_mt5.order_send.return_value = None
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        result = open_market_order("EURUSD", 1, 0.1, 1.09500, 1.10500)
        assert result is False


# ======================================================================
# close_position_by_ticket
# ======================================================================

class TestClosePositionByTicket:
    """Tests for position closing."""

    @patch("src.executor.mt5")
    def test_close_buy_position(self, mock_mt5):
        """Close a long (BUY) position."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1001, symbol="EURUSD", volume=0.1, pos_type=POSITION_TYPE_BUY)
        ]
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick(ask=1.10010, bid=1.10000)
        mock_mt5.order_send.return_value = make_order_result(
            retcode=TRADE_RETCODE_DONE, order=2001
        )
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.POSITION_TYPE_BUY = POSITION_TYPE_BUY
        mock_mt5.POSITION_TYPE_SELL = POSITION_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2
        mock_mt5.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE

        result = close_position_by_ticket(1001)
        assert result is True

        # Verify request: closing BUY → issues SELL using bid price
        request = mock_mt5.order_send.call_args[0][0]
        assert request["type"] == ORDER_TYPE_SELL
        assert request["price"] == 1.10000  # bid for closing BUY
        assert request["position"] == 1001

    @patch("src.executor.mt5")
    def test_close_sell_position(self, mock_mt5):
        """Close a short (SELL) position."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1002, symbol="EURUSD", volume=0.2, pos_type=POSITION_TYPE_SELL)
        ]
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick(ask=1.10010, bid=1.10000)
        mock_mt5.order_send.return_value = make_order_result(
            retcode=TRADE_RETCODE_DONE, order=2002
        )
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.POSITION_TYPE_BUY = POSITION_TYPE_BUY
        mock_mt5.POSITION_TYPE_SELL = POSITION_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2
        mock_mt5.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE

        result = close_position_by_ticket(1002)
        assert result is True

        # Verify request: closing SELL → issues BUY using ask price
        request = mock_mt5.order_send.call_args[0][0]
        assert request["type"] == ORDER_TYPE_BUY
        assert request["price"] == 1.10010  # ask for closing SELL
        assert request["position"] == 1002

    @patch("src.executor.mt5")
    def test_position_not_found(self, mock_mt5):
        """No position with the given ticket → return False."""
        mock_mt5.positions_get.return_value = None
        result = close_position_by_ticket(9999)
        assert result is False

    @patch("src.executor.mt5")
    def test_close_order_failure(self, mock_mt5):
        """Order send fails → return False."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1001, symbol="EURUSD", volume=0.1)
        ]
        mock_mt5.symbol_info.return_value = make_symbol_info()
        mock_mt5.symbol_info_tick.return_value = make_tick()
        mock_mt5.order_send.return_value = make_order_result(
            retcode=10014, comment="Failed"
        )
        mock_mt5.ORDER_TYPE_BUY = ORDER_TYPE_BUY
        mock_mt5.ORDER_TYPE_SELL = ORDER_TYPE_SELL
        mock_mt5.POSITION_TYPE_BUY = POSITION_TYPE_BUY
        mock_mt5.POSITION_TYPE_SELL = POSITION_TYPE_SELL
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 0
        mock_mt5.SYMBOL_FILLING_FOK = 1
        mock_mt5.SYMBOL_FILLING_IOC = 2
        mock_mt5.ORDER_FILLING_FOK = 0
        mock_mt5.ORDER_FILLING_IOC = 1
        mock_mt5.ORDER_FILLING_RETURN = 2

        result = close_position_by_ticket(1001)
        assert result is False


# ======================================================================
# get_active_positions
# ======================================================================

class TestGetActivePositions:
    """Tests for active position retrieval."""

    @patch("src.executor.mt5")
    def test_with_symbol_filter(self, mock_mt5):
        """Filter positions by symbol and magic number."""
        all_positions = [
            make_position(ticket=1, symbol="EURUSD", magic=config.MAGIC_NUMBER),
            make_position(ticket=2, symbol="GBPUSD", magic=config.MAGIC_NUMBER),
            make_position(ticket=3, symbol="EURUSD", magic=9999),  # different magic
        ]

        # Mock positions_get to filter by symbol (like real MT5 would)
        def positions_get_side_effect(symbol=None):
            return [p for p in all_positions if p.symbol == symbol]

        mock_mt5.positions_get.side_effect = positions_get_side_effect

        positions = get_active_positions(symbol="EURUSD")
        assert len(positions) == 1, f"Expected 1 EURUSD position, got {len(positions)}"
        assert positions[0].ticket == 1
        # Should have called positions_get with symbol="EURUSD"
        mock_mt5.positions_get.assert_called_with(symbol="EURUSD")

    @patch("src.executor.mt5")
    def test_all_positions(self, mock_mt5):
        """No symbol filter → return all positions with matching magic."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1, symbol="EURUSD", magic=config.MAGIC_NUMBER),
            make_position(ticket=2, symbol="GBPUSD", magic=config.MAGIC_NUMBER),
            make_position(ticket=3, symbol="USDJPY", magic=9999),  # different magic
        ]

        positions = get_active_positions()
        assert len(positions) == 2, f"Expected 2 robot positions, got {len(positions)}"

    @patch("src.executor.mt5")
    def test_no_positions(self, mock_mt5):
        """positions_get returns None → empty list."""
        mock_mt5.positions_get.return_value = None
        positions = get_active_positions()
        assert positions == []

    @patch("src.executor.mt5")
    def test_no_robot_positions(self, mock_mt5):
        """No positions with matching magic → empty list."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1, symbol="EURUSD", magic=9999),
        ]
        positions = get_active_positions()
        assert positions == []


# ======================================================================
# modify_position_sl
# ======================================================================

class TestModifyPositionSl:
    """Tests for Stop Loss modification."""

    @patch("src.executor.mt5")
    def test_normal_modify(self, mock_mt5):
        """Normal SL modification should succeed."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1001, symbol="EURUSD", sl=1.09500, tp=1.10500)
        ]
        mock_mt5.order_send.return_value = make_order_result(
            retcode=TRADE_RETCODE_DONE, order=3001
        )
        mock_mt5.TRADE_ACTION_SLTP = 5
        mock_mt5.TRADE_RETCODE_DONE = TRADE_RETCODE_DONE

        result = modify_position_sl(1001, 1.10000)
        assert result is True

        # Verify request
        request = mock_mt5.order_send.call_args[0][0]
        assert request["action"] == 5  # TRADE_ACTION_SLTP
        assert request["position"] == 1001
        assert request["sl"] == 1.10000
        assert request["tp"] == 1.10500  # original TP preserved

    @patch("src.executor.mt5")
    def test_sl_too_close_skipped(self, mock_mt5):
        """SL difference < 1e-5 → skip modification, return True."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1001, symbol="EURUSD", sl=1.10000)
        ]
        # new_sl is essentially same as current SL
        result = modify_position_sl(1001, 1.10000)
        assert result is True
        # order_send should NOT have been called
        mock_mt5.order_send.assert_not_called()

    @patch("src.executor.mt5")
    def test_position_not_found(self, mock_mt5):
        """Position not found → return False."""
        mock_mt5.positions_get.return_value = None
        result = modify_position_sl(9999, 1.10000)
        assert result is False

    @patch("src.executor.mt5")
    def test_order_send_failure(self, mock_mt5):
        """order_send returns failure → return False."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1001, symbol="EURUSD", sl=1.09500, tp=1.10500)
        ]
        mock_mt5.order_send.return_value = make_order_result(
            retcode=10014, comment="Failed"
        )
        mock_mt5.TRADE_ACTION_SLTP = 5

        result = modify_position_sl(1001, 1.10000)
        assert result is False

    @patch("src.executor.mt5")
    def test_order_send_returns_none(self, mock_mt5):
        """order_send returns None → return False."""
        mock_mt5.positions_get.return_value = [
            make_position(ticket=1001, symbol="EURUSD", sl=1.09500, tp=1.10500)
        ]
        mock_mt5.order_send.return_value = None
        mock_mt5.TRADE_ACTION_SLTP = 5

        result = modify_position_sl(1001, 1.10000)
        assert result is False
