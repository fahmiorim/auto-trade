import duckdb
import sqlite3
import pandas as pd
import os

DB_DUCK_PATH = os.path.join("data", "mt5_data.db")
DB_SQLITE_PATH = os.path.join("data", "mt5_ops.db")

def get_duck_connection():
    """Mengembalikan koneksi read-only ke database DuckDB."""
    return duckdb.connect(DB_DUCK_PATH, read_only=True)

def get_duck_connection_rw():
    """Mengembalikan koneksi read-write ke database DuckDB."""
    return duckdb.connect(DB_DUCK_PATH, read_only=False)

def get_sqlite_connection():
    """Mengembalikan koneksi read-only ke database SQLite."""
    # Membuka SQLite dalam mode read-only menggunakan URI
    normalized_path = DB_SQLITE_PATH.replace('\\', '/')
    db_uri = f"file:{normalized_path}?mode=ro"
    return sqlite3.connect(db_uri, uri=True)

def fetch_db_rates_m5(symbol: str, limit: int = 50000) -> pd.DataFrame:
    """
    Mengambil data candlestick M5 dari DuckDB.
    """
    con = get_duck_connection()
    query = """
        SELECT time, open, high, low, close, tick_volume, spread
        FROM (
            SELECT 
                time_utc AS time, 
                open, 
                high, 
                low, 
                close, 
                tick_volume, 
                spread 
            FROM candles_m5 
            WHERE symbol = ? 
            ORDER BY time_utc DESC 
            LIMIT ?
        )
        ORDER BY time ASC
    """
    try:
        df = con.execute(query, [symbol, limit]).fetchdf()
        # Konversi kolom time ke datetime jika belum
        df['time'] = pd.to_datetime(df['time'])
        return df
    except Exception as e:
        print(f"[Database] Gagal mengambil data M5 untuk {symbol}: {e}")
        return pd.DataFrame()
    finally:
        con.close()

def fetch_db_rates_m1(symbol: str, limit: int = 250000) -> pd.DataFrame:
    """
    Mengambil data candlestick M1 dari DuckDB.
    """
    con = get_duck_connection()
    query = """
        SELECT time, open, high, low, close, tick_volume, spread
        FROM (
            SELECT 
                time_utc AS time, 
                open, 
                high, 
                low, 
                close, 
                tick_volume, 
                spread 
            FROM candles_m1 
            WHERE symbol = ? 
            ORDER BY time_utc DESC 
            LIMIT ?
        )
        ORDER BY time ASC
    """
    try:
        df = con.execute(query, [symbol, limit]).fetchdf()
        df['time'] = pd.to_datetime(df['time'])
        return df
    except Exception as e:
        print(f"[Database] Gagal mengambil data M1 untuk {symbol}: {e}")
        return pd.DataFrame()
    finally:
        con.close()

def fetch_db_economic_calendar() -> pd.DataFrame:
    """
    Mengambil seluruh histori kalender ekonomi High Impact dari SQLite.
    """
    con = get_sqlite_connection()
    query = """
        SELECT time_utc, country, event, impact 
        FROM economic_calendar 
        WHERE impact = 'High' AND time_utc IS NOT NULL
    """
    try:
        df = pd.read_sql_query(query, con)
        df['time_utc'] = pd.to_datetime(df['time_utc'])
        return df
    except Exception as e:
        print(f"[Database] Gagal mengambil kalender berita dari SQLite: {e}")
        return pd.DataFrame()
    finally:
        con.close()
