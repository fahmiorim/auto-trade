import MetaTrader5 as mt5
import time
from datetime import datetime
import pytz
import pandas as pd
import logging
from src import config
from src.results_db import get_best_config, print_leaderboard
from src import data_fetcher
from src import strategies
from src import risk_manager
from src import news_filter
from src import executor

# Configure logging framework
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("main")

# Definisikan zona waktu WIB
WIB = pytz.timezone('Asia/Jakarta')

# Pelacakan waktu candle transaksi terakhir per (symbol, strategy) untuk mencegah double entry
last_trade_candle_times = {}

# Sinyal stop untuk eksekusi via GUI
gui_stop_signal = False


def validate_account_balance() -> bool:
    """
    Validasi saldo akun saat startup.
    Cek apakah saldo cukup untuk menjalankan minimal 1 pair aktif.
    Tampilkan laporan lengkap per pair dan saran jika tidak mencukupi.
    """
    account = mt5.account_info()
    if account is None:
        logger.error("Tidak dapat membaca info akun dari MT5.")
        return False

    balance  = account.balance
    currency = account.currency
    leverage = account.leverage

    # Keep table formatting using standard print for clean alignment in terminal
    print(f"\n{'='*58}")
    print(f"  VALIDASI SALDO AKUN")
    print(f"{'='*58}")
    print(f"  Broker   : {account.company}")
    print(f"  Akun     : {account.login} ({account.server})")
    print(f"  Tipe     : {'DEMO' if account.trade_mode == 0 else 'LIVE'}")
    print(f"  Saldo    : {balance:,.2f} {currency}")
    print(f"  Leverage : 1:{leverage}")
    print(f"{'='*58}")
    print(f"  Status per Pair:")
    print(f"  {'PAIR':<8} {'STRAT':>5} {'SL':>5} {'Min Saldo':>12} {'Status'}")
    print(f"  {'-'*54}")

    can_trade    = []
    cannot_trade = []

    for symbol in config.cfg.SYMBOLS:
        strat = config.SYMBOL_STRATEGIES.get(symbol)
        if strat is None:
            print(f"  {symbol:<8} {'OFF':>5}  {'N/A':>5}  {'N/A':>12}  [NONAKTIF]")
            continue

        sl_points = config.SYMBOL_SL_TP.get(symbol, {}).get('sl', 150)
        lot       = risk_manager.calculate_dynamic_lot(symbol, balance, config.cfg.RISK_PERCENT, sl_points)

        # Hitung saldo minimum untuk bisa trade pair ini (lot minimum 0.01)
        info = risk_manager._get_cached_symbol_info(symbol)
        if info is None:
            continue
        tick_value     = info.trade_tick_value
        tick_size      = info.trade_tick_size
        min_lot        = info.volume_min
        loss_per_minlot = (sl_points * (info.point / tick_size)) * tick_value * min_lot
        min_balance    = loss_per_minlot / config.cfg.RISK_PERCENT

        if lot >= min_lot:
            status = f"[OK] lot={lot:.2f}"
            can_trade.append(symbol)
        else:
            status = f"[SALDO KURANG] butuh min ${min_balance:,.0f}"
            cannot_trade.append((symbol, min_balance))

        print(f"  {symbol:<8} {strat:>5}  {sl_points:>5}  ${min_balance:>10,.0f}  {status}")

    print(f"  {'='*54}")

    if can_trade:
        print(f"  Bisa trading  : {len(can_trade)} pair ({', '.join(can_trade)})")
    if cannot_trade:
        print(f"  Tidak bisa    : {len(cannot_trade)} pair (saldo kurang)")
        max_min = max(v for _, v in cannot_trade)
        print(f"  Saldo sekarang: {balance:,.2f} {currency}")
        print(f"  Saldo optimal : ${max_min:,.0f} (agar semua pair aktif)")
        print(f"")
        print(f"  Solusi:")
        print(f"  1. Tambah deposit minimal ${max_min:,.0f}")
        print(f"  2. Atau naikkan RISK_PERCENT di config.py (hati-hati!)")
        print(f"  3. Atau jalankan hanya {len(can_trade)} pair yang saldo-nya cukup")

    print(f"{'='*58}\n")

    if not can_trade:
        logger.critical("Tidak ada satu pun pair yang bisa trading! Saldo terlalu kecil.")
        logger.warning(f"Saldo {balance:.2f} {currency} terlalu kecil untuk semua pair aktif.")
        logger.warning("Robot tetap berjalan tapi tidak akan membuka order apapun.")
        return False

    return True

def is_market_open() -> bool:
    """
    Cek apakah pasar forex sedang buka berdasarkan 3 lapis pengecekan:
    1. Akhir pekan (Sabtu-Minggu) — forex global tutup
    2. Status market dari MT5 langsung — broker bisa tutup sewaktu-waktu
    3. Rollover hours
    """
    now_wib  = datetime.now(WIB)
    time_str = now_wib.strftime("%H:%M")
    day_name = now_wib.strftime("%A")
    weekday  = now_wib.weekday()

    # CEK 1: Akhir pekan
    if weekday == 6:
        if now_wib.minute % 30 == 0 and now_wib.second < 15:
            logger.info("Market tutup: Hari Minggu, pasar forex global libur.")
        return False
    if weekday == 5 and time_str >= "05:00":
        if now_wib.minute % 30 == 0 and now_wib.second < 15:
            logger.info(f"Market tutup: Sabtu {time_str} WIB, pasar forex sudah tutup.")
        return False
    if weekday == 0 and time_str < "05:00":
        if now_wib.minute % 30 == 0 and now_wib.second < 15:
            logger.info(f"Market tutup: Senin {time_str} WIB, pasar forex belum dibuka.")
        return False

    # CEK 2: Status MT5 (Cek beberapa pair major untuk redundansi)
    check_symbols = ["EURUSD", "USDJPY", "GBPUSD"]
    active_market = False
    checked_count = 0
    
    for sym in check_symbols:
        info = risk_manager._get_cached_symbol_info(sym)
        if info is not None:
            checked_count += 1
            if info.trade_mode != 0 and info.spread > 0:
                active_market = True
                break
                
    if checked_count > 0 and not active_market:
        if now_wib.minute % 15 == 0 and now_wib.second < 15:
            logger.info("Market tutup: Broker maintenance atau semua pair major tidak aktif.")
        return False

    # CEK 3: Rollover
    rollover_start = config.cfg.ROLLOVER_HOURS["START"]
    rollover_end   = config.cfg.ROLLOVER_HOURS["END"]
    if rollover_start < rollover_end:
        is_rollover = rollover_start <= time_str <= rollover_end
    else:
        is_rollover = time_str >= rollover_start or time_str <= rollover_end

    if is_rollover:
        if now_wib.minute % 15 == 0 and now_wib.second < 15:
            logger.info(f"Jam rollover ({time_str} WIB) — robot standby/libur.")
        return False

    return True




def get_current_session() -> str:
    """
    Tentukan nama sesi trading yang sedang aktif berdasarkan jam WIB saat ini.
    Returns: 'ASIA', 'LONDON', 'LONDON_NY', 'NEW_YORK', atau None
    """
    now_wib  = datetime.now(WIB)
    time_str = now_wib.strftime("%H:%M")

    for session, hours in config.cfg.SESSION_HOURS_WIB.items():
        start = hours["START"]
        end   = hours["END"]
        if start < end:
            if start <= time_str < end:
                return session
        else:
            # Melewati tengah malam (NEW_YORK)
            if time_str >= start or time_str < end:
                return session
    return None


def check_active_positions_for_be():
    """
    Memantau posisi aktif yang dibuka oleh robot ini.
    Jika posisi sudah profit >= 10 pips (100 points), SL akan digeser ke BE (harga entry).
    """
    active_pos = executor.get_active_positions()
    for pos in active_pos:
        symbol = pos.symbol
        ticket = pos.ticket
        entry = pos.price_open
        current_sl = pos.sl
        pos_type = pos.type
        
        info = risk_manager._get_cached_symbol_info(symbol)
        if info is None:
            continue
            
        point = info.point
        current_price = info.bid if pos_type == mt5.POSITION_TYPE_BUY else info.ask
        
        # Jarak profit saat ini dalam points
        if pos_type == mt5.POSITION_TYPE_BUY:
            profit_points = (current_price - entry) / point
            # Jika profit >= 10 pips (100 points) dan SL belum dipindahkan ke Entry
            if profit_points >= 100 and current_sl < entry:
                executor.modify_position_sl(ticket, entry)
        elif pos_type == mt5.POSITION_TYPE_SELL:
            profit_points = (entry - current_price) / point
            # Jika profit >= 10 pips (100 points) dan SL belum dipindahkan ke Entry (SL Sell di atas entry)
            if profit_points >= 100 and (current_sl > entry or current_sl == 0):
                executor.modify_position_sl(ticket, entry)


def process_symbol(symbol: str, session: str):
    """
    Proses utama per-simbol: ambil data -> cari sinyal -> kelola order.
    Strategi dan SL/TP diambil dari konfigurasi sesi yang sedang aktif.
    """
    global last_trade_candle_times
    # Ambil sesi aktif dan gunakan strategi + SL/TP khusus sesi itu
    strat_name = config.get_session_strategy(symbol, session)
    if strat_name is None:
        return  # Pair tidak aktif / tidak PASSED di sesi ini

    # Cek apakah pair ini eligible di sesi aktif
    eligible = config.cfg.SESSION_ELIGIBLE_PAIRS.get(session, config.cfg.SYMBOLS)
    if symbol not in eligible:
        return

    active_pos = executor.get_active_positions(symbol)
    if len(active_pos) > 0:
        return

    if news_filter.is_news_blocked(symbol):
        return

    # Fetch 2500 baris agar strategi dapat menghitung EMA 2400 untuk trend H1
    df_m5 = data_fetcher.fetch_history(symbol, config.cfg.TIMEFRAME_M5, 2500)
    if df_m5.empty:
        return
        
    df_m1 = pd.DataFrame()
    signal = 0
    
    if strat_name == "A":
        # Metode A butuh M1 history
        df_m1 = data_fetcher.fetch_history(symbol, config.cfg.TIMEFRAME_M1, 250)
        if df_m1.empty:
            return

    # Tentukan waktu candle closed pemicu transaksi untuk mencegah double entry
    if strat_name == "A":
        candle_time = df_m1['time'].iloc[-2]
    else:
        candle_time = df_m5['time'].iloc[-2]

    key = (symbol, strat_name)
    if last_trade_candle_times.get(key) == candle_time:
        return
    
    if strat_name == "A":
        signal = strategies.strategy_a_triple_ema_stochastic(df_m1, df_m5)
    elif strat_name == "B":
        signal = strategies.strategy_b_bollinger_bands_stochastic(df_m5)
    elif strat_name == "C":
        signal = strategies.strategy_c_heikin_ashi_atr(df_m5)
    elif strat_name == "D":
        signal = strategies.strategy_d_fvg_smc(df_m5)
    elif strat_name == "E":
        signal = strategies.strategy_e_hma_rsi(df_m5)

    if signal != 0:
        logger.info(f"Sinyal Terdeteksi | Simbol: {symbol}, Arah: {'BUY' if signal == 1 else 'SELL'} (Strategi {strat_name})")
        
        account = mt5.account_info()
        if account is None:
            return
        balance = account.balance
        
        sl_tp     = config.get_session_sl_tp(symbol, session)
        sl_points = sl_tp.get("sl", 150)
        tp_points = sl_tp.get("tp", 250)
        
        lot = risk_manager.calculate_dynamic_lot(symbol, balance, config.cfg.RISK_PERCENT, sl_points)
        if lot <= 0:
            info_sym = risk_manager._get_cached_symbol_info(symbol)
            if info_sym:
                tick_value      = info_sym.trade_tick_value
                tick_size       = info_sym.trade_tick_size
                min_lot         = info_sym.volume_min
                loss_per_minlot = (sl_points * (info_sym.point / tick_size)) * tick_value * min_lot
                min_balance     = loss_per_minlot / config.RISK_PERCENT
                logger.warning(f"{symbol}: Tidak bisa order — saldo ${balance:,.2f} "
                               f"di bawah minimum ${min_balance:,.0f} "
                               f"(butuh SL={sl_points} pts dengan lot min {min_lot})")
            else:
                logger.warning(f"{symbol}: Lot = 0, saldo tidak mencukupi.")
            return
            
        info = risk_manager._get_cached_symbol_info(symbol)
        if info is None:
            logger.error(f"Gagal mengambil info simbol {symbol} sebelum eksekusi order.")
            return
            
        entry_price = info.ask if signal == 1 else info.bid
        sl_price, tp_price = risk_manager.get_adjusted_sl_tp(
            symbol, signal, entry_price, sl_points, tp_points
        )
        
        if sl_price is None or tp_price is None:
            return
 
        success = executor.open_market_order(
            symbol=symbol,
            direction=signal,
            lot=lot,
            sl_price=sl_price,
            tp_price=tp_price,
            comment=f"Autopilot {strat_name}"
        )
        
        if success:
            logger.info(f"Berhasil entri posisi {symbol} (Lot: {lot}, SL: {sl_price}, TP: {tp_price})")
            last_trade_candle_times[key] = candle_time


def main():
    print("==================================================")
    print("       ROBOT TRADING AUTOPILOT MT5 RUNNING        ")
    print("  Parameter dibaca otomatis dari trading_results.db")
    print("==================================================")
    # Tampilkan leaderboard parameter yang sedang aktif (keep as stdout print)
    print_leaderboard()
    print("==================================================")
    best = get_best_config()
    db_count = sum(1 for v in best.values() if v.get('source') == 'db' and v.get('strategy'))
    default_count = sum(1 for v in best.values() if v.get('source') == 'default' and v.get('strategy'))
    if default_count > 0:
        logger.info(f"{db_count} pair dari DB, {default_count} pair dari default.")
        logger.warning("Jalankan 'python tune_all.py' untuk mengisi DB.")
    else:
        logger.info(f"Semua {db_count} pair aktif menggunakan parameter dari DB.")
    print("==================================================")

    if not mt5.initialize():
        logger.error(f"Gagal menginisialisasi MT5. Error: {mt5.last_error()}")
        return

    # Validasi saldo akun saat startup
    validate_account_balance()

    # Reset daily risk tracker
    account = mt5.account_info()
    if account is not None:
        risk_manager.reset_daily_tracker(account.balance)

    global gui_stop_signal
    gui_stop_signal = False

    try:
        while not gui_stop_signal:
            try:
                # 1. Kelola active positions (Trailing SL ke BE jika profit >= 10 pips)
                check_active_positions_for_be()
                
                # 2. Deteksi posisi yang baru ditutup untuk tracking consecutive losses
                risk_manager.track_positions(executor.get_active_positions())
                
                # 3. Cek status pasar dan sesi
                if is_market_open():
                    session = get_current_session()
                    if session:
                        eligible = config.cfg.SESSION_ELIGIBLE_PAIRS.get(session, config.cfg.SYMBOLS)
                        now_wib = datetime.now(WIB)
                        now_str = now_wib.strftime("%H:%M")
                        if now_wib.second < 15 and now_wib.minute % 5 == 0:
                            logger.info(f"Sesi aktif: {session} — Scan {len(eligible)} pair: {', '.join(eligible)}")
                        
                        # Risk check sebelum scan pair
                        account_info = mt5.account_info()
                        if account_info is not None:
                            allowed, msg = risk_manager.check_daily_loss_limit(
                                account_info.balance
                            )
                            if not allowed:
                                logger.warning(f"[RiskManager] Trading dihentikan: {msg}")
                                # Tetap loop untuk monitoring, tapi skip entri baru
                                for _ in range(150):
                                    if gui_stop_signal:
                                        break
                                    time.sleep(0.1)
                                continue
                            
                            allowed, msg = risk_manager.check_max_consecutive_losses()
                            if not allowed:
                                logger.warning(f"[RiskManager] Trading dihentikan: {msg}")
                                for _ in range(150):
                                    if gui_stop_signal:
                                        break
                                    time.sleep(0.1)
                                continue
                        
                        for symbol in eligible:
                            if gui_stop_signal:
                                break
                            try:
                                process_symbol(symbol, session)
                            except Exception as e:
                                logger.error(f"Error memproses simbol {symbol}: {e}")
                            
                            # Sleep yang responsif terhadap stop signal
                            for _ in range(10):
                                if gui_stop_signal:
                                    break
                                time.sleep(0.1)
                    else:
                        # Di luar semua sesi tapi market buka (transisi antar sesi)
                        now_wib = datetime.now(WIB)
                        if now_wib.minute % 15 == 0 and now_wib.second < 15:
                            logger.info("Transisi antar sesi — standby sebentar.")
            except Exception as e:
                logger.error(f"Error pada loop utama: {e}")
                
            # Sleep 15 detik yang responsif terhadap stop signal
            for _ in range(150):
                if gui_stop_signal:
                    break
                time.sleep(0.1)
            
    except KeyboardInterrupt:
        logger.info("Menyelesaikan sesi trading, mematikan robot...")
    finally:
        mt5.shutdown()
        logger.info("Koneksi MT5 ditutup. Robot mati dengan aman.")

if __name__ == "__main__":
    main()
