"""
src/results_db.py

Modul database untuk menyimpan semua hasil tuning/backtest ke SQLite.
Config dan live trading membaca parameter terbaik dari sini secara otomatis.
Mendukung penyimpanan per SESI (ASIA, LONDON, LONDON_NY, NEW_YORK).
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'trading_results.db')

# Parameter default jika DB kosong / belum pernah di-tune
DEFAULTS = {
    "EURUSD": {"strategy": "B", "sl": 230, "tp": 360},
    "USDJPY": {"strategy": "D", "sl": 240, "tp": 380},
    "GBPUSD": {"strategy": None, "sl": 150, "tp": 250},
    "AUDUSD": {"strategy": "C", "sl": 170, "tp": 310},
    "USDCAD": {"strategy": "C", "sl": 240, "tp": 180},
    "NZDUSD": {"strategy": None, "sl": 150, "tp": 250},
    "USDCHF": {"strategy": "C", "sl": 250, "tp": 260},
    "EURJPY": {"strategy": "C", "sl": 220, "tp": 340},
    "GBPJPY": {"strategy": "C", "sl": 220, "tp": 270},
    "XAUUSD": {"strategy": None, "sl": 150, "tp": 250},
}

FORCE_DISABLED = {"XAUUSD"}

ALL_SESSIONS = ["ASIA", "LONDON", "LONDON_NY", "NEW_YORK"]


def _get_conn() -> sqlite3.Connection:
    """Buka koneksi ke SQLite, buat tabel jika belum ada, migrasi jika perlu."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Buat tabel dengan kolom session
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tuning_results (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol            TEXT    NOT NULL,
            strategy          TEXT    NOT NULL,
            session           TEXT    NOT NULL DEFAULT 'LONDON_NY',
            sl_points         INTEGER NOT NULL,
            tp_points         INTEGER NOT NULL,
            n_trials          INTEGER DEFAULT 0,
            is_trades         INTEGER DEFAULT 0,
            is_win_rate       REAL    DEFAULT 0.0,
            is_net_profit     REAL    DEFAULT 0.0,
            is_profit_factor  REAL    DEFAULT 0.0,
            oos_trades        INTEGER DEFAULT 0,
            oos_win_rate      REAL    DEFAULT 0.0,
            oos_net_profit    REAL    DEFAULT 0.0,
            oos_profit_factor REAL    DEFAULT 0.0,
            status            TEXT    DEFAULT 'FAILED',
            tuned_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrasi: tambah kolom session jika belum ada (untuk DB lama)
    existing = [r[1] for r in conn.execute("PRAGMA table_info(tuning_results)").fetchall()]
    if "session" not in existing:
        conn.execute("ALTER TABLE tuning_results ADD COLUMN session TEXT NOT NULL DEFAULT 'LONDON_NY'")
        print("[ResultsDB] Migrasi: kolom 'session' ditambahkan ke DB lama.")

    conn.commit()
    return conn


def save_results(results: list, n_trials: int = 100, session: str = "LONDON_NY"):
    """
    Simpan batch hasil tuning ke database dengan label sesi.

    Args:
        results  : List of dict dari tune_all.py
        n_trials : Jumlah trial Optuna yang digunakan
        session  : Nama sesi ('ASIA', 'LONDON', 'LONDON_NY', 'NEW_YORK')
    """
    conn = _get_conn()
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in results:
        rows.append((
            r.get("symbol", ""),
            r.get("strategy", ""),
            session,
            int(r.get("best_sl_points", 150)),
            int(r.get("best_tp_points", 250)),
            n_trials,
            int(r.get("is_trades", 0)),
            float(r.get("is_win_rate", 0.0)),
            float(r.get("is_net_profit", 0.0)),
            float(r.get("is_profit_factor", 0.0)),
            int(r.get("oos_trades", 0)),
            float(r.get("oos_win_rate", 0.0)),
            float(r.get("oos_net_profit", 0.0)),
            float(r.get("oos_profit_factor", 0.0)),
            r.get("status", "FAILED").split(":")[0].strip(),
            now
        ))

    conn.executemany("""
        INSERT INTO tuning_results
            (symbol, strategy, session, sl_points, tp_points, n_trials,
             is_trades, is_win_rate, is_net_profit, is_profit_factor,
             oos_trades, oos_win_rate, oos_net_profit, oos_profit_factor,
             status, tuned_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()
    conn.close()
    print(f"[ResultsDB] {len(rows)} hasil tuning sesi '{session}' disimpan ke database.")


def get_best_config(session: str = None) -> dict:
    """
    Query database dan kembalikan konfigurasi terbaik per symbol.

    Args:
        session : Filter sesi ('ASIA','LONDON','LONDON_NY','NEW_YORK').
                  Jika None → ambil yang terbaik dari SEMUA sesi per symbol.
    Returns:
        dict {symbol: {strategy, sl, tp, oos_net_profit, session, source, ...}}
    """
    config = {}
    conn = None
    try:
        conn = _get_conn()
        if session:
            rows = conn.execute("""
                WITH ranked_results AS (
                    SELECT symbol, strategy, session, sl_points, tp_points,
                           oos_net_profit, oos_profit_factor, oos_win_rate,
                           is_net_profit, n_trials, tuned_at,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY oos_net_profit DESC) as rn
                    FROM tuning_results
                    WHERE status = 'PASSED' AND session = ?
                )
                SELECT symbol, strategy, session, sl_points, tp_points,
                       oos_net_profit, oos_profit_factor, oos_win_rate,
                       is_net_profit, n_trials, tuned_at
                FROM ranked_results
                WHERE rn = 1
                ORDER BY symbol
            """, (session,)).fetchall()
        else:
            rows = conn.execute("""
                WITH ranked_results AS (
                    SELECT symbol, strategy, session, sl_points, tp_points,
                           oos_net_profit, oos_profit_factor, oos_win_rate,
                           is_net_profit, n_trials, tuned_at,
                           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY oos_net_profit DESC) as rn
                    FROM tuning_results
                    WHERE status = 'PASSED'
                )
                SELECT symbol, strategy, session, sl_points, tp_points,
                       oos_net_profit, oos_profit_factor, oos_win_rate,
                       is_net_profit, n_trials, tuned_at
                FROM ranked_results
                WHERE rn = 1
                ORDER BY symbol
            """).fetchall()

        for row in rows:
            sym = row["symbol"]
            if sym in FORCE_DISABLED:
                continue
            config[sym] = {
                "strategy":          row["strategy"],
                "sl":                row["sl_points"],
                "tp":                row["tp_points"],
                "session":           row["session"],
                "oos_net_profit":    round(row["oos_net_profit"], 1),
                "oos_profit_factor": round(row["oos_profit_factor"], 2),
                "oos_win_rate":      round(row["oos_win_rate"], 3),
                "is_net_profit":     round(row["is_net_profit"], 1),
                "n_trials":          row["n_trials"],
                "tuned_at":          row["tuned_at"],
                "source":            "db"
            }
    except Exception as e:
        print(f"[ResultsDB] Gagal baca DB: {e} — menggunakan nilai default.")
    finally:
        if conn:
            conn.close()

    # Isi symbol yang belum ada di DB dengan DEFAULTS
    for sym, defaults in DEFAULTS.items():
        if sym not in config:
            config[sym] = {**defaults, "session": session or "default", "source": "default"}
            if sym in FORCE_DISABLED:
                config[sym]["strategy"] = None

    return config


def get_all_session_configs() -> dict:
    """
    Kembalikan konfigurasi terbaik untuk SETIAP sesi sekaligus.

    Returns:
        dict {session_name: {symbol: {strategy, sl, tp, ...}}}
    """
    return {s: get_best_config(session=s) for s in ALL_SESSIONS}


def get_history(symbol: str = None, strategy: str = None,
                session: str = None, limit: int = 50) -> list:
    """Ambil riwayat tuning dari DB untuk analisis tren."""
    conn = _get_conn()
    query  = "SELECT * FROM tuning_results WHERE 1=1"
    params = []
    if symbol:
        query += " AND symbol = ?"
        params.append(symbol)
    if strategy:
        query += " AND strategy = ?"
        params.append(strategy)
    if session:
        query += " AND session = ?"
        params.append(session)
    query += " ORDER BY tuned_at DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


def print_leaderboard(session: str = None):
    """
    Tampilkan papan peringkat parameter terbaik di terminal.

    Args:
        session : Filter sesi tertentu, atau None untuk tampilkan semua sesi
    """
    sessions_to_show = [session] if session else ALL_SESSIONS
    has_any = False

    for sess in sessions_to_show:
        cfg = get_best_config(session=sess)
        db_entries = {s: c for s, c in cfg.items() if c.get("source") == "db"}
        if not db_entries and session:
            # Sesi spesifik diminta tapi kosong
            print(f"[{sess}] Belum ada hasil tuning. Jalankan: python tune_all.py --session {sess}")
            continue
        if not db_entries:
            continue

        has_any = True
        print(f"\n{'='*72}")
        print(f"  LEADERBOARD SESI: {sess}")
        print(f"{'='*72}")
        print(f"  {'PAIR':<8} {'STRAT':>5} {'SL':>6} {'TP':>6} {'OOS Profit':>11} {'OOS PF':>7} {'Source'}")
        print(f"  {'-'*68}")

        for sym, c in sorted(cfg.items()):
            strat  = c.get("strategy") or "OFF"
            sl     = c.get("sl", "-")
            tp     = c.get("tp", "-")
            oos    = c.get("oos_net_profit", "-")
            pf     = c.get("oos_profit_factor", "-")
            source = c.get("source", "?")
            oos_str = f"+{oos:.1f}" if isinstance(oos, float) else "-"
            pf_str  = f"{pf:.2f}"   if isinstance(pf,  float) else "-"
            print(f"  {sym:<8} {strat:>5} {sl:>6} {tp:>6} {oos_str:>11} {pf_str:>7} [{source}]")

        print(f"{'='*72}")

    if not has_any and not session:
        print("[ResultsDB] Database kosong. Jalankan: python tune_all.py --session ALL")
