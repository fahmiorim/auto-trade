import pandas as pd
import numpy as np
import argparse
import os
import sys
import time
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

from backtest import preprocess_symbol_data, run_duckdb_backtest, load_news_block_times
from src import config
from src.results_db import save_results, print_leaderboard


def run_tune_task(args):
    """
    Worker function: dijalankan di proses terpisah.
    Menjalankan Optuna WFO untuk satu kombinasi symbol-strategi-sesi.
    """
    symbol, strategy_name, df_is, df_oos, n_trials, limit_bars = args

    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            sl_val = trial.suggest_int('sl_points', 100, 250, step=10)
            tp_val = trial.suggest_int('tp_points', 150, 400, step=10)
            res = run_duckdb_backtest(
                symbol=symbol, strategy_name=strategy_name, df_main=df_is,
                limit_bars=limit_bars, sl_points=sl_val, tp_points=tp_val,
                commission_points=6.0, start_idx=200
            )
            if res.get('total_trades', 0) < 10:
                return -9999.0
            return res.get('net_profit_pips', 0.0)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials)
        best_params = study.best_params

        res_is = run_duckdb_backtest(
            symbol=symbol, strategy_name=strategy_name, df_main=df_is,
            limit_bars=limit_bars, sl_points=best_params['sl_points'],
            tp_points=best_params['tp_points'], commission_points=6.0, start_idx=200
        )
        res_oos = run_duckdb_backtest(
            symbol=symbol, strategy_name=strategy_name, df_main=df_oos,
            limit_bars=limit_bars, sl_points=best_params['sl_points'],
            tp_points=best_params['tp_points'], commission_points=6.0, start_idx=0
        )

        passed = res_oos['net_profit_pips'] > 0 and res_is['net_profit_pips'] > 0
        return {
            "symbol":           symbol,
            "strategy":         strategy_name,
            "best_sl_points":   best_params['sl_points'],
            "best_tp_points":   best_params['tp_points'],
            "is_trades":        res_is.get('total_trades', 0),
            "is_win_rate":      res_is.get('win_rate', 0.0),
            "is_net_profit":    res_is.get('net_profit_pips', 0.0),
            "is_profit_factor": res_is.get('profit_factor', 0.0),
            "oos_trades":       res_oos.get('total_trades', 0),
            "oos_win_rate":     res_oos.get('win_rate', 0.0),
            "oos_net_profit":   res_oos.get('net_profit_pips', 0.0),
            "oos_profit_factor":res_oos.get('profit_factor', 0.0),
            "status":           "PASSED" if passed else "FAILED",
        }

    except Exception as e:
        import traceback
        return {
            "symbol": symbol, "strategy": strategy_name,
            "best_sl_points": 150, "best_tp_points": 250,
            "is_trades": 0, "is_win_rate": 0.0, "is_net_profit": 0.0, "is_profit_factor": 0.0,
            "oos_trades": 0, "oos_win_rate": 0.0, "oos_net_profit": 0.0, "oos_profit_factor": 0.0,
            "status": f"ERROR: {str(e)}"
        }


def filter_by_session(df: pd.DataFrame, session: str) -> pd.DataFrame:
    """
    Filter DataFrame hanya untuk jam-jam dalam sesi tertentu (berdasarkan UTC).
    NEW_YORK melewati tengah malam UTC, ditangani khusus.
    """
    if session == "ALL":
        return df

    utc = config.cfg.SESSION_HOURS_UTC.get(session)
    if utc is None:
        print(f"[Warning] Sesi '{session}' tidak dikenal, gunakan semua data.")
        return df

    hour = pd.to_datetime(df['time']).dt.hour

    if utc["start"] < utc["end"]:
        mask = (hour >= utc["start"]) & (hour < utc["end"])
    else:
        # Melewati tengah malam (misal NEW_YORK: 16:00-21:00 UTC)
        mask = (hour >= utc["start"]) | (hour < utc["end"])

    filtered = df[mask].copy().reset_index(drop=True)
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Tuning Massal Semua Pair & Strategi per Sesi (Optuna + WFO, Full Parallel)"
    )
    parser.add_argument("--trials",  type=int, default=100,
                        help="Jumlah trial per kombinasi Optuna (default: 100)")
    parser.add_argument("--session", type=str, default="ALL",
                        choices=["ALL", "ASIA", "LONDON", "LONDON_NY", "NEW_YORK"],
                        help="Sesi yang di-tune (default: ALL = semua sesi)")
    parser.add_argument("--split-date", type=str, default="2025-01-01",
                        help="Tanggal pemisah In-Sample dan Out-of-Sample (default: 2025-01-01)")
    args = parser.parse_args()
    n_trials     = args.trials
    target_session = args.session
    split_date   = args.split_date


    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        print("[Error] Optuna tidak ditemukan! Install dengan: pip install optuna")
        sys.exit(1)

    n_workers = os.cpu_count() or 4
    sessions_to_run = (
        ["ASIA", "LONDON", "LONDON_NY", "NEW_YORK"]
        if target_session == "ALL"
        else [target_session]
    )

    print("=" * 60)
    print("  TUNING MASSAL PER SESI (OPTUNA + WFO, PARALLEL)")
    print(f"  Sesi    : {', '.join(sessions_to_run)}")
    print(f"  Trials  : {n_trials} per kombinasi")
    print(f"  CPU     : {n_workers} core (semua)")
    print("=" * 60)

    # Pre-fetch data semua pair (sekali saja untuk semua sesi)
    currencies  = ['USD', 'EUR', 'JPY', 'GBP', 'AUD', 'CAD', 'NZD', 'CHF']
    news_blocks = load_news_block_times(currencies)
    limit_bars  = 400000

    print(f"\n[Pre-fetch] Menarik data historis untuk {len(config.cfg.SYMBOLS)} pair...")
    t_fetch = time.time()
    preprocessed_data = {}
    for symbol in config.cfg.SYMBOLS:
        df = preprocess_symbol_data(symbol, limit_bars, news_blocks)
        if not df.empty:
            df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)
            preprocessed_data[symbol] = df
    print(f"[Pre-fetch] Selesai dalam {time.time()-t_fetch:.1f} detik.\n")

    grand_total_tasks = 0
    t_grand_start     = time.time()

    for session in sessions_to_run:
        eligible_pairs = config.cfg.SESSION_ELIGIBLE_PAIRS.get(session, config.cfg.SYMBOLS)
        strategies_list = ["A", "B", "C", "D", "E"]

        print(f"\n{'='*60}")
        print(f"  SESI: {session} — Pair: {', '.join(eligible_pairs)}")
        print(f"{'='*60}")

        # Siapkan tasks untuk sesi ini
        tasks = []
        for symbol in eligible_pairs:
            if symbol not in preprocessed_data:
                continue
            df_main = preprocessed_data[symbol]

            # Filter data per sesi
            df_is_full  = df_main[df_main['time'] < split_date].copy().reset_index(drop=True)
            df_oos_full = df_main[df_main['time'] >= split_date].copy().reset_index(drop=True)

            df_is  = filter_by_session(df_is_full,  session)
            df_oos = filter_by_session(df_oos_full, session)

            if df_is.empty or df_oos.empty or len(df_is) < 1000:
                print(f"  [Skip] {symbol}: data sesi {session} terlalu sedikit ({len(df_is)} bar)")
                continue

            print(f"  {symbol}: IS={len(df_is):,} bar | OOS={len(df_oos):,} bar")
            for strat in strategies_list:
                tasks.append((symbol, strat, df_is, df_oos, n_trials, limit_bars))

        if not tasks:
            print(f"  [Skip] Tidak ada task untuk sesi {session}.")
            continue

        total_tasks = len(tasks)
        grand_total_tasks += total_tasks
        print(f"\n[{session}] Mengirim {total_tasks} tugas ke {n_workers} core...")

        results   = []
        completed = 0
        t_start   = time.time()

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            future_to_task = {executor.submit(run_tune_task, task): task for task in tasks}
            for future in as_completed(future_to_task):
                res = future.result()
                results.append(res)
                completed += 1
                elapsed   = time.time() - t_start
                remaining = (total_tasks - completed) * (elapsed / completed) if completed > 0 else 0
                print(f"  [{completed:02d}/{total_tasks}] {res['symbol']:7s} Strat-{res['strategy']} | "
                      f"SL={res.get('best_sl_points','?')} TP={res.get('best_tp_points','?')} | "
                      f"OOS: {res.get('oos_net_profit', 0):+.1f} pips | "
                      f"{res['status']} | ETA: {remaining/60:.1f} mnt")

        # Simpan hasil sesi ini ke DB
        save_results(results, n_trials=n_trials, session=session)

        # Ringkasan per sesi
        df_res = pd.DataFrame(results)
        passed = len(df_res[df_res['status'] == 'PASSED'])
        failed = len(df_res[df_res['status'] == 'FAILED'])
        print(f"\n[{session}] Selesai: {passed} PASSED, {failed} FAILED "
              f"dalam {(time.time()-t_start)/60:.1f} menit")

    # Tampilkan leaderboard lengkap semua sesi
    total_duration = time.time() - t_grand_start
    print(f"\n\n{'='*60}")
    print(f"  SEMUA SESI SELESAI — Total: {total_duration/60:.1f} menit")
    print(f"  {grand_total_tasks} kombinasi diuji")
    print(f"{'='*60}\n")

    for session in sessions_to_run:
        print_leaderboard(session=session)


if __name__ == "__main__":
    main()
