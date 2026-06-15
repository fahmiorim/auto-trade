import MetaTrader5 as mt5
import duckdb
import pandas as pd
import os
import sys
from datetime import datetime, timezone, timedelta
from src import config
from src.database import get_duck_connection_rw, get_duck_connection

# ==========================================
# TIMEZONE & DST RULES FOR BROKER (EET/EEST)
# ==========================================
def get_broker_offset_hours(dt: datetime, is_utc: bool = True) -> int:
    """
    Menentukan offset timezone broker (EET/EEST) secara dinamis berdasarkan DST.
    DST mulai Minggu terakhir Maret (UTC+3) s.d. Minggu terakhir Oktober (UTC+2).
    """
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
        
    year = dt.year
    
    # Minggu terakhir Maret
    march_31 = datetime(year, 3, 31)
    dst_start = march_31 - timedelta(days=(march_31.weekday() + 1) % 7)
    dst_start = dst_start.replace(hour=1 if is_utc else 3, minute=0, second=0, microsecond=0)
    
    # Minggu terakhir Oktober
    oct_31 = datetime(year, 10, 31)
    dst_end = oct_31 - timedelta(days=(oct_31.weekday() + 1) % 7)
    dst_end = dst_end.replace(hour=1 if is_utc else 4, minute=0, second=0, microsecond=0)
    
    if dst_start <= dt < dst_end:
        return 3  # EEST (UTC+3)
    else:
        return 2  # EET (UTC+2)

def utc_to_broker(dt_utc: datetime) -> datetime:
    """Mengonversi UTC datetime ke broker datetime dengan offset DST dinamis."""
    offset = get_broker_offset_hours(dt_utc, is_utc=True)
    return dt_utc + timedelta(hours=offset)

# ==========================================
# SINKRONISASI UTAMA
# ==========================================
def sync_symbol_tf(symbol: str, tf_code: int, table_name: str) -> int:
    """
    Sinkronisasi satu pair dan timeframe tertentu.
    Mengembalikan jumlah baris baru yang berhasil ditambahkan.
    """
    # 1. Ambil waktu bar terakhir di database
    con = get_duck_connection()
    try:
        res = con.execute(f"SELECT MAX(time_utc) FROM {table_name} WHERE symbol = ?", [symbol]).fetchone()
        last_time_utc = res[0]
    except Exception as e:
        print(f"  [Error] Gagal membaca data terakhir dari DuckDB: {e}")
        return 0
    finally:
        con.close()
        
    if last_time_utc is None:
        # Jika simbol belum ada, mulai dari 30 hari yang lalu
        last_time_utc = datetime.now(timezone.utc) - timedelta(days=30)
        print(f"  [Info] Simbol {symbol} tidak ditemukan di {table_name}. Memulai fallback dari 30 hari lalu.")

    # Jika timezone-naive, pastikan di-set ke UTC
    if last_time_utc.tzinfo is None:
        last_time_utc = last_time_utc.replace(tzinfo=timezone.utc)

    # 2. Hitung start time (waktu setelah bar terakhir untuk menghindari duplikasi)
    tf_delta = timedelta(minutes=1) if tf_code == mt5.TIMEFRAME_M1 else timedelta(minutes=5)
    start_time_utc = last_time_utc + tf_delta
    
    # 3. Konversi ke waktu broker
    start_broker = utc_to_broker(start_time_utc).replace(tzinfo=None)
    
    # End time adalah waktu sekarang
    now_utc = datetime.now(timezone.utc)
    end_broker = utc_to_broker(now_utc).replace(tzinfo=None)
    
    # Jika waktu mulai lebih besar dari waktu sekarang (karena weekend/market closed), tidak perlu sync
    if start_broker >= end_broker:
        return 0

    # 4. Ambil data dari MT5
    rates = mt5.copy_rates_range(symbol, tf_code, start_broker, end_broker)
    if rates is None or len(rates) == 0:
        return 0
        
    df = pd.DataFrame(rates)
    
    # 5. Konversi waktu broker (unix timestamp) kembali ke UTC
    df['time_utc'] = pd.to_datetime(df['time'], unit='s')
    offsets = df['time_utc'].apply(lambda t: get_broker_offset_hours(t, is_utc=False))
    df['time_utc'] = df['time_utc'] - pd.to_timedelta(offsets, unit='h')
    
    # Tambahkan zona waktu UTC secara eksplisit pada DataFrame agar konsisten
    df['time_utc'] = df['time_utc'].dt.tz_localize('UTC')
    
    # 6. Filter data: hanya ambil yang strictly setelah last_time_utc
    df = df[df['time_utc'] > last_time_utc]
    
    # Filter tambahan untuk memastikan kita tidak mengimpor bar yang sedang berjalan (incomplete)
    df = df[df['time_utc'] <= now_utc - tf_delta]
    
    if df.empty:
        return 0
        
    # 7. Siapkan struktur DataFrame agar persis seperti skema DuckDB
    df['symbol'] = symbol
    df['is_closed'] = True
    if 'real_volume' not in df.columns:
        df['real_volume'] = 0
        
    df_to_insert = df[[
        'symbol', 'time_utc', 'open', 'high', 'low', 'close', 
        'tick_volume', 'spread', 'real_volume', 'is_closed'
    ]].copy()
    
    # Konversi time_utc ke format naive datetime karena DuckDB menyimpan sebagai naive TIMESTAMP
    df_to_insert['time_utc'] = df_to_insert['time_utc'].dt.tz_localize(None)

    # 8. Tulis ke DuckDB
    con = get_duck_connection_rw()
    try:
        con.execute(f"INSERT INTO {table_name} SELECT * FROM df_to_insert")
        inserted_rows = len(df_to_insert)
        return inserted_rows
    except Exception as e:
        print(f"  [Error] Gagal menginsert data ke DuckDB untuk {symbol} {table_name}: {e}")
        return 0
    finally:
        con.close()

def main():
    print("==================================================")
    print("      SINKRONISASI DATABASE DUCKDB LIVE (MT5)     ")
    print("==================================================")
    
    # Inisialisasi MetaTrader 5
    if not mt5.initialize():
        print(f"Gagal menginisialisasi MT5: {mt5.last_error()}")
        return False
        
    print(f"Connected to MT5 broker: {mt5.terminal_info().company if mt5.terminal_info() else 'Unknown'}")
    
    total_added_m1 = 0
    total_added_m5 = 0
    
    try:
        symbols = config.cfg.SYMBOLS
        print(f"Mulai sinkronisasi untuk {len(symbols)} pair: {symbols}")
        
        for symbol in symbols:
            print(f"\n[Processing {symbol}]")
            
            # Pastikan simbol aktif di Market Watch
            if not mt5.symbol_select(symbol, True):
                print(f"  [Warning] Gagal memilih/mengaktifkan simbol {symbol} di Market Watch.")
                continue
                
            # Sync M1
            added_m1 = sync_symbol_tf(symbol, mt5.TIMEFRAME_M1, 'candles_m1')
            total_added_m1 += added_m1
            if added_m1 > 0:
                print(f"  - M1: Berhasil menambahkan {added_m1:,} bar baru.")
            else:
                print(f"  - M1: Sudah up-to-date.")
                
            # Sync M5
            added_m5 = sync_symbol_tf(symbol, mt5.TIMEFRAME_M5, 'candles_m5')
            total_added_m5 += added_m5
            if added_m5 > 0:
                print(f"  - M5: Berhasil menambahkan {added_m5:,} bar baru.")
            else:
                print(f"  - M5: Sudah up-to-date.")
                
        print("\n==================================================")
        print("            RINGKASAN HASIL SINKRONISASI          ")
        print("==================================================")
        print(f"Total baris ditambahkan ke candles_m1 : {total_added_m1:,} bar")
        print(f"Total baris ditambahkan ke candles_m5 : {total_added_m5:,} bar")
        print("==================================================")
        
    finally:
        mt5.shutdown()
        
    return True

if __name__ == "__main__":
    main()
