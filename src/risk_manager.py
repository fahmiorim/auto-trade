import MetaTrader5 as mt5
import logging
import time
from datetime import datetime

# Set up module logger
logger = logging.getLogger("risk_manager")

# ============================================
# Cache untuk symbol_info (kurangi round-trip MT5)
# ============================================
_symbol_info_cache = {}			# symbol -> (timestamp, info)
_symbol_info_cache_ttl = 5.0	# cache valid 5 detik


def _get_cached_symbol_info(symbol: str):
    """
    Ambil SymbolInfo dari cache jika masih fresh, jika tidak fetch ulang.
    Cache di-invalidate otomatis setiap _symbol_info_cache_ttl detik.
    """
    now = time.time()
    cached = _symbol_info_cache.get(symbol)
    if cached and (now - cached[0]) < _symbol_info_cache_ttl:
        return cached[1]

    info = mt5.symbol_info(symbol)
    _symbol_info_cache[symbol] = (now, info)
    return info


def _clear_symbol_info_cache():
    """Hapus semua cache symbol_info. Dipanggil dari test setup."""
    _symbol_info_cache.clear()

# ============================================
# State untuk Daily Loss & Consecutive Losses
# ============================================
_daily_start_balance = None
_current_date = None
_consecutive_losses = 0
_known_tickets = set()
_last_reset_time = ""


def reset_daily_tracker(balance: float) -> None:
    """
    Inisialisasi / reset state di awal hari atau startup.
    Panggil sekali saat robot mulai berjalan.
    """
    global _daily_start_balance, _current_date, _consecutive_losses
    global _known_tickets, _last_reset_time
    _daily_start_balance = balance
    _current_date = datetime.now().strftime("%Y-%m-%d")
    _consecutive_losses = 0
    _known_tickets = set()
    _last_reset_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[RiskManager] Daily tracker direset. Saldo awal: ${balance:.2f}")


def check_daily_loss_limit(balance: float,
                           max_loss_percent: float = 0.05) -> tuple[bool, str]:
    """
    Cek apakah total loss hari ini sudah melebihi batas.
    Membandingkan saldo saat ini dengan saldo awal hari.

    Args:
        balance          : Saldo akun saat ini.
        max_loss_percent : Maksimum loss harian (default 5%%).

    Returns:
        (is_allowed, reason_message)
        - is_allowed = False → robot harus stop trading.
    """
    global _daily_start_balance, _current_date

    # Auto-reset jika ganti hari
    today = datetime.now().strftime("%Y-%m-%d")
    if _daily_start_balance is None or _current_date != today:
        reset_daily_tracker(balance)
        return True, ""

    if _daily_start_balance <= 0:
        return True, ""

    loss_percent = (_daily_start_balance - balance) / _daily_start_balance * 100

    if loss_percent >= max_loss_percent * 100:
        msg = (f"Daily loss {loss_percent:.1f}%% melebihi batas "
               f"{max_loss_percent*100:.0f}%% "
               f"(${_daily_start_balance:.2f} → ${balance:.2f})")
        return False, msg

    return True, ""


def record_trade_result(profit_pips: float) -> None:
    """
    Catat hasil trade untuk melacak consecutive losses.
    Panggil setelah trade ditutup (SL atau TP terkena).

    Args:
        profit_pips : Profit/loss dalam pips (negatif = loss).
    """
    global _consecutive_losses

    if profit_pips < 0:
        _consecutive_losses += 1
        logger.warning(f"[RiskManager] Trade LOSS. "
                       f"Consecutive losses: {_consecutive_losses}")
    else:
        if _consecutive_losses > 0:
            logger.info(f"[RiskManager] Trade WIN. "
                        f"Consecutive losses reset to 0 "
                        f"(was {_consecutive_losses})")
        _consecutive_losses = 0


def check_max_consecutive_losses(max_consecutive: int = 3) -> tuple[bool, str]:
    """
    Cek apakah jumlah consecutive losses sudah melebihi batas.

    Args:
        max_consecutive : Batas maksimum loss beruntun (default 3).

    Returns:
        (is_allowed, reason_message)
    """
    if _consecutive_losses >= max_consecutive:
        msg = (f"Consecutive losses ({_consecutive_losses}) >= "
               f"limit ({max_consecutive})")
        return False, msg
    return True, ""


def track_positions(active_positions: list) -> None:
    """
    Deteksi posisi yang baru saja ditutup dan catat hasilnya.
    Panggil setiap iterasi loop utama.

    Cara kerja:
      1. Simpan set tiket dari iterasi sebelumnya.
      2. Bandingkan dengan tiket saat ini.
      3. Tiket yang hilang → posisi ditutup → query histori.

    Args:
        active_positions : List posisi aktif dari get_active_positions().
    """
    global _known_tickets

    current_tickets = {p.ticket for p in active_positions}
    closed_tickets = _known_tickets - current_tickets

    for ticket in closed_tickets:
        deals = _query_closed_deal(ticket)

        if deals and len(deals) > 0:
            # deals[-1] = closing deal (profit riil), deals[0] = opening deal (profit=0)
            deal = deals[-1]
            profit = deal.profit
            symbol = deal.symbol
            record_trade_result(profit)
            logger.info(f"[RiskManager] Posisi {symbol} (ticket={ticket}) "
                        f"ditutup dengan PnL ${profit:.2f}")
        else:
            logger.warning(f"[RiskManager] Posisi tiket={ticket} ditutup "
                          f"(histori tidak tersedia, dilewati)")

    _known_tickets = current_tickets


def _query_closed_deal(ticket: int) -> list:
    """
    Query histori MT5 untuk posisi yang sudah ditutup.
    Mencoba dua parameter name berbeda untuk kompatibilitas antar versi/build MT5.

    Args:
        ticket: Nomor tiket posisi yang sudah ditutup.

    Returns:
        List of deal objects, atau None jika gagal.
    """
    # Coba parameter 'position' (umum di build terbaru)
    try:
        deals = mt5.history_deals_get(position=ticket)
        if deals and len(deals) > 0:
            return deals
    except Exception:
        pass

    # Fallback: coba parameter 'ticket' (beberapa build MT5 lain)
    try:
        deals = mt5.history_deals_get(ticket=ticket)
        if deals and len(deals) > 0:
            return deals
    except Exception:
        pass

    return None


def get_risk_status() -> dict:
    """Kembalikan status risk saat ini untuk logging / dashboard.
    Mengembalikan copy value, aman dipanggil dari thread berbeda."""
    return {
        "daily_start_balance": float(_daily_start_balance) if _daily_start_balance is not None else None,
        "consecutive_losses": int(_consecutive_losses),
        "last_reset": str(_last_reset_time),
    }

def calculate_dynamic_lot(symbol: str, balance: float, risk_percent: float, sl_points: float) -> float:
    """
    Menghitung ukuran lot secara dinamis berdasarkan persentase risiko saldo
    dan jarak Stop Loss (dalam points).
    """
    if sl_points <= 0:
        return 0.0

    info = _get_cached_symbol_info(symbol)
    if info is None:
        logger.error(f"Gagal mengambil spesifikasi simbol {symbol} untuk perhitungan lot.")
        return 0.0

    tick_value = info.trade_tick_value
    tick_size  = info.trade_tick_size
    min_lot    = info.volume_min
    max_lot    = info.volume_max
    lot_step   = info.volume_step

    risk_amount  = balance * risk_percent
    loss_per_lot = (sl_points * (info.point / tick_size)) * tick_value
    raw_lot      = risk_amount / (loss_per_lot + 1e-9)
    refined_lot  = round(raw_lot / lot_step) * lot_step

    if refined_lot < min_lot:
        return 0.0
    elif refined_lot > max_lot:
        refined_lot = max_lot

    step_decimals = len(str(lot_step).split('.')[1]) if '.' in str(lot_step) else 0
    return round(refined_lot, step_decimals)


def enforce_broker_stops(symbol: str, sl_points: float, tp_points: float) -> tuple:
    """
    Memastikan SL dan TP tidak lebih kecil dari stops_level minimum broker.
    Jika lebih kecil, otomatis dinaikkan ke batas minimum broker + buffer 10 points.
    Mengembalikan (sl_points, tp_points) yang sudah aman.
    """
    info = _get_cached_symbol_info(symbol)
    if info is None:
        return sl_points, tp_points

    stops_level = info.trade_stops_level
    freeze_level = info.trade_freeze_level
    spread = info.spread

    # Buffer minimum: stops_level + spread + 10 points keamanan
    min_required = max(stops_level, freeze_level) + spread + 10

    if sl_points < min_required:
        old_sl = sl_points
        sl_points = min_required
        logger.warning(f"[BrokerRule] {symbol}: SL disesuaikan {old_sl} → {sl_points} points "
                       f"(stops_level={stops_level}, spread={spread})")

    if tp_points < min_required:
        old_tp = tp_points
        tp_points = min_required
        logger.warning(f"[BrokerRule] {symbol}: TP disesuaikan {old_tp} → {tp_points} points "
                       f"(stops_level={stops_level}, spread={spread})")

    return sl_points, tp_points


def get_adjusted_sl_tp(symbol: str, direction: int, entry_price: float,
                       sl_points: float, tp_points: float,
                       commission_per_lot: float = 6.0) -> tuple:
    """
    Menghitung level harga SL dan TP yang telah disesuaikan dengan:
    - Spread real-time broker
    - Komisi broker (dalam points)
    - Aturan stops_level minimum broker (otomatis adjust jika perlu)
    """
    info = _get_cached_symbol_info(symbol)
    if info is None:
        return None, None

    point      = info.point
    tick_value = info.trade_tick_value
    tick_size  = info.trade_tick_size

    # Validasi & enforce aturan minimum broker
    sl_points, tp_points = enforce_broker_stops(symbol, sl_points, tp_points)

    # Hitung biaya komisi dalam points (tidak lagi menyertakan spread_points ke TP)
    commission_points  = (commission_per_lot / (tick_value + 1e-9)) * (tick_size / point)

    if direction == 1:   # BUY
        sl_price  = entry_price - (sl_points * point)
        tp_price  = entry_price + (tp_points * point) + (commission_points * point)
    elif direction == -1:  # SELL
        sl_price  = entry_price + (sl_points * point)
        tp_price  = entry_price - (tp_points * point) - (commission_points * point)
    else:
        return None, None

    return round(sl_price, info.digits), round(tp_price, info.digits)
