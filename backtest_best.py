"""
backtest_best.py

Backtest menggunakan parameter terbaik dari trading_results.db.
Support filter per sesi & per periode waktu.

Usage:
    python backtest_best.py                              # semua sesi, OOS
    python backtest_best.py --session ASIA               # sesi Asia saja
    python backtest_best.py --session ALL --period oos   # semua sesi, OOS
    python backtest_best.py --period is                  # semua sesi, IS
"""
import pandas as pd
import time
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from backtest import preprocess_symbol_data, run_duckdb_backtest, load_news_block_times
from tune_all import filter_by_session
from src import config
from src.results_db import get_best_config, ALL_SESSIONS


def run_task(args):
    symbol, strategy, df, sl, tp, limit_bars, session = args
    try:
        res = run_duckdb_backtest(
            symbol=symbol, strategy_name=strategy, df_main=df,
            limit_bars=limit_bars, sl_points=sl, tp_points=tp,
            commission_points=6.0, start_idx=200
        )
        res['symbol']   = symbol
        res['strategy'] = strategy
        res['sl']       = sl
        res['tp']       = tp
        res['session']  = session
        return res
    except Exception as e:
        return {'symbol': symbol, 'strategy': strategy, 'sl': sl, 'tp': tp,
                'session': session, 'total_trades': 0, 'win_rate': 0,
                'net_profit_pips': 0, 'profit_factor': 0, 'error': str(e)}


def print_session_result(results: list, session: str, period_label: str, duration: float):
    """Tampilkan ringkasan hasil backtest untuk satu sesi."""
    if not results:
        print(f"  [Tidak ada hasil untuk sesi {session}]")
        return

    df_res = pd.DataFrame(results)
    profit = df_res[df_res['net_profit_pips'] > 0]
    loss   = df_res[df_res['net_profit_pips'] <= 0]
    total  = df_res['net_profit_pips'].sum()
    sign   = "+" if total >= 0 else ""

    print(f"\n{'='*65}")
    print(f"  SESI: {session} | {period_label}")
    print(f"{'='*65}")
    print(f"  {'PAIR':<8} {'STRAT':>5} {'SL':>5} {'TP':>5} "
          f"{'TRADES':>7} {'WR':>7} {'PF':>6} {'PnL PIPS':>12}")
    print(f"  {'-'*61}")

    df_sorted = df_res.sort_values('net_profit_pips', ascending=False)
    for _, row in df_sorted.iterrows():
        pnl    = row.get('net_profit_pips', 0)
        s      = "+" if pnl >= 0 else ""
        tag    = "[OK]" if pnl > 0 else "[--]"
        print(f"  {tag} {row['symbol']:<7} {row['strategy']:>5} "
              f"{int(row.get('sl',0)):>5} {int(row.get('tp',0)):>5} "
              f"{int(row.get('total_trades',0)):>7} "
              f"{row.get('win_rate',0):>6.1f}% "
              f"{row.get('profit_factor',0):>6.2f} "
              f"{s}{pnl:>10.1f}")

    print(f"  {'-'*61}")
    print(f"  Profit: {len(profit)}/{len(results)} pair | "
          f"Total: {sign}{total:.1f} pips | {duration:.1f} detik")
    print(f"{'='*65}")
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period",  choices=["full", "is", "oos"], default="oos",
                        help="Periode: full=semua, is=2021-24, oos=2025-26 (default: oos)")
    parser.add_argument("--session", default="ALL",
                        choices=["ALL"] + ALL_SESSIONS,
                        help="Sesi: ALL atau spesifik (default: ALL)")
    parser.add_argument("--split-date", type=str, default="2025-01-01",
                        help="Tanggal pemisah In-Sample dan Out-of-Sample (default: 2025-01-01)")
    args = parser.parse_args()

    sessions_to_run = ALL_SESSIONS if args.session == "ALL" else [args.session]
    split_date = args.split_date

    if args.period == "is":
        period_label = f"In-Sample (sebelum {split_date})"
        date_filter  = lambda df: df[df['time'] < split_date].reset_index(drop=True)
    elif args.period == "oos":
        period_label = f"Out-of-Sample (sejak {split_date})"
        date_filter  = lambda df: df[df['time'] >= split_date].reset_index(drop=True)
    else:
        period_label = "Full (Semua Data)"
        date_filter  = lambda df: df

    print("=" * 65)
    print(f"  BACKTEST PER SESI — {period_label}")
    print(f"  Sesi yang diuji: {', '.join(sessions_to_run)}")
    print("=" * 65)

    # Kumpulkan semua pair yang perlu di-fetch
    all_pairs = set()
    session_configs = {}
    for sess in sessions_to_run:
        cfg = get_best_config(session=sess)
        active = {sym: c for sym, c in cfg.items()
                  if c.get("strategy") and c.get("source") == "db"}
        session_configs[sess] = active
        all_pairs.update(active.keys())

    if not all_pairs:
        print("[Error] Tidak ada hasil tuning di DB. Jalankan tune_all.py --session ALL")
        sys.exit(1)

    # Pre-fetch sekali untuk semua pair
    currencies  = ['USD', 'EUR', 'JPY', 'GBP', 'AUD', 'CAD', 'NZD', 'CHF']
    news_blocks = load_news_block_times(currencies)
    limit_bars  = 400000

    print(f"\n[Pre-fetch] Memuat data {len(all_pairs)} pair unik...")
    t0 = time.time()
    preprocessed = {}
    for sym in sorted(all_pairs):
        df = preprocess_symbol_data(sym, limit_bars, news_blocks)
        if not df.empty:
            df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)
            preprocessed[sym] = df
    print(f"[Pre-fetch] Selesai dalam {time.time()-t0:.1f} detik.\n")

    # Build tasks per sesi
    all_tasks = []
    for sess in sessions_to_run:
        active = session_configs[sess]
        for sym, cfg in active.items():
            if sym not in preprocessed:
                continue
            df = preprocessed[sym].copy()
            df = date_filter(df)                    # filter periode (IS/OOS/full)
            df = filter_by_session(df, sess)        # filter jam sesi
            if df.empty or len(df) < 100:
                continue
            all_tasks.append((sym, cfg['strategy'], df,
                              cfg['sl'], cfg['tp'], limit_bars, sess))

    print(f"[Backtest] Total {len(all_tasks)} task di {len(sessions_to_run)} sesi — jalankan paralel...\n")

    # Jalankan semua paralel
    raw_results = []
    t1 = time.time()
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(run_task, t): t for t in all_tasks}
        done = 0
        for future in as_completed(futures):
            res = future.result()
            raw_results.append(res)
            done += 1
            pnl  = res.get('net_profit_pips', 0)
            sign = "+" if pnl >= 0 else ""
            tag  = "[PROFIT]" if pnl > 0 else "[LOSS]  "
            print(f"  [{done:02d}/{len(all_tasks)}] {tag} "
                  f"{res.get('session','?'):<10} {res.get('symbol','?'):<7} "
                  f"Strat-{res.get('strategy','?')} | "
                  f"PnL={sign}{pnl:.1f} pips | "
                  f"Trades={res.get('total_trades',0)}")

    total_duration = time.time() - t1

    # Kelompokkan per sesi dan tampilkan
    grand_total = 0.0
    for sess in sessions_to_run:
        sess_results = [r for r in raw_results if r.get('session') == sess]
        t = print_session_result(sess_results, sess, period_label,
                                 total_duration / len(sessions_to_run))
        if t:
            grand_total += t

    # Grand total
    print(f"\n{'='*65}")
    print(f"  GRAND TOTAL — Semua Sesi | {period_label}")
    print(f"{'='*65}")
    sign = "+" if grand_total >= 0 else ""
    print(f"  Total Pip Gabungan : {sign}{grand_total:.1f} pips")
    print(f"  Total Pair Diuji   : {len(raw_results)}")
    profit_count = sum(1 for r in raw_results if r.get('net_profit_pips', 0) > 0)
    print(f"  Pair Profit        : {profit_count}/{len(raw_results)}")
    print(f"  Waktu Total        : {total_duration:.1f} detik")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
