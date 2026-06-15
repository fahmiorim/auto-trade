import pandas as pd
import numpy as np
import time
import os
from datetime import datetime, timedelta, timezone
from src import config
from src import strategies
from src.data_fetcher import get_heikin_ashi
from src.database import fetch_db_rates_m1, fetch_db_rates_m5, fetch_db_economic_calendar

def check_and_update_databases():
    """
    Memeriksa apakah data di DuckDB dan SQLite sudah up-to-date.
    Jika tidak, menjalankan sinkronisasi otomatis secara aman.
    """
    print("[Database Check] Memeriksa kesegaran data historis...")
    
    # 1. Cek DuckDB (Harga)
    db_duck_path = os.path.join("data", "mt5_data.db")
    if os.path.exists(db_duck_path):
        import duckdb
        con = duckdb.connect(db_duck_path, read_only=True)
        try:
            res = con.execute("SELECT MAX(time_utc) FROM candles_m5 WHERE symbol = 'EURUSD'").fetchone()
            last_price_utc = res[0]
        except Exception:
            last_price_utc = None
        finally:
            con.close()
    else:
        last_price_utc = None
        
    # 2. Cek SQLite (Berita)
    db_sqlite_path = os.path.join("data", "mt5_ops.db")
    if os.path.exists(db_sqlite_path):
        import sqlite3
        con = sqlite3.connect(db_sqlite_path)
        try:
            cur = con.cursor()
            cur.execute("SELECT MAX(time_utc) FROM economic_calendar")
            last_news_utc_str = cur.fetchone()[0]
            last_news_utc = pd.to_datetime(last_news_utc_str) if last_news_utc_str else None
        except Exception:
            last_news_utc = None
        finally:
            con.close()
    else:
        last_news_utc = None

    now_utc = datetime.now(timezone.utc)
    
    # Aturan Pengecekan Harga (Price Check Rules)
    weekday = now_utc.weekday()
    if weekday == 5:    # Sabtu
        target_price_limit = now_utc.replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(days=1)
    elif weekday == 6:  # Minggu
        target_price_limit = now_utc.replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(days=2)
    else:
        # Hari kerja: data harus ada minimal dalam 4 jam terakhir
        target_price_limit = now_utc - timedelta(hours=4)

    # Aturan Pengecekan Berita (News Check Rules): Berita harus terisi untuk minggu ini (sejak hari Senin)
    week_start_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now_utc.weekday())
    target_news_limit = week_start_utc - timedelta(days=1) # Minimal hari Minggu sebelum Senin dimulai

    # Set timezone-naive untuk perbandingan
    if last_price_utc and last_price_utc.tzinfo is not None:
        last_price_utc = last_price_utc.replace(tzinfo=None)
    if last_news_utc and last_news_utc.tzinfo is not None:
        last_news_utc = last_news_utc.replace(tzinfo=None)
        
    target_price_limit = target_price_limit.replace(tzinfo=None)
    target_news_limit = target_news_limit.replace(tzinfo=None)
    
    need_price_sync = (last_price_utc is None) or (last_price_utc < target_price_limit)
    need_news_sync = (last_news_utc is None) or (last_news_utc < target_news_limit)
    
    if need_price_sync or need_news_sync:
        print("[Database Check] Peringatan: Data database Anda usang/tidak up-to-date!")
        if last_price_utc:
            print(f"  - Terakhir harga  : {last_price_utc} UTC (Target Min: {target_price_limit} UTC)")
        else:
            print("  - Terakhir harga  : Tidak ditemukan data")
            
        if last_news_utc:
            print(f"  - Terakhir berita : {last_news_utc} UTC (Target Min: {target_news_limit} UTC)")
        else:
            print("  - Terakhir berita : Tidak ditemukan data")
            
        print("[Database Check] Menjalankan sinkronisasi otomatis...")
        
        # Jalankan update_db
        if need_price_sync:
            try:
                import update_db
                success = update_db.main()
                if not success:
                    print("[Database Check] Peringatan: Sinkronisasi data harga selesai dengan status gagal (lanjut dengan data lama).")
            except Exception as e:
                print(f"[Database Check] Gagal sinkronisasi data harga: {e} (lanjut dengan data lama).")
            
        # Jalankan update_news
        if need_news_sync:
            try:
                import update_news
                success = update_news.main()
                if not success:
                    print("[Database Check] Peringatan: Sinkronisasi berita selesai dengan status gagal (lanjut dengan data lama).")
            except Exception as e:
                print(f"[Database Check] Gagal sinkronisasi data berita: {e} (lanjut dengan data lama).")
    else:
        print(f"[Database Check] Sukses: Data sudah up-to-date.")
        print(f"  - Terakhir harga  : {last_price_utc} UTC")
        print(f"  - Terakhir berita : {last_news_utc} UTC")


def load_news_block_times(currencies: list) -> dict:
    """
    Mengambil data kalender ekonomi historis dari SQLite (via src.database) 
    dan membuat set waktu terblokir untuk pencarian O(1) cepat.
    """
    print("Memuat data histori berita ekonomi...")
    df_news = fetch_db_economic_calendar()
    
    if df_news.empty:
        print("Peringatan: Tidak ada data berita ekonomi yang dimuat.")
        return {curr: set() for curr in currencies}

    blocked_times = {curr: set() for curr in currencies}
    blocked_times['All'] = set()
    
    for _, row in df_news.iterrows():
        t_event = row['time_utc']
        country = row['country']
        
        if country not in blocked_times:
            blocked_times[country] = set()
            
        t_base = t_event.replace(second=0, microsecond=0)
        
        # Tambahkan semua kelipatan 5 menit dalam rentang blokir
        for offset in range(-config.cfg.NEWS_BLOCK_BEFORE, config.cfg.NEWS_BLOCK_AFTER + 1, 5):
            t_blocked = t_base + timedelta(minutes=offset)
            blocked_times[country].add(t_blocked)
            
    print(f"Jendela blokir berita berhasil disiapkan untuk {len(blocked_times)} mata uang.")
    return blocked_times


def preprocess_symbol_data(symbol: str, limit_bars: int, news_blocks: dict) -> pd.DataFrame:
    """
    Mengambil data candlestick, menghitung seluruh indikator teknikal untuk 
    kelima strategi (A, B, C, D, E) serta menyelaraskan timeframe M5 & M1, 
    dan menyiapkan filter rollover/berita sebelum loop backtest dimulai.
    """
    print(f"[Pre-processing {symbol}] Menarik data dan menghitung indikator...")
    
    # 1. Ambil data M5 dan M1 dari DuckDB
    df_m5 = fetch_db_rates_m5(symbol, limit_bars)
    if df_m5.empty:
        print(f"  [Error] Gagal mengambil data M5 untuk {symbol}")
        return pd.DataFrame()
        
    df_m5 = df_m5.sort_values('time').reset_index(drop=True)
    
    df_m1 = fetch_db_rates_m1(symbol, limit_bars * 5)
    if not df_m1.empty:
        df_m1 = df_m1.sort_values('time').reset_index(drop=True)
        
    # 2. Hitung Indikator untuk M5
    # Indikator Tren & ATR Dasar
    df_m5['m5_ema200'] = strategies.calculate_ema(df_m5['close'], 200)
    df_m5['atr'] = strategies.calculate_atr(df_m5, 14)
    df_m5['atr_sma'] = df_m5['atr'].rolling(window=50).mean()
    
    # Metode B
    df_m5['bb_upper'], df_m5['bb_middle'], df_m5['bb_lower'] = strategies.calculate_bollinger_bands(df_m5, 20, 2.0)
    df_m5['stoch_k'], df_m5['stoch_d'] = strategies.calculate_stochastic(df_m5, 5, 3, 3)
    
    # Metode C
    df_ha = get_heikin_ashi(df_m5)
    df_m5['ha_open'] = df_ha['ha_open']
    df_m5['ha_high'] = df_ha['ha_high']
    df_m5['ha_low'] = df_ha['ha_low']
    df_m5['ha_close'] = df_ha['ha_close']
    
    # Metode E
    df_m5['hma55'] = strategies.calculate_hma(df_m5['close'], 55)
    df_m5['rsi2'] = strategies.calculate_rsi(df_m5['close'], 2)
    
    # 3. Hitung Indikator M1 & Lakukan Pre-Alignment (pd.merge_asof) untuk Metode A
    if not df_m1.empty:
        df_m1['ema9'] = strategies.calculate_ema(df_m1['close'], 9)
        df_m1['ema21'] = strategies.calculate_ema(df_m1['close'], 21)
        # Shift M1 EMA untuk mendapatkan crossover
        df_m1['ema9_prev'] = df_m1['ema9'].shift(1)
        df_m1['ema21_prev'] = df_m1['ema21'].shift(1)
        df_m1['stoch_k'], df_m1['stoch_d'] = strategies.calculate_stochastic(df_m1, 5, 3, 3)
        
        # Rename kolom M1 agar jelas dan terhindar dari konflik dengan M5
        df_m1_renamed = df_m1[['time', 'ema9', 'ema21', 'ema9_prev', 'ema21_prev', 'stoch_k', 'stoch_d']].rename(
            columns={
                'time': 'm1_time',
                'ema9': 'm1_ema9',
                'ema21': 'm1_ema21',
                'ema9_prev': 'm1_ema9_prev',
                'ema21_prev': 'm1_ema21_prev',
                'stoch_k': 'm1_stoch_k',
                'stoch_d': 'm1_stoch_d'
            }
        )
        
        # Cast merge keys ke precision yang sama (datetime64[ns])
        df_m1_renamed['m1_time'] = pd.to_datetime(df_m1_renamed['m1_time']).astype('datetime64[ns]')
        df_m5['time'] = pd.to_datetime(df_m5['time']).astype('datetime64[ns]')
        
        # Hitung end_time dari candle M5 (T_start + 5 menit)
        df_m5['m5_end_time'] = (df_m5['time'] + pd.Timedelta(minutes=5)).astype('datetime64[ns]')
        
        # Gabungkan secara asinkron berdasarkan waktu (direction backward, allow_exact_matches=False)
        df_m5 = pd.merge_asof(
            df_m5.sort_values('time'),
            df_m1_renamed.sort_values('m1_time'),
            left_on='m5_end_time',
            right_on='m1_time',
            direction='backward',
            allow_exact_matches=False
        )
        df_m5 = df_m5.drop(columns=['m5_end_time', 'm1_time'])
    else:
        # Tambahkan kolom kosong agar tidak error jika df_m1 kosong
        for col in ['m1_ema9', 'm1_ema21', 'm1_ema9_prev', 'm1_ema21_prev', 'm1_stoch_k', 'm1_stoch_d']:
            df_m5[col] = np.nan
            
    # 4. Pre-calculate Filter Rollover (WIB: 03:45 s.d. 05:15)
    # Data disimpan dalam waktu UTC. Konversi ke WIB secara vektor (+7 jam)
    times_wib = df_m5['time'] + pd.Timedelta(hours=7)
    hours_wib = times_wib.dt.hour.values
    minutes_wib = times_wib.dt.minute.values
    df_m5['is_rollover'] = (
        ((hours_wib == 3) & (minutes_wib >= 45)) |
        (hours_wib == 4) |
        ((hours_wib == 5) & (minutes_wib <= 15))
    )
    
    # 5. Pre-calculate Filter Berita
    base_curr = symbol[:3]
    quote_curr = symbol[3:6]
    news_set = news_blocks.get(base_curr, set()).union(news_blocks.get(quote_curr, set())).union(news_blocks.get('All', set()))
    df_m5['is_news_blocked'] = df_m5['time'].isin(news_set)
    
    return df_m5


def run_duckdb_backtest(symbol: str, strategy_name: str, df_main: pd.DataFrame, limit_bars: int = 50000, sl_points: int = 150, tp_points: int = 250, commission_points: float = 6.0, start_idx: int = 200) -> dict:
    """
    Menjalankan simulasi backtest dengan array NumPy untuk kecepatan eksekusi tinggi (Metode Asli).
    """
    if df_main.empty:
        return {}

    # Indikator spesifikasi simbol
    point = 0.01 if symbol == "XAUUSD" else (0.001 if "JPY" in symbol else 0.00001)
    digits = 2 if symbol == "XAUUSD" else (3 if "JPY" in symbol else 5)
    
    # Konversi kolom DataFrame ke NumPy array mentah
    time_arr = df_main['time'].values
    open_arr = df_main['open'].values
    high_arr = df_main['high'].values
    low_arr = df_main['low'].values
    close_arr = df_main['close'].values
    spread_arr = df_main['spread'].values
    is_rollover_arr = df_main['is_rollover'].values
    is_news_blocked_arr = df_main['is_news_blocked'].values
    
    # Ekstrak array spesifik indikator strategi
    if strategy_name == "A":
        m5_ema200_arr = df_main['m5_ema200'].values
        m1_ema9_arr = df_main['m1_ema9'].values
        m1_ema21_arr = df_main['m1_ema21'].values
        m1_ema9_prev_arr = df_main['m1_ema9_prev'].values
        m1_ema21_prev_arr = df_main['m1_ema21_prev'].values
        m1_stoch_k_arr = df_main['m1_stoch_k'].values
        m1_stoch_d_arr = df_main['m1_stoch_d'].values
    elif strategy_name == "B":
        bb_upper_arr = df_main['bb_upper'].values
        bb_lower_arr = df_main['bb_lower'].values
        stoch_k_arr = df_main['stoch_k'].values
        stoch_d_arr = df_main['stoch_d'].values
    elif strategy_name == "C":
        atr_arr = df_main['atr'].values
        atr_sma_arr = df_main['atr_sma'].values
        ha_open_arr = df_main['ha_open'].values
        ha_high_arr = df_main['ha_high'].values
        ha_low_arr = df_main['ha_low'].values
        ha_close_arr = df_main['ha_close'].values
    elif strategy_name == "D":
        m5_ema200_arr = df_main['m5_ema200'].values
        atr_arr = df_main['atr'].values
    elif strategy_name == "E":
        hma55_arr = df_main['hma55'].values
        rsi2_arr = df_main['rsi2'].values

    trades = []
    active_trade = None
    
    print(f"Simulasi {strategy_name} pada {symbol} dimulai ({len(df_main) - start_idx:,} bar)...")
    
    for i in range(start_idx, len(df_main) - 1):
        # A. CEK EKSEKUSI TRANSAKSI AKTIF (SL / TP)
        if active_trade is not None:
            bar_high = high_arr[i]
            bar_low = low_arr[i]
            current_time = time_arr[i]
            
            pip_divisor = 10.0
            total_loss_pips = -(sl_points + commission_points) / pip_divisor
            total_profit_pips = tp_points / pip_divisor
            bar_spread = spread_arr[i]
            
            if active_trade['type'] == 'BUY':
                # Cek pemicu SL/TP (BUY ditutup pada harga Bid: bar_low/bar_high)
                if bar_low <= active_trade['sl']:
                    trades.append({'time': pd.to_datetime(current_time), 'type': 'BUY', 'result': 'SL', 'pnl': total_loss_pips})
                    active_trade = None
                elif bar_high >= active_trade['tp']:
                    trades.append({'time': pd.to_datetime(current_time), 'type': 'BUY', 'result': 'TP', 'pnl': total_profit_pips})
                    active_trade = None
                    
            elif active_trade['type'] == 'SELL':
                # Cek pemicu SL/TP (SELL ditutup pada harga Ask: Bid + Spread)
                ask_high = bar_high + bar_spread * point
                ask_low = bar_low + bar_spread * point
                if ask_high >= active_trade['sl']:
                    trades.append({'time': pd.to_datetime(current_time), 'type': 'SELL', 'result': 'SL', 'pnl': total_loss_pips})
                    active_trade = None
                elif ask_low <= active_trade['tp']:
                    trades.append({'time': pd.to_datetime(current_time), 'type': 'SELL', 'result': 'TP', 'pnl': total_profit_pips})
                    active_trade = None

        # B. CARI SINYAL BARU (Hanya jika tidak ada posisi aktif)
        if active_trade is None:
            # FILTER 1: Jam Rollover (Robot dilarang entri saat spread melebar)
            if is_rollover_arr[i]:
                continue
                
            # FILTER 2: Filter Berita High Impact Historis
            if is_news_blocked_arr[i]:
                continue

            signal = 0
            
            if strategy_name == "A":
                # M5 Trend (EMA 200) - Gunakan indeks i untuk menyamakan dengan iloc[-2] di live trading
                is_trend_up = close_arr[i] > m5_ema200_arr[i]
                is_trend_down = close_arr[i] < m5_ema200_arr[i]
                
                # M1 Crossover (langsung diakses O(1))
                m1_ema_fast_curr = m1_ema9_arr[i]
                m1_ema_med_curr = m1_ema21_arr[i]
                m1_ema_fast_prev = m1_ema9_prev_arr[i]
                m1_ema_med_prev = m1_ema21_prev_arr[i]
                
                m1_cross_up = (m1_ema_fast_prev <= m1_ema_med_prev) and (m1_ema_fast_curr > m1_ema_med_curr)
                m1_cross_down = (m1_ema_fast_prev >= m1_ema_med_prev) and (m1_ema_fast_curr < m1_ema_med_curr)
                
                # M1 Stochastic
                stoch_k = m1_stoch_k_arr[i]
                stoch_d = m1_stoch_d_arr[i]
                stoch_oversold = stoch_k < config.cfg.STO_OVERSOLD or stoch_d < config.cfg.STO_OVERSOLD
                stoch_overbought = stoch_k > config.cfg.STO_OVERBOUGHT or stoch_d > config.cfg.STO_OVERBOUGHT
                
                if is_trend_up and m1_cross_up and stoch_oversold:
                    signal = 1
                elif is_trend_down and m1_cross_down and stoch_overbought:
                    signal = -1
                
            elif strategy_name == "B":
                close_p = close_arr[i]
                high_p = high_arr[i]
                low_p = low_arr[i]
                bb_l = bb_lower_arr[i]
                bb_u = bb_upper_arr[i]
                
                k_val = stoch_k_arr[i]
                d_val = stoch_d_arr[i]
                k_prev = stoch_k_arr[i-1]
                d_prev = stoch_d_arr[i-1]
                
                stoch_up = (k_prev <= d_prev) and (k_val > d_val) and (k_val < config.cfg.STO_OVERSOLD or k_prev < config.cfg.STO_OVERSOLD)
                stoch_down = (k_prev >= d_prev) and (k_val < d_val) and (k_val > config.cfg.STO_OVERBOUGHT or k_prev > config.cfg.STO_OVERBOUGHT)
                
                if (low_p <= bb_l or close_p <= bb_l) and stoch_up:
                    signal = 1
                elif (high_p >= bb_u or close_p >= bb_u) and stoch_down:
                    signal = -1
                    
            elif strategy_name == "C":
                # Metode C Heikin Ashi murni (tanpa filter tren H1 yang lambat)
                is_green_3 = (ha_close_arr[i-2] > ha_open_arr[i-2]) and \
                             (ha_close_arr[i-1] > ha_open_arr[i-1]) and \
                             (ha_close_arr[i] > ha_open_arr[i])
                is_red_3 = (ha_close_arr[i-2] < ha_open_arr[i-2]) and \
                           (ha_close_arr[i-1] < ha_open_arr[i-1]) and \
                           (ha_close_arr[i] < ha_open_arr[i])
                
                no_low_shadow = ha_low_arr[i] >= (ha_open_arr[i] - 1e-6)
                no_up_shadow = ha_high_arr[i] <= (ha_open_arr[i] + 1e-6)
                
                vol_exp = atr_arr[i] > atr_sma_arr[i]
                
                if is_green_3 and no_low_shadow and vol_exp:
                    signal = 1
                elif is_red_3 and no_up_shadow and vol_exp:
                    signal = -1
                    
            elif strategy_name == "D":
                # FVG SMC dengan EMA 200 asli
                is_bullish_fvg = (low_arr[i] > high_arr[i-2]) and (close_arr[i-1] > open_arr[i-1])
                is_bearish_fvg = (high_arr[i] < low_arr[i-2]) and (close_arr[i-1] < open_arr[i-1])
                
                atr_val = atr_arr[i]
                ema_val = m5_ema200_arr[i]
                close_val = close_arr[i]
                
                if is_bullish_fvg and (close_val > ema_val):
                    gap = low_arr[i] - high_arr[i-2]
                    if gap > 0.5 * atr_val:
                        signal = 1
                elif is_bearish_fvg and (close_val < ema_val):
                    gap = low_arr[i-2] - high_arr[i]
                    if gap > 0.5 * atr_val:
                        signal = -1
                        
            elif strategy_name == "E":
                # HMA RSI-2 asli (tanpa filter tren tambahan)
                close_val = close_arr[i]
                hma_val = hma55_arr[i]
                rsi_val = rsi2_arr[i]
                
                if (close_val > hma_val) and (rsi_val < 10):
                    signal = 1
                elif (close_val < hma_val) and (rsi_val > 90):
                    signal = -1

            # C. BUKA POSISI BARU (Dengan SPREAD & ASK/BID RIIL HISTORIS)
            if signal != 0:
                spread_pts = spread_arr[i]
                
                if signal == 1:  # BUY (Entri pada harga Ask = Close/Bid + Spread)
                    entry = close_arr[i] + spread_pts * point
                    sl = entry - (sl_points * point)
                    tp = entry + (tp_points * point) + (commission_points * point)
                    active_trade = {'type': 'BUY', 'entry': entry, 'sl': sl, 'tp': tp, 'entry_spread': spread_pts}
                    
                elif signal == -1:  # SELL (Entri pada harga Bid = Close)
                    entry = close_arr[i]
                    sl = entry + (sl_points * point)
                    tp = entry - (tp_points * point) - (commission_points * point)
                    active_trade = {'type': 'SELL', 'entry': entry, 'sl': sl, 'tp': tp, 'entry_spread': spread_pts}

    # Hitung Performa
    if not trades:
        return {'symbol': symbol, 'strategy': strategy_name, 'total_trades': 0, 'win_rate': 0.0, 'net_profit_pips': 0.0, 'profit_factor': 0.0}

    df_trades = pd.DataFrame(trades)
    total_trades = len(df_trades)
    win_trades = len(df_trades[df_trades['result'] == 'TP'])
    win_rate = (win_trades / total_trades) * 100.0
    net_profit = df_trades['pnl'].sum()
    
    gross_profit = df_trades[df_trades['pnl'] > 0]['pnl'].sum()
    gross_loss = np.abs(df_trades[df_trades['pnl'] < 0]['pnl'].sum())
    profit_factor = gross_profit / (gross_loss + 1e-9)
    
    return {
        'symbol': symbol,
        'strategy': strategy_name,
        'total_trades': total_trades,
        'win_rate': round(win_rate, 2),
        'net_profit_pips': round(net_profit, 1),
        'profit_factor': round(profit_factor, 2)
    }


def run_single_backtest_task(args):
    """
    Worker function untuk menjalankan satu simulasi backtest di proses terpisah.
    """
    symbol, strategy_name, df_main, limit_bars = args
    try:
        return run_duckdb_backtest(symbol, strategy_name, df_main, limit_bars)
    except Exception as e:
        print(f"Error saat backtesting {symbol} - {strategy_name}: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("==================================================")
    print("      MEMULAI MESIN BACKTEST DUCKDB OPTIMIZED     ")
    print("        (PRE-FETCHING, ALIGNMENT & NUMPY)        ")
    print("==================================================")
    
    # Cek kesegaran data dan sinkronisasi otomatis jika usang
    check_and_update_databases()
    
    currencies = ['USD', 'EUR', 'JPY', 'GBP', 'AUD', 'CAD', 'NZD', 'CHF']
    
    # 1. Muat Jendela Waktu Blokir Berita Ekonomi
    news_blocks = load_news_block_times(currencies)
    
    # Untuk backtest cepat, kita batasi 400.000 bar M5 (~5 tahun)
    limit_bars = 400000 
    
    # 2. Pre-process dan cache data untuk setiap simbol
    preprocessed_data = {}
    print(f"\n[Pre-fetch] Memulai pre-fetching dan kalkulasi indikator untuk {len(config.cfg.SYMBOLS)} pair...")
    t_start_fetch = time.time()
    for symbol in config.cfg.SYMBOLS:
        df_main = preprocess_symbol_data(symbol, limit_bars, news_blocks)
        if not df_main.empty:
            preprocessed_data[symbol] = df_main
    print(f"[Pre-fetch] Selesai memuat seluruh data dalam {(time.time() - t_start_fetch):.2f} detik.")
            
    start_backtest = time.time()
    
    # Menyiapkan list tugas untuk multiprocessing (5 strategi: A, B, C, D, E)
    tasks = []
    for symbol in config.cfg.SYMBOLS:
        if symbol not in preprocessed_data:
            continue
        df_main = preprocessed_data[symbol]
        for strat in ["A", "B", "C", "D", "E"]:
            tasks.append((symbol, strat, df_main, limit_bars))
            
    print(f"\n[Multiprocessing] Menjalankan {len(tasks)} simulasi secara paralel...")
    
    results = []
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor() as executor:
        # Jalankan secara paralel menggunakan pool executor
        futures = executor.map(run_single_backtest_task, tasks)
        for res in futures:
            if res:
                results.append(res)
                
    # Buat tabel ringkasan
    print("\n\n==================================================")
    print("          RINGKASAN HASIL BACKTEST DUCKDB         ")
    print("==================================================")
    df_res = pd.DataFrame(results)
    print(df_res.to_string(index=False))
    
    # Simpan hasil ke SQLite (mt5_ops.db)
    import sqlite3
    db_sqlite_path = os.path.join("data", "mt5_ops.db")
    try:
        conn = sqlite3.connect(db_sqlite_path)
        cursor = conn.cursor()
        
        # Buat tabel hasil backtest jika belum ada
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backtest_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                symbol TEXT,
                strategy TEXT,
                total_trades INTEGER,
                win_rate REAL,
                net_profit_pips REAL,
                profit_factor REAL,
                limit_bars INTEGER
            )
        """)
        
        # Masukkan hasil ke dalam tabel
        for res in results:
            cursor.execute("""
                INSERT INTO backtest_results (symbol, strategy, total_trades, win_rate, net_profit_pips, profit_factor, limit_bars)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (res['symbol'], res['strategy'], res['total_trades'], res['win_rate'], res['net_profit_pips'], res['profit_factor'], limit_bars))
            
        conn.commit()
        conn.close()
        print("[Database] Hasil backtest berhasil disimpan ke tabel 'backtest_results' di SQLite (mt5_ops.db).")
    except Exception as e:
        print(f"[Database Error] Gagal menyimpan hasil backtest ke SQLite: {e}")
        
    print(f"Total waktu backtesting: {(time.time() - start_backtest)/60:.2f} menit.")

if __name__ == "__main__":
    main()
