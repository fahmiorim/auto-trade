# 🤖 Robot Trading MT5 Autopilot — Sesi-Based Tuning & WFO

Proyek ini adalah sistem **robot trading forex otomatis** untuk MetaTrader 5 (MT5) berbasis Python. Robot menggunakan metode **Walk-Forward Optimization (WFO)** dengan **Optuna** untuk mencari parameter optimal (Stop Loss, Take Profit, dan Strategi) secara dinamis per **sesi perdagangan global** (ASIA, LONDON, LONDON_NY, NEW_YORK).

---

## 📋 Daftar Isi

- [🖥️ Persyaratan Sistem](#️-persyaratan-sistem)
- [⚡ Instalasi Cepat](#-instalasi-cepat)
- [🗺️ Arsitektur Sistem](#️-arsitektur-sistem)
- [📁 Struktur File Proyek](#-struktur-file-proyek)
- [⚙️ Konfigurasi](#️-konfigurasi)
- [📈 Lima Strategi Trading](#-lima-strategi-trading)
- [⏰ Sesi Trading & Pair Eligible](#-sesi-trading--pair-eligible)
- [🔄 Alur Kerja Operasional](#-alur-kerja-operasional)
- [🧪 Testing](#-testing)
- [📊 Hasil Verifikasi OOS](#-hasil-verifikasi-oos)
- [🛠️ Troubleshooting](#️-troubleshooting)
- [🚀 Roadmap](#-roadmap)

---

## 🖥️ Persyaratan Sistem

### Minimum
- **OS**: Windows 10 / Windows Server 2019+
- **Python**: 3.10 – 3.14
- **MetaTrader 5**: Terminal MT5 terinstall dan akun (demo/live) aktif
- **RAM**: 8 GB (untuk tuning paralel)
- **Storage**: 1 GB free (data historis)

### Recommended
- **OS**: Windows 11
- **Python**: 3.14
- **RAM**: 16 GB+
- **CPU**: 8+ cores (tuning paralel Optuna)
- **MT5**: Akun Finex / broker dengan **5-digit pricing** dan **hedging mode**

---

## ⚡ Instalasi Cepat

### 1. Clone / Download Project

```powershell
cd C:\laragon\www\auto-trade
```

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Install & Buka MetaTrader 5

1. Download & install [MetaTrader 5](https://www.metatrader5.com/)
2. Login ke akun broker (demo/live)
3. **Enable Algo Trading**: `Tools → Options → Expert Advisors → Allow Automated Trading`
4. Pastikan symbol pairs (EURUSD, USDJPY, dll.) tampil di **Market Watch**

### 4. Verifikasi Instalasi

```powershell
python -m pytest tests/ -v
```

Semua test harus **PASSED** (102 tests, ~0.6 detik).

---

## 🗺️ Arsitektur Sistem

```
MT5 (Broker Finex / Demo)
      │
      ▼
update_db.py ──────────→ data/mt5_data.db       [DuckDB]  ← Data M1 & M5 historis
                                   │
                                   ▼
                          tune_all.py             [Optuna WFO + Paralel Multi-Core]
                           │     │
                           │     ├─ Filter data per sesi (UTC)
                           │     └─ 4.600+ backtest internal per run
                           │
                           ▼
                  data/trading_results.db        [SQLite]  ← Semua hasil tuning
                           │
                     ┌─────┴──────────────┐
                     ▼                    ▼
                src/config.py        src/results_db.py
                (baca otomatis)      (query best per sesi)
                     │
                ┌────┴────────────┐
                ▼                 ▼
           main.py           backtest_best.py
          (live 24 jam)      (verifikasi)
               │
               ├─ detect sesi aktif (WIB)
               ├─ cek market open (weekend/maintenance/rollover)
               ├─ risk check (daily loss limit, consecutive losses)
               └─ process_symbol() → buka order dengan parameter sesi aktif
```

---

## 📁 Struktur File Proyek

```
auto-trade/
│
├── main.py                    ← Entry point robot live trading (session-aware)
├── backtest.py                ← Mesin backtest vektorisasi NumPy + DuckDB
├── backtest_best.py           ← Backtest verifikasi parameter terbaik dari DB
├── tune_all.py                ← Tuning massal Optuna WFO per sesi (paralel)
├── update_db.py               ← Update data historis dari MT5 ke DuckDB
├── update_news.py             ← Update kalender berita ekonomi ke SQLite
├── check_broker_rules.py      ← Validasi SL/TP terhadap stops_level broker
├── gui.py                     ← GUI Dashboard Desktop (CustomTkinter)
├── requirements.txt           ← Dependencies Python
│
├── src/
│   ├── config.py              ← Dataclass konfigurasi + baca DB per sesi
│   ├── results_db.py          ← CRUD SQLite untuk hasil tuning
│   ├── strategies.py          ← 5 strategi (A–E): indikator & sinyal
│   ├── risk_manager.py        ← Kalkulasi lot, daily loss & consecutive loss tracker
│   ├── executor.py            ← Eksekusi order MT5 (buka, modifikasi, tutup)
│   ├── data_fetcher.py        ← Ambil data realtime M1/M5 dari terminal MT5
│   ├── database.py            ← Query DuckDB/SQLite (candle & berita)
│   └── news_filter.py         ← Blokir trading 30 menit sebelum/sesudah berita
│
├── tests/
│   ├── test_indicators.py     ← Test indikator teknikal (EMA, Stoch, BB, dll.)
│   ├── test_strategies.py     ← Test 5 strategi (A–E) dengan data dummy
│   ├── test_risk_manager.py   ← Test lot, broker stops, daily loss tracker
│   └── test_executor.py       ← Test order execution dengan mocked MT5
│
└── data/
    ├── mt5_data.db            ← Data historis M1 & M5 (DuckDB)
    ├── trading_results.db     ← Hasil tuning per sesi (SQLite)
    └── mt5_ops.db             ← Kalender berita ekonomi (SQLite)
```

---

## ⚙️ Konfigurasi

Semua konfigurasi ada di `src/config.py` menggunakan **dataclass** dengan type hints.

### Konfigurasi Dasar

| Parameter | Default | Deskripsi |
|:---|---:|:---|
| `RISK_PERCENT` | `0.01` (1%) | Risiko per transaksi dari saldo |
| `MAGIC_NUMBER` | `20260613` | ID unik order robot di MT5 |
| `SLIPPAGE` | `10` | Toleransi slippage (points) |
| `STO_OVERSOLD` | `20` | Batas Stochastic oversold |
| `STO_OVERBOUGHT` | `80` | Batas Stochastic overbought |
| `NEWS_BLOCK_BEFORE` | `30` | Menit sebelum berita (block) |
| `NEWS_BLOCK_AFTER` | `30` | Menit sesudah berita (block) |

### Cara Mengubah

```python
# src/config.py
cfg.RISK_PERCENT = 0.02      # Ubah risiko jadi 2%
cfg.STO_OVERSOLD = 30        # Ubah batas oversold jadi 30
```

### Konfigurasi Dinamis (Dari Database)

Parameter **SL/TP** dan **Strategi** dibaca otomatis dari `trading_results.db` per sesi:

```python
# main.py — otomatis, tidak perlu diubah manual
strat_name = config.get_session_strategy(symbol, session)
sl_tp      = config.get_session_sl_tp(symbol, session)
```

### Risk Management (Daily Loss & Consecutive Losses)

Di `src/risk_manager.py`:

| Parameter | Default | Deskripsi |
|:---|---:|:---|
| `max_loss_percent` | `5%` | Stop trading jika loss harian >5% |
| `max_consecutive` | `3` | Stop trading jika 3 loss beruntun |

---

## 📈 Lima Strategi Trading (`src/strategies.py`)

| ID | Nama Strategi | Indikator | Timeframe | Karakteristik |
|:---:|:---|---|:---:|:---|
| **A** | Triple EMA + Stochastic | EMA (9,21,200) + Stoch (5,3,3) | M1 + M5 | Trend-following dengan konfirmasi multi-timeframe |
| **B** | Bollinger Bands + Stoch | BB (20,2.0) + Stochastic (5,3,3) | M5 | Mean Reversion di pasar sideway |
| **C** | Heikin Ashi + ATR | HA candles + ATR (14) | M5 | Trend following dengan noise minimum |
| **D** | FVG / SMC | Fair Value Gap + EMA 200 | M5 | Smart Money Concepts, cari imbalance harga |
| **E** | HMA + RSI Extreme | Hull MA (55) + RSI (2) | M5 | Mean Reversion agresif, pullback ekstrim |

---

## ⏰ Sesi Trading & Pair Eligible

| Sesi | Jam WIB | Jam UTC | Pair |
|:---|:---:|:---:|:---|
| **ASIA** | 09:00–15:00 | 02:00–08:00 | USDJPY, EURJPY, GBPJPY, AUDUSD, NZDUSD |
| **LONDON** | 15:00–20:00 | 08:00–13:00 | EURUSD, GBPUSD, USDCHF, EURJPY, GBPJPY, USDCAD |
| **LONDON_NY** | 20:00–23:00 | 13:00–16:00 | EURUSD, USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF, EURJPY, GBPJPY |
| **NEW_YORK** | 23:00–03:45 | 16:00–21:00 | EURUSD, GBPUSD, USDCAD, USDJPY, USDCHF, AUDUSD |

> ⚠️ **NEW_YORK** melewati tengah malam WIB. Logika perbandingan jam menggunakan format **OR** (`hour >= start OR hour < end`).

---

## 🔄 Alur Kerja Operasional

### Quick Start (Pertama Kali)

```powershell
# 1. Update data harga historis dari MT5
python update_db.py

# 2. Update kalender berita ekonomi
python update_news.py

# 3. Tuning parameter Optuna (butuh waktu ~30-60 menit)
python tune_all.py --trials 100 --session ALL

# 4. Verifikasi parameter
python backtest_best.py

# 5. Jalankan robot live trading
python main.py
```

### Menggunakan GUI Desktop

```powershell
python gui.py
```

Fitur GUI:
- **Start/Stop Robot** — tombol kontrol
- **Dashboard** — balance, equity, margin, sesi aktif, risk status
- **Active Positions** — lihat & tutup posisi manual
- **System Console** — log real-time
- **Sync** — update DB harga & berita dari GUI
- **Run Backtest** — verifikasi WFO dari GUI

### Jadwal Rutin

| Frekuensi | Tugas | Perintah |
|:---|---:|:---|
| **Harian** | Jalankan robot | `python main.py` atau via GUI |
| **Mingguan** (Senin) | Update data harga | `python update_db.py` |
| **Bulanan** | Re-tuning parameter | `python tune_all.py --trials 100 --session ALL` |
| **Saat perlu** | Update berita | `python update_news.py` |

### Checklist Sebelum Live Trading

- [ ] 1. Buka MT5, login akun, **Algo Trading ON**
- [ ] 2. `python update_db.py` — data historis terbaru
- [ ] 3. `python tune_all.py --session ALL` — parameter optimal
- [ ] 4. `python check_broker_rules.py` — SL/TP aman untuk broker
- [ ] 5. `python main.py` — robot berjalan

---

## 🧪 Testing

### Menjalankan Semua Test

```powershell
python -m pytest tests/ -v
```

Hasil: **102 tests, ~0.6 detik, 100% PASS**.

### Test per Modul

```powershell
# Indikator teknikal (EMA, Stochastic, BB, ATR, WMA, HMA, RSI)
python -m pytest tests/test_indicators.py -v

# 5 Strategi trading (A–E)
python -m pytest tests/test_strategies.py -v

# Risk manager (lot, broker stops, daily loss tracker)
python -m pytest tests/test_risk_manager.py -v

# Executor (order execution dengan mocked MT5)
python -m pytest tests/test_executor.py -v
```

### Test Coverage

| Modul | Test | Cakupan |
|:---|:---:|:---|
| Indikator | 17 | EMA, Stochastic, BB, ATR, WMA, HMA, RSI |
| Strategi A | 6 | BUY, SELL, no signal, data kurang (M1/M5), empty |
| Strategi B–E | 5 each | BUY, SELL, no signal, data kurang, empty |
| Risk Manager | 16 | Lot, broker stops, SL/TP, daily loss, consecutive loss, track positions |
| Executor | 25 | Filling mode, market order, close position, active positions, modify SL |

### Catatan untuk Test

- Semua fungsi **MetaTrader5** di-mock — test bisa jalan **tanpa koneksi MT5**
- Data dummy deterministik — hasil test **100% reproducible**
- Test **tidak menyentuh database** — aman dijalankan kapan saja

---

## 📊 Hasil Verifikasi Final OOS (2025–2026)

### Ringkasan

| Metrik | Nilai |
|:---|---:|
| **Pair Profit** | **25/25 (100%)** |
| **Grand Total Pips** | **+21.784,0** |
| **Sesi Terbaik** | ASIA (+5.870,3 pips) |
| **Strategi Terbaik** | C (Heikin Ashi + ATR) |

### Performa per Sesi

#### ASIA
| Pair | Strat | SL | TP | Trades | WR | PF | PnL |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|---:|
| GBPJPY | C | 210 | 290 | 1258 | 46.5% | 1.17 | +2.415,6 |
| EURJPY | D | 160 | 400 | 552 | 33.7% | 1.22 | +1.354,6 |
| USDJPY | D | 110 | 390 | 643 | 26.6% | 1.21 | +1.176,4 |
| NZDUSD | C | 240 | 360 | 227 | 45.4% | 1.22 | +656,8 |
| AUDUSD | E | 140 | 400 | 183 | 29.5% | 1.14 | +266,9 |

#### LONDON
| Pair | Strat | SL | TP | Trades | WR | PF | PnL |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|---:|
| GBPJPY | C | 190 | 360 | 1063 | 37.4% | 1.10 | +1.274,4 |
| EURJPY | C | 110 | 390 | 987 | 24.5% | 1.09 | +769,7 |
| USDCAD | D | 140 | 310 | 520 | 34.8% | 1.13 | +653,6 |
| GBPUSD | C | 150 | 290 | 910 | 36.1% | 1.05 | +467,2 |
| EURUSD | E | 140 | 400 | 202 | 28.7% | 1.10 | +210,9 |
| USDCHF | D | 160 | 370 | 348 | 31.3% | 1.01 | +50,8 |

#### LONDON_NY & NEW_YORK
*(Lihat tabel lengkap di hasil tuning: `python main.py` akan menampilkan leaderboard.)*

> ⚠️ XAUUSD dinonaktifkan karena volatilitas ekstrem (lihat `FORCE_DISABLED` di `results_db.py`).

---

## 🛠️ Troubleshooting

### ❌ "Gagal menginisialisasi MT5"

**Penyebab**: MT5 tidak berjalan atau Algo Trading tidak aktif.

**Solusi**:
1. Buka MetaTrader 5
2. `Tools → Options → Expert Advisors`
3. Centang **"Allow Automated Trading"**
4. Restart terminal

### ❌ Semua test gagal atau error import

**Penyebab**: Dependencies tidak terinstall.

**Solusi**:
```powershell
pip install -r requirements.txt
```

### ❌ "MetaTrader5 not found"

**Penyebab**: Package MT5 tidak terinstall atau versi tidak cocok.

**Solusi**:
```powershell
pip install MetaTrader5==5.0.5735
```

### ❌ Tuning lambat / memory error

**Penyebab**: Data terlalu besar atau CPU terbatas.

**Solusi**:
```powershell
# Kurangi trial atau batasi pair
python tune_all.py --trials 50 --session LONDON  # hanya London, 50 trial
```

### ❌ "No data available" saat backtest

**Penyebab**: Database DuckDB kosong atau data kedaluwarsa.

**Solusi**:
```powershell
python update_db.py
```

### ❌ GUI tidak muncul atau error `customtkinter`

**Penyebab**: CustomTkinter tidak terinstall.

**Solusi**:
```powershell
pip install customtkinter
```

### ❌ Unicode/encoding error di terminal Windows

**Penyebab**: Terminal Windows menggunakan CP1252.

**Solusi**: Project sudah menggunakan ASCII murni. Jika masih error:
```powershell
chcp 65001  # Set UTF-8
```

---

## 🚀 Roadmap

- [ ] **Telegram Alert Integration** — notifikasi order, drawdown, error via bot Telegram
- [ ] **Auto-tuning Scheduler** — Windows Task Scheduler untuk update data mingguan + tuning bulanan
- [ ] **Web Dashboard (Streamlit)** — alternatif GUI via browser
- [ ] **Multi-Account Support** — jalankan robot di beberapa akun sekaligus
- [ ] **Validation Set** — tambah segmen validasi (2024) untuk mengurangi overfitting

---

## 📖 Glosarium

| Istilah | Definisi |
|:---|---|
| **In-Sample (IS)** | Data latih (2021–2024) untuk mencari parameter optimal |
| **Out-of-Sample (OOS)** | Data uji (2025–2026) untuk verifikasi keandalan strategi |
| **Walk-Forward Optimization (WFO)** | Metode optimasi bergulir: optimasi di IS → verifikasi di OOS |
| **Profit Factor (PF)** | Gross Profit / Gross Loss. PF > 1.0 = profitable |
| **Drawdown** | Penurunan saldo dari puncak tertinggi |
| **Stops Level** | Jarak minimum SL/TP dari harga pasar (aturan broker) |
| **Rollover** | Jeda harian (03:45–05:15 WIB) saat spread melebar |

---

## 💡 Catatan untuk Developer

1. **Akses konfigurasi**: Gunakan `config.cfg.SYMBOLS` (dataclass) untuk type hints. Module aliases (`config.SYMBOLS`) masih didukung untuk backward compatibility.
2. **Fungsi dinamis**: `config.get_session_strategy()` dan `config.get_session_sl_tp()` membaca parameter dari database — jangan hardcode.
3. **Risk state**: `risk_manager.get_risk_status()` mengembalikan *copy* value, aman dipanggil dari thread mana pun (GUI).
4. **Backtest paralel**: `backtest.py` menggunakan `ProcessPoolExecutor`. Pastikan data yang dilempar antar proses adalah tipe dasar (numpy array, string, int), bukan objek MT5.
5. **Filter sesi**: Saat tuning, filter jam **UTC** dilakukan *setelah* pemisahan IS/OOS.
