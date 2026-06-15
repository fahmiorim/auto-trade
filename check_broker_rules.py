"""
Cek semua aturan broker untuk setiap pair yang aktif.
Jalankan saat MT5 terhubung: python check_broker_rules.py
"""
import MetaTrader5 as mt5
from src.results_db import get_best_config

if not mt5.initialize():
    print("Gagal konek ke MT5! Buka MetaTrader5 terlebih dahulu.")
    exit()

# Load best configs dari DB (otomatis fallback ke defaults jika DB kosong)
best_config = get_best_config()
SYMBOLS = ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD",
           "NZDUSD", "USDCHF", "EURJPY", "GBPJPY", "XAUUSD"]

print("=" * 90)
print(f"  {'PAIR':<8} {'STOPS_LVL':>9} {'SPREAD':>8} {'SL_KITA':>8} {'TP_KITA':>8} {'MIN_LOT':>8} {'SOURCE':<10} {'STATUS'}")
print("=" * 90)

for sym in SYMBOLS:
    info = mt5.symbol_info(sym)
    if info is None:
        print(f"  {sym:<8} Tidak tersedia di broker ini")
        continue

    stops_level   = info.trade_stops_level   # Jarak minimum SL/TP dari harga (points)
    spread        = info.spread              # Spread saat ini (points)
    min_lot       = info.volume_min
    
    cfg = best_config.get(sym, {})
    our_sl = cfg.get("sl", 150)
    our_tp = cfg.get("tp", 250)
    source = cfg.get("source", "default")
    session = cfg.get("session", "default")
    source_label = f"{source}({session})"

    # Cek apakah SL/TP kita memenuhi stops_level broker
    sl_ok = our_sl >= stops_level
    tp_ok = our_tp >= stops_level
    status = "[OK]" if (sl_ok and tp_ok) else "[DANGER]"

    if not sl_ok:
        status += f" | SL terlalu dekat! min={stops_level}"
    if not tp_ok:
        status += f" | TP terlalu dekat! min={stops_level}"

    print(f"  {sym:<8} {stops_level:>9} {spread:>8} {our_sl:>8} {our_tp:>8} {min_lot:>8} {source_label:<10} {status}")

print("=" * 90)
print("\nKeterangan:")
print("  STOPS_LVL = Jarak minimum antara harga entry dan SL/TP (points) -- aturan broker")
print("  SPREAD    = Spread saat ini (points)")
print("  SL/TP KITA = Nilai aktif dari hasil tuning Optuna WFO atau default")
print("  [DANGER]  = Broker akan MENOLAK order! SL atau TP terlalu dekat dari harga")
mt5.shutdown()
