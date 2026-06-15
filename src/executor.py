import MetaTrader5 as mt5
import logging
from . import config

# Set up module logger
logger = logging.getLogger("executor")

def get_filling_mode(symbol: str) -> int:
    """
    Mendeteksi secara otomatis tipe pengisian order (Filling Mode) yang didukung oleh broker.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_RETURN
        
    filling_mode = info.filling_mode
    
    if filling_mode & mt5.SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    elif filling_mode & mt5.SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    else:
        return mt5.ORDER_FILLING_RETURN


def _send_with_fallback(request: dict, filling_mode: int, context: str = "") -> object:
    """
    Helper: kirim order via mt5.order_send dengan auto-fallback filling mode.
    Jika broker menolak filling mode (retcode 10030), coba mode alternatif.

    Args:
        request      : Dictionary request order (akan diubah type_filling-nya jika fallback).
        filling_mode : Filling mode awal yang dipilih.
        context      : Label konteks untuk log (misal "Open" atau "Close").

    Returns:
        Result object dari MT5, atau None jika semua percobaan gagal.
    """
    result = mt5.order_send(request)

    if result is not None and result.retcode == 10030:
        alternate_modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
        if filling_mode in alternate_modes:
            alternate_modes.remove(filling_mode)

        for alt_mode in alternate_modes:
            logger.info(f"[Executor] {context} Broker menolak mode pengisian "
                        f"{filling_mode} (Retcode 10030). "
                        f"Mencoba mode alternatif: {alt_mode}...")
            request["type_filling"] = alt_mode
            alt_result = mt5.order_send(request)
            if alt_result is not None:
                result = alt_result
                if alt_result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"[Executor] {context} BERHASIL dengan mode alternatif {alt_mode}!")
                    break

    return result


def open_market_order(symbol: str, direction: int, lot: float, sl_price: float, tp_price: float, comment: str = "") -> bool:
    """
    Membuka posisi instan (market order) Buy atau Sell dengan level SL dan TP.
    """

    info = mt5.symbol_info(symbol)
    if info is None:
        logger.error(f"Gagal mengambil info simbol {symbol} sebelum eksekusi.")
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        price = tick.ask if direction == 1 else tick.bid
    else:
        logger.warning(f"[Executor] Gagal mengambil tick terbaru untuk {symbol}, menggunakan data info.")
        price = info.ask if direction == 1 else info.bid

    if direction == 1:
        order_type = mt5.ORDER_TYPE_BUY
    elif direction == -1:
        order_type = mt5.ORDER_TYPE_SELL
    else:
        logger.error(f"Arah order tidak dikenal: {direction}")
        return False

    filling_mode = get_filling_mode(symbol)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": config.cfg.SLIPPAGE,
        "magic": config.cfg.MAGIC_NUMBER,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }

    result = _send_with_fallback(request, filling_mode, context="Open")

    if result is None:
        logger.error("[Executor] Gagal mengirim order. Tidak ada respon dari terminal MT5.")
        return False
        
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"[Executor] Order GAGAL! Simbol: {symbol}, Retcode: {result.retcode}, Pesan: {result.comment}")
        return False

    logger.info(f"[Executor] Order BERHASIL! Simbol: {symbol}, Arah: {'BUY' if direction == 1 else 'SELL'}, Lot: {lot}, Ticket: {result.order}")
    return True


def close_position_by_ticket(ticket: int) -> bool:
    """
    Menutup posisi trading berdasarkan tiket posisi yang aktif.
    """

    positions = mt5.positions_get(ticket=ticket)
    if not positions or len(positions) == 0:
        logger.error(f"[Executor] Gagal menutup posisi: Ticket {ticket} tidak ditemukan.")
        return False
        
    pos = positions[0]
    symbol = pos.symbol
    lot = pos.volume
    pos_type = pos.type

    info = mt5.symbol_info(symbol)
    if info is None:
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        price = tick.bid if pos_type == mt5.POSITION_TYPE_BUY else tick.ask
    else:
        logger.warning(f"[Executor] Gagal mengambil tick terbaru untuk {symbol} saat penutupan, menggunakan data info.")
        price = info.bid if pos_type == mt5.POSITION_TYPE_BUY else info.ask

    if pos_type == mt5.POSITION_TYPE_BUY:
        close_type = mt5.ORDER_TYPE_SELL
    elif pos_type == mt5.POSITION_TYPE_SELL:
        close_type = mt5.ORDER_TYPE_BUY
    else:
        return False

    filling_mode = get_filling_mode(symbol)

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": config.cfg.SLIPPAGE,
        "magic": config.cfg.MAGIC_NUMBER,
        "comment": "Close autopilot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }

    result = _send_with_fallback(request, filling_mode, context="Close")

    if result is None:
        return False
        
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"[Executor] Gagal menutup tiket {ticket}: {result.comment}")
        return False

    logger.info(f"[Executor] Berhasil menutup posisi tiket {ticket} pada harga {price}.")
    return True


def get_active_positions(symbol: str = None) -> list:
    """
    Mengambil daftar posisi aktif yang dibuka oleh robot ini (berdasarkan Magic Number).
    """

    if symbol:
        positions = mt5.positions_get(symbol=symbol)
    else:
        positions = mt5.positions_get()
        
    if not positions:
        return []

    robot_positions = [p for p in positions if p.magic == config.cfg.MAGIC_NUMBER]
    return robot_positions


def modify_position_sl(ticket: int, new_sl: float) -> bool:
    """
    Memodifikasi level Stop Loss (SL) untuk posisi trading aktif (Move SL to BE).
    """
        
    positions = mt5.positions_get(ticket=ticket)
    if not positions or len(positions) == 0:
        return False
        
    pos = positions[0]
    symbol = pos.symbol
    tp = pos.tp  # Pertahankan level TP yang lama
    
    # Jika SL baru sangat dekat dengan SL saat ini, lewatkan agar tidak spam order
    if abs(pos.sl - new_sl) < 1e-5:
        return True
        
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "symbol": symbol,
        "sl": new_sl,
        "tp": tp
    }
    
    result = mt5.order_send(request)
    if result is None:
        logger.error(f"[Executor] Tidak ada respon dari MT5 saat memodifikasi SL tiket {ticket}.")
        return False
        
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"[Executor] Gagal memindahkan SL tiket {ticket} ke {new_sl}. Retcode: {result.retcode}, Pesan: {result.comment}")
        return False
        
    logger.info(f"[Executor] Sukses memindahkan SL ke Break-Even ({new_sl}) untuk tiket {ticket}.")
    return True
