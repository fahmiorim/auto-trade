import requests
import sqlite3
import pandas as pd
import sys
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime, timezone
from src import config

def main():
    print("==================================================")
    print("      SINKRONISASI BERITA EKONOMI LIVE (SQLITE)   ")
    print("==================================================")
    
    db_path = r"data/mt5_ops.db"
    
    # 1. Ambil data dari feed Forex Factory JSON
    url = config.cfg.ECONOMIC_CALENDAR_URL
    print(f"Mengunduh feed berita dari: {url}...")
    try:
        response = requests.get(url, verify=False, timeout=10)
        if response.status_code != 200:
            print(f"[Error] Gagal mengunduh feed berita. Status code: {response.status_code}")
            return False
        calendar = response.json()
        if not isinstance(calendar, list):
            print(f"[Error] Format feed berita tidak valid: Diharapkan list, mendapat {type(calendar)}")
            return False
    except Exception as e:
        print(f"[Error] Gagal mengunduh feed berita: {e}")
        return False
        
    print(f"Berhasil mengunduh {len(calendar)} berita untuk minggu ini.")
    
    # 2. Hubungkan ke database SQLite dalam mode read-write
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        added_count = 0
        skipped_count = 0
        fetched_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        
        # 3. Proses dan masukkan data berita
        for event in calendar:
            title = event.get("title")
            country = event.get("country")
            date_str = event.get("date")
            impact = event.get("impact")
            forecast = event.get("forecast")
            previous = event.get("previous")
            
            if not date_str or not title or not country:
                continue
                
            # Skip events with no time component (e.g. 'All Day' events)
            if ':' not in date_str:
                continue
                
            try:
                # Konversi tanggal ISO 8601 ke UTC datetime string
                dt = pd.to_datetime(date_str)
                if dt.tzinfo is None:
                    dt_utc = dt.replace(tzinfo=timezone.utc)
                else:
                    dt_utc = dt.tz_convert('UTC')
                time_utc = dt_utc.strftime('%Y-%m-%d %H:%M:%S')
                
                # Cek duplikasi di database
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM economic_calendar 
                    WHERE time_utc = ? AND country = ? AND event = ?
                    """,
                    (time_utc, country, title)
                )
                exists = cursor.fetchone()[0] > 0
                
                if not exists:
                    # Insert data berita baru
                    cursor.execute(
                        """
                        INSERT INTO economic_calendar (time_utc, country, event, impact, forecast, previous, source, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (time_utc, country, title, impact, forecast, previous, 'ForexFactory', fetched_at)
                    )
                    added_count += 1
                else:
                    skipped_count += 1
                    
            except Exception as e:
                print(f"  [Warning] Gagal memproses berita '{title}': {e}")
                continue
                
        # Commit seluruh transaksi
        conn.commit()
        
    except Exception as e:
        print(f"[Error] Gagal memproses database SQLite: {e}")
        return False
    finally:
        if conn:
            conn.close()
    
    print("\n==================================================")
    print("            RINGKASAN HASIL SINKRONISASI          ")
    print("==================================================")
    print(f"Berita Baru Ditambahkan : {added_count:,} data")
    print(f"Berita Lama Dilewati    : {skipped_count:,} data")
    print("==================================================")
    return True

if __name__ == "__main__":
    main()
