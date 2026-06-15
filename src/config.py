"""
Konfigurasi Robot Trading Autopilot MT5.

Struktur dataclass untuk type safety. Semua konstanta didefinisikan di
dalam kelas ``Config``, lalu diekspor sebagai module-level aliases agar
kode lama tetap berfungsi (``config.SYMBOLS`` → ``config.cfg.SYMBOLS``).

Untuk kode baru, akses langsung via ``config.cfg`` untuk mendapat
autocomplete & type hints di IDE.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import MetaTrader5 as mt5
from src.results_db import get_all_session_configs, get_best_config


# ======================================================================
# DATACLASS KONFIGURASI
# ======================================================================

@dataclass
class Config:
    # ---- Instrumen & Timeframe ---------------------------------------
    SYMBOLS: List[str] = field(default_factory=lambda: [
        "EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD",
        "NZDUSD", "USDCHF", "EURJPY", "GBPJPY", "XAUUSD",
    ])
    TIMEFRAME_M1: int = mt5.TIMEFRAME_M1
    TIMEFRAME_M5: int = mt5.TIMEFRAME_M5

    # ---- Manajemen Risiko --------------------------------------------
    RISK_PERCENT: float = 0.01          # 1% risiko per transaksi
    MAGIC_NUMBER: int = 20260613        # ID unik order robot
    SLIPPAGE: int = 10                  # toleransi slippage (points)

    # ---- Indikator Teknikal ------------------------------------------
    EMA_FAST: int = 9
    EMA_MEDIUM: int = 21
    EMA_SLOW: int = 200
    STO_K: int = 5
    STO_D: int = 3
    STO_SLOWING: int = 3
    STO_OVERSOLD: int = 20
    STO_OVERBOUGHT: int = 80
    BB_PERIOD: int = 20
    BB_DEVIATION: float = 2.0
    ATR_PERIOD: int = 14
    ATR_MULTIPLIER_SL: float = 1.5
    ATR_MULTIPLIER_TP: float = 2.0
    HMA_PERIOD: int = 55
    RSI_PERIOD: int = 2

    # ---- Filter Berita -----------------------------------------------
    NEWS_BLOCK_BEFORE: int = 30         # menit sebelum berita
    NEWS_BLOCK_AFTER: int = 30          # menit sesudah berita
    ECONOMIC_CALENDAR_URL: str = (
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    )

    # ---- Operasional -------------------------------------------------
    ROLLOVER_HOURS: Dict[str, str] = field(default_factory=lambda: {
        "START": "03:45",
        "END": "05:15",
    })

    # ---- Sesi Trading (WIB) ------------------------------------------
    SESSION_HOURS_WIB: Dict[str, Dict[str, str]] = field(
        default_factory=lambda: {
            "ASIA":      {"START": "09:00", "END": "15:00"},
            "LONDON":    {"START": "15:00", "END": "20:00"},
            "LONDON_NY": {"START": "20:00", "END": "23:00"},
            "NEW_YORK":  {"START": "23:00", "END": "03:45"},
        }
    )

    # Sesi dalam UTC (WIB - 7 jam)
    SESSION_HOURS_UTC: Dict[str, Dict[str, int]] = field(
        default_factory=lambda: {
            "ASIA":      {"start": 2,  "end": 8},
            "LONDON":    {"start": 8,  "end": 13},
            "LONDON_NY": {"start": 13, "end": 16},
            "NEW_YORK":  {"start": 16, "end": 21},
        }
    )

    # Pair eligible per sesi
    SESSION_ELIGIBLE_PAIRS: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "ASIA":      ["USDJPY", "EURJPY", "GBPJPY", "AUDUSD", "NZDUSD"],
            "LONDON":    ["EURUSD", "GBPUSD", "USDCHF", "EURJPY", "GBPJPY", "USDCAD"],
            "LONDON_NY": ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD",
                         "USDCHF", "EURJPY", "GBPJPY"],
            "NEW_YORK":  ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "USDCHF", "AUDUSD"],
        }
    )

    # ---- Legacy ------------------------------------------------------
    TRADING_HOURS: Dict[str, str] = field(default_factory=lambda: {
        "START": "09:00",
        "END": "03:45",
    })


# ======================================================================
# INSTANCE GLOBAL
# ======================================================================

cfg: Config = Config()


# ======================================================================
# STATE FROM DATABASE (dibaca sekali saat modul di-load)
# ======================================================================

_session_configs = get_all_session_configs()
_fallback_config = get_best_config(session=None)


# ======================================================================
# FUNGSI DINAMIS (membaca state DB)
# ======================================================================

def get_session_strategy(symbol: str, session: str) -> Optional[str]:
    """Ambil strategi terbaik untuk *symbol* di *session* tertentu.

    Fallback ke best config dari semua sesi jika session belum di-tune.
    """
    cfg_data = _session_configs.get(session, {}).get(symbol)
    if cfg_data and cfg_data.get("source") == "db":
        return cfg_data.get("strategy")
    return _fallback_config.get(symbol, {}).get("strategy")


def get_session_sl_tp(symbol: str, session: str) -> Dict[str, int]:
    """Ambil pasangan SL/TP terbaik untuk *symbol* di *session* tertentu."""
    cfg_data = _session_configs.get(session, {}).get(symbol)
    if cfg_data and cfg_data.get("source") == "db":
        return {"sl": cfg_data.get("sl", 150), "tp": cfg_data.get("tp", 250)}
    return {
        "sl": _fallback_config.get(symbol, {}).get("sl", 150),
        "tp": _fallback_config.get(symbol, {}).get("tp", 250),
    }


# ======================================================================
# BACKWARD-COMPATIBLE ALIASES
# ======================================================================
# Agar kode lama seperti ``from src import config; config.SYMBOLS`` tetap
# berfungsi tanpa perubahan import.

SYMBOLS: List[str] = cfg.SYMBOLS
TIMEFRAME_M1: int = cfg.TIMEFRAME_M1
TIMEFRAME_M5: int = cfg.TIMEFRAME_M5
RISK_PERCENT: float = cfg.RISK_PERCENT
MAGIC_NUMBER: int = cfg.MAGIC_NUMBER
SLIPPAGE: int = cfg.SLIPPAGE
EMA_FAST: int = cfg.EMA_FAST
EMA_MEDIUM: int = cfg.EMA_MEDIUM
EMA_SLOW: int = cfg.EMA_SLOW
STO_K: int = cfg.STO_K
STO_D: int = cfg.STO_D
STO_SLOWING: int = cfg.STO_SLOWING
STO_OVERSOLD: int = cfg.STO_OVERSOLD
STO_OVERBOUGHT: int = cfg.STO_OVERBOUGHT
BB_PERIOD: int = cfg.BB_PERIOD
BB_DEVIATION: float = cfg.BB_DEVIATION
ATR_PERIOD: int = cfg.ATR_PERIOD
ATR_MULTIPLIER_SL: float = cfg.ATR_MULTIPLIER_SL
ATR_MULTIPLIER_TP: float = cfg.ATR_MULTIPLIER_TP
HMA_PERIOD: int = cfg.HMA_PERIOD
RSI_PERIOD: int = cfg.RSI_PERIOD
NEWS_BLOCK_BEFORE: int = cfg.NEWS_BLOCK_BEFORE
NEWS_BLOCK_AFTER: int = cfg.NEWS_BLOCK_AFTER
ECONOMIC_CALENDAR_URL: str = cfg.ECONOMIC_CALENDAR_URL
ROLLOVER_HOURS: Dict[str, str] = cfg.ROLLOVER_HOURS
SESSION_HOURS_WIB: Dict[str, Dict[str, str]] = cfg.SESSION_HOURS_WIB
SESSION_HOURS_UTC: Dict[str, Dict[str, int]] = cfg.SESSION_HOURS_UTC
SESSION_ELIGIBLE_PAIRS: Dict[str, List[str]] = cfg.SESSION_ELIGIBLE_PAIRS
TRADING_HOURS: Dict[str, str] = cfg.TRADING_HOURS

# Dict turunan dari _fallback_config (backward compat)
SYMBOL_STRATEGIES: Dict[str, Optional[str]] = {
    sym: c.get("strategy") for sym, c in _fallback_config.items()
}
SYMBOL_SL_TP: Dict[str, Dict[str, int]] = {
    sym: {"sl": c.get("sl", 150), "tp": c.get("tp", 250)}
    for sym, c in _fallback_config.items()
}
