import sys
import os
import time
import threading
from datetime import datetime
import pytz
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox

import customtkinter as ctk
import MetaTrader5 as mt5

# Impor modul trading kita
import main as robot
from src import config
from src import executor
from src import risk_manager
import update_db
import update_news
import backtest_best

# Konfigurasi CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

WIB = pytz.timezone('Asia/Jakarta')

class RedirectText(object):
    """Mengalihkan stdout/stderr ke CTkTextbox secara real-time."""
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.buffer = ""

    def write(self, string):
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", string)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")

    def flush(self):
        pass

class TradingTerminalGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Setup Window Utama
        self.title("Antigravity Algorithmic Trading Terminal v1.0")
        self.geometry("1150x720")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Variabel Status
        self.robot_thread = None
        self.is_connected_mt5 = False
        
        # --- UI LAYOUT ---
        self.create_sidebar()
        self.create_main_content()
        
        # Mulai loop update data real-time & redirect logs
        self.setup_logging_redirect()
        self.check_connection_status()
        self.update_realtime_data()

    def create_sidebar(self):
        # Frame Sidebar kiri
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar_frame.grid_rowconfigure(9, weight=1)

        # Judul/Logo
        self.logo_label = ctk.CTkLabel(
            self.sidebar_frame, text="ANTIGRAVITY", 
            font=ctk.CTkFont(size=22, weight="bold"), text_color="#2ecc71"
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.sub_logo = ctk.CTkLabel(
            self.sidebar_frame, text="MT5 Algo Terminal", 
            font=ctk.CTkFont(size=12, slant="italic"), text_color="#7f8c8d"
        )
        self.sub_logo.grid(row=1, column=0, padx=20, pady=(0, 20))

        # Status Badge
        self.status_frame = ctk.CTkFrame(self.sidebar_frame, corner_radius=6, fg_color="#2c3e50")
        self.status_frame.grid(row=2, column=0, padx=15, pady=10, sticky="ew")
        
        self.status_dot = ctk.CTkLabel(
            self.status_frame, text="●", text_color="#95a5a6", font=ctk.CTkFont(size=16)
        )
        self.status_dot.pack(side="left", padx=(10, 5), pady=5)
        
        self.status_text = ctk.CTkLabel(
            self.status_frame, text="STANDBY", font=ctk.CTkFont(weight="bold")
        )
        self.status_text.pack(side="left", padx=5, pady=5)

        # Tombol Start/Stop Robot
        self.btn_start = ctk.CTkButton(
            self.sidebar_frame, text="Start Robot", fg_color="#27ae60", hover_color="#219653",
            font=ctk.CTkFont(weight="bold"), command=self.start_robot
        )
        self.btn_start.grid(row=3, column=0, padx=15, pady=10, sticky="ew")

        self.btn_stop = ctk.CTkButton(
            self.sidebar_frame, text="Stop Robot", fg_color="#c0392b", hover_color="#962d22",
            font=ctk.CTkFont(weight="bold"), state="disabled", command=self.stop_robot
        )
        self.btn_stop.grid(row=4, column=0, padx=15, pady=10, sticky="ew")

        # Separator Line
        self.separator = ctk.CTkFrame(self.sidebar_frame, height=2, fg_color="#7f8c8d")
        self.separator.grid(row=5, column=0, padx=15, pady=15, sticky="ew")

        # Tombol Utilitas Background Thread
        self.btn_sync_db = ctk.CTkButton(
            self.sidebar_frame, text="Sync DuckDB Prices", fg_color="#7f8c8d", hover_color="#6c7a89",
            command=self.run_sync_db
        )
        self.btn_sync_db.grid(row=6, column=0, padx=15, pady=8, sticky="ew")

        self.btn_sync_news = ctk.CTkButton(
            self.sidebar_frame, text="Sync Economic News", fg_color="#7f8c8d", hover_color="#6c7a89",
            command=self.run_sync_news
        )
        self.btn_sync_news.grid(row=7, column=0, padx=15, pady=8, sticky="ew")

        self.btn_backtest = ctk.CTkButton(
            self.sidebar_frame, text="Run WFO Backtest", fg_color="#7f8c8d", hover_color="#6c7a89",
            command=self.run_backtest
        )
        self.btn_backtest.grid(row=8, column=0, padx=15, pady=8, sticky="ew")

        # Mode Tampilan (Dark/Light)
        self.appearance_mode_label = ctk.CTkLabel(self.sidebar_frame, text="Appearance Mode:", anchor="w")
        self.appearance_mode_label.grid(row=10, column=0, padx=20, pady=(10, 0))
        self.appearance_mode_menu = ctk.CTkOptionMenu(
            self.sidebar_frame, values=["Dark", "Light", "System"], command=self.change_appearance_mode
        )
        self.appearance_mode_menu.grid(row=11, column=0, padx=20, pady=(10, 20), sticky="ew")

    def create_main_content(self):
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(1, weight=1)

        # --- BARIS 1: STATUS KONEKSI & INFORMASI RINGKAS ---
        self.header_frame = ctk.CTkFrame(self.main_frame, corner_radius=8)
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        self.header_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.lbl_broker = ctk.CTkLabel(self.header_frame, text="Broker: Connecting...", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_broker.grid(row=0, column=0, padx=15, pady=12, sticky="w")

        self.lbl_account = ctk.CTkLabel(self.header_frame, text="Account: N/A", font=ctk.CTkFont(size=13))
        self.lbl_account.grid(row=0, column=1, padx=15, pady=12, sticky="w")

        self.lbl_session = ctk.CTkLabel(self.header_frame, text="Sesi Trading: N/A", font=ctk.CTkFont(size=13))
        self.lbl_session.grid(row=0, column=2, padx=15, pady=12, sticky="w")

        self.lbl_market_status = ctk.CTkLabel(self.header_frame, text="Market: N/A", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_market_status.grid(row=0, column=3, padx=15, pady=12, sticky="e")

        # --- BARIS 2: TABVIEW KONTEN ---
        self.tabview = ctk.CTkTabview(self.main_frame)
        self.tabview.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.tabview.add("Dashboard")
        self.tabview.add("Active Positions")
        self.tabview.add("System Console")
        self.tabview.add("Info & Panduan")

        self.setup_dashboard_tab()
        self.setup_positions_tab()
        self.setup_console_tab()
        self.setup_info_tab()

    def setup_dashboard_tab(self):
        tab = self.tabview.tab("Dashboard")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # Sub-Frame 1: Info Keuangan (Kiri)
        self.fin_frame = ctk.CTkFrame(tab, corner_radius=8)
        self.fin_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.fin_frame.grid_columnconfigure(1, weight=1)

        self.fin_title = ctk.CTkLabel(self.fin_frame, text="FINANCIAL OVERVIEW", font=ctk.CTkFont(size=14, weight="bold"), text_color="#2ecc71")
        self.fin_title.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 15), sticky="w")

        self.lbl_balance = self.create_info_row(self.fin_frame, "Account Balance", "$0.00", 1)
        self.lbl_equity = self.create_info_row(self.fin_frame, "Account Equity", "$0.00", 2)
        self.lbl_margin = self.create_info_row(self.fin_frame, "Free Margin", "$0.00", 3)
        self.lbl_leverage = self.create_info_row(self.fin_frame, "Leverage", "1:N/A", 4)
        
        # Sub-Frame 2: Info Sesi & Pasar (Kanan)
        self.market_frame = ctk.CTkFrame(tab, corner_radius=8)
        self.market_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.market_frame.grid_columnconfigure(1, weight=1)

        self.market_title = ctk.CTkLabel(self.market_frame, text="OPERATIONAL STATUS", font=ctk.CTkFont(size=14, weight="bold"), text_color="#2ecc71")
        self.market_title.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 15), sticky="w")

        self.lbl_time_wib = self.create_info_row(self.market_frame, "Local Time (WIB)", "--:--:--", 1)
        self.lbl_news_filter = self.create_info_row(self.market_frame, "News Filter Status", "N/A", 2)
        self.lbl_active_pairs = self.create_info_row(self.market_frame, "Eligible Pairs Count", "0 / 10", 3)
        self.lbl_uptime = self.create_info_row(self.market_frame, "Robot Uptime", "00:00:00", 4)
        self.lbl_daily_loss = self.create_info_row(self.market_frame, "Daily Loss (Limit 5%)", "0.0%", 5)
        self.lbl_consec_loss = self.create_info_row(self.market_frame, "Consecutive Losses (Limit 3)", "0", 6)

        # Leaderboard Parameter Frame (Bawah)
        self.leader_frame = ctk.CTkFrame(tab, corner_radius=8)
        self.leader_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        self.leader_frame.grid_rowconfigure(1, weight=1)
        self.leader_frame.grid_columnconfigure(0, weight=1)

        self.leader_title = ctk.CTkLabel(self.leader_frame, text="ACTIVE STRATEGY PARAMETERS & LEADERBOARD", font=ctk.CTkFont(size=13, weight="bold"))
        self.leader_title.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="w")

        # Treeview untuk Leaderboard/Params
        self.setup_treeview_styles()
        self.tree_leader = ttk.Treeview(
            self.leader_frame, columns=("Pair", "Strategy", "SL (points)", "TP (points)", "Source", "OOS Net Profit"), show="headings"
        )
        self.tree_leader.heading("Pair", text="PAIR")
        self.tree_leader.heading("Strategy", text="STRATEGY")
        self.tree_leader.heading("SL (points)", text="SL (points)")
        self.tree_leader.heading("TP (points)", text="TP (points)")
        self.tree_leader.heading("Source", text="SOURCE")
        self.tree_leader.heading("OOS Net Profit", text="OOS NET PROFIT")
        
        self.tree_leader.column("Pair", width=80, anchor="center")
        self.tree_leader.column("Strategy", width=80, anchor="center")
        self.tree_leader.column("SL (points)", width=100, anchor="center")
        self.tree_leader.column("TP (points)", width=100, anchor="center")
        self.tree_leader.column("Source", width=120, anchor="center")
        self.tree_leader.column("OOS Net Profit", width=130, anchor="center")

        self.tree_leader.grid(row=1, column=0, sticky="nsew", padx=15, pady=(5, 15))
        
        # Scrollbar untuk Leaderboard Treeview
        scroll_leader = ttk.Scrollbar(self.leader_frame, orient="vertical", command=self.tree_leader.yview)
        scroll_leader.grid(row=1, column=1, sticky="ns", pady=(5, 15))
        self.tree_leader.configure(yscrollcommand=scroll_leader.set)

    def setup_positions_tab(self):
        tab = self.tabview.tab("Active Positions")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Frame List Posisi
        self.pos_list_frame = ctk.CTkFrame(tab, corner_radius=8)
        self.pos_list_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.pos_list_frame.grid_rowconfigure(0, weight=1)
        self.pos_list_frame.grid_columnconfigure(0, weight=1)

        # Treeview untuk Posisi Aktif
        self.tree_pos = ttk.Treeview(
            self.pos_list_frame, columns=("Ticket", "Symbol", "Direction", "Lot", "Entry", "SL", "TP", "Profit ($)"), show="headings"
        )
        self.tree_pos.heading("Ticket", text="TICKET")
        self.tree_pos.heading("Symbol", text="SYMBOL")
        self.tree_pos.heading("Direction", text="DIRECTION")
        self.tree_pos.heading("Lot", text="LOT SIZE")
        self.tree_pos.heading("Entry", text="ENTRY PRICE")
        self.tree_pos.heading("SL", text="STOP LOSS")
        self.tree_pos.heading("TP", text="TAKE PROFIT")
        self.tree_pos.heading("Profit ($)", text="UNREALIZED PNL")

        self.tree_pos.column("Ticket", width=90, anchor="center")
        self.tree_pos.column("Symbol", width=90, anchor="center")
        self.tree_pos.column("Direction", width=100, anchor="center")
        self.tree_pos.column("Lot", width=80, anchor="center")
        self.tree_pos.column("Entry", width=110, anchor="center")
        self.tree_pos.column("SL", width=110, anchor="center")
        self.tree_pos.column("TP", width=110, anchor="center")
        self.tree_pos.column("Profit ($)", width=120, anchor="center")
        
        self.tree_pos.grid(row=0, column=0, sticky="nsew", padx=15, pady=15)

        # Scrollbar untuk Treeview Posisi
        scroll_pos = ttk.Scrollbar(self.pos_list_frame, orient="vertical", command=self.tree_pos.yview)
        scroll_pos.grid(row=0, column=1, sticky="ns", pady=15)
        self.tree_pos.configure(yscrollcommand=scroll_pos.set)

        # Frame Kontrol Order Manual (Bawah)
        self.pos_ctrl_frame = ctk.CTkFrame(tab, corner_radius=8, height=80)
        self.pos_ctrl_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        
        self.lbl_pos_action = ctk.CTkLabel(self.pos_ctrl_frame, text="Manual Position Actions (Select Row):", font=ctk.CTkFont(size=12, weight="bold"))
        self.lbl_pos_action.pack(side="left", padx=20, pady=15)

        self.btn_close_pos = ctk.CTkButton(
            self.pos_ctrl_frame, text="Close Selected Position", fg_color="#e67e22", hover_color="#d35400",
            font=ctk.CTkFont(weight="bold"), command=self.manual_close_position
        )
        self.btn_close_pos.pack(side="left", padx=15, pady=15)

        self.btn_move_be = ctk.CTkButton(
            self.pos_ctrl_frame, text="Set Stop Loss to Break-Even", fg_color="#3498db", hover_color="#2980b9",
            font=ctk.CTkFont(weight="bold"), command=self.manual_move_be
        )
        self.btn_move_be.pack(side="left", padx=15, pady=15)

    def setup_console_tab(self):
        tab = self.tabview.tab("System Console")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Textbox Log Teks
        self.console_textbox = ctk.CTkTextbox(tab, font=("Consolas", 12), fg_color="#1e1e1e")
        self.console_textbox.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.console_textbox.configure(state="disabled")

        # Tombol Aksi Console
        self.console_ctrl = ctk.CTkFrame(tab, corner_radius=8, height=50)
        self.console_ctrl.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        
        self.btn_clear_logs = ctk.CTkButton(
            self.console_ctrl, text="Clear Console Logs", fg_color="#7f8c8d", hover_color="#95a5a6",
            command=self.clear_console_logs
        )
        self.btn_clear_logs.pack(side="right", padx=15, pady=10)

    def create_info_row(self, parent, label_text, default_value, row):
        """Helper untuk membuat baris detail overview."""
        lbl_label = ctk.CTkLabel(parent, text=label_text, anchor="w", font=ctk.CTkFont(size=12))
        lbl_label.grid(row=row, column=0, padx=15, pady=6, sticky="w")
        
        lbl_val = ctk.CTkLabel(parent, text=default_value, anchor="e", font=ctk.CTkFont(size=12, weight="bold"))
        lbl_val.grid(row=row, column=1, padx=15, pady=6, sticky="e")
        return lbl_val

    def setup_treeview_styles(self):
        """Mengatur styling Treeview agar menyatu dengan CustomTkinter dark mode."""
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", 
                        background="#2a2a2a", 
                        foreground="white", 
                        rowheight=26, 
                        fieldbackground="#2a2a2a",
                        bordercolor="#2a2a2a",
                        borderwidth=0)
        style.map('Treeview', background=[('selected', '#27ae60')])
        style.configure("Treeview.Heading", 
                        background="#1e1e1e", 
                        foreground="white", 
                        relief="flat",
                        font=("Segoe UI", 10, "bold"))

    def setup_info_tab(self):
        tab = self.tabview.tab("Info & Panduan")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        # Scrollable Frame agar info yang panjang bisa di-scroll
        scroll_frame = ctk.CTkScrollableFrame(tab, corner_radius=8)
        scroll_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scroll_frame.columnconfigure(0, weight=1)

        # --- SEKSI 1: PENJELASAN ISTILAH GUI ---
        title_gui = ctk.CTkLabel(
            scroll_frame, text="📘 PANDUAN ISTILAH GUI", 
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#2ecc71", anchor="w"
        )
        title_gui.pack(fill="x", padx=15, pady=(10, 15))

        terms = [
            ("Saldo (Balance)", "Jumlah dana bersih di akun saat ini (tidak termasuk floating profit/loss dari posisi berjalan)."),
            ("Equity (Ekuitas)", "Nilai akun secara real-time yang sudah memperhitungkan floating profit/loss berjalan. Jika posisi ditutup, Saldo akan bernilai sama dengan Ekuitas."),
            ("Free Margin", "Sisa jaminan dana yang masih bisa digunakan untuk membuka posisi baru. Jika Free Margin terlalu kecil, broker akan menolak pembukaan order baru."),
            ("Leverage", "Rasio daya ungkit akun (contoh 1:500). Memungkinkan Anda mengontrol volume transaksi besar dengan jaminan margin kecil."),
            ("Unrealized PnL (Floating PnL)", "Profit atau loss berjalan dari posisi aktif yang sedang terbuka dan belum ditutup."),
            ("Sesi Trading", "Zona pasar aktif berdasarkan jam WIB: ASIA (09:00 WIB), LONDON (15:00 WIB), LONDON_NY (20:00 WIB), NEW_YORK (23:00 WIB)."),
            ("Market Status", "Menunjukkan apakah pasar forex global aktif (OPEN) atau tutup (CLOSED) pada hari Sabtu/Minggu."),
            ("News Filter Status", "Sistem perlindungan yang memblokir pembukaan order baru dalam rentang 30 menit sebelum dan sesudah rilis berita ekonomi berkategori High Impact."),
            ("Robot Uptime", "Menunjukkan durasi waktu robot telah berjalan aktif sejak Anda mengklik tombol 'Start Robot'.")
        ]

        for term, desc in terms:
            self.create_info_item(scroll_frame, term, desc)

        # Separator Line
        sep = ctk.CTkFrame(scroll_frame, height=2, fg_color="#34495e")
        sep.pack(fill="x", padx=15, pady=20)

        # --- SEKSI 2: PENJELASAN STRATEGI A - E ---
        title_strat = ctk.CTkLabel(
            scroll_frame, text="⚙️ PENJELASAN STRATEGI (METODE A - E)", 
            font=ctk.CTkFont(size=15, weight="bold"), text_color="#2ecc71", anchor="w"
        )
        title_strat.pack(fill="x", padx=15, pady=(10, 15))

        strategies_info = [
            ("Strategi A: Triple EMA & Stochastic (M1/M5)", 
             "• Deskripsi: Strategi kombinasi tren dan momentum.\n"
             "• Filter Tren (M5): Close > EMA 200 (Tren Naik), Close < EMA 200 (Tren Turun).\n"
             "• Pemicu Tren (M1): Persilangan (Crossover) cepat EMA 9 dan EMA 21.\n"
             "• Pemicu Entri (M1): Stochastic (5,3,3) oversold (<20) untuk BUY, atau overbought (>80) untuk SELL."),
            
            ("Strategi B: Bollinger Bands & Stochastic (M5)", 
             "• Deskripsi: Strategi pembalikan nilai rata-rata (Mean Reversion) yang optimal di pasar sideway (ranging).\n"
             "• BUY: Lilin menyentuh/menembus Lower Band dan Stochastic (5,3,3) cross-up di area oversold (<20).\n"
             "• SELL: Lilin menyentuh/menembus Upper Band dan Stochastic (5,3,3) cross-down di area overbought (>80)."),
            
            ("Strategi C: Heikin Ashi & ATR (M5)", 
             "• Deskripsi: Strategi mengikuti momentum tren kuat (Breakout/Trend Following).\n"
             "• BUY: Terbentuk 3 lilin Heikin Ashi hijau berturut-turut tanpa bayangan bawah (no lower shadow) dan volatilitas pasar mengembang (ATR 14 > Rata-Rata ATR 50).\n"
             "• SELL: Terbentuk 3 lilin Heikin Ashi merah berturut-turut tanpa bayangan atas (no upper shadow) dan volatilitas pasar mengembang (ATR 14 > Rata-Rata ATR 50)."),
            
            ("Strategi D: Fair Value Gap / SMC (M5)", 
             "• Deskripsi: Strategi mengikuti jejak uang institusional (Smart Money Concepts) berdasar celah ketidakefisienan harga.\n"
             "• BUY: Terbentuk Bullish Fair Value Gap (low candle [i] > high candle [i-2]) saat harga di atas EMA 200, dan ukuran gap > 0.5 * ATR.\n"
             "• SELL: Terbentuk Bearish Fair Value Gap (high candle [i] < low candle [i-2]) saat harga di bawah EMA 200, dan ukuran gap > 0.5 * ATR."),
            
            ("Strategi E: Hull Moving Average & RSI-2 (M5)", 
             "• Deskripsi: Strategi Mean Reversion agresif berbasis pembalikan harga ekstrim.\n"
             "• BUY: Harga ditutup di atas Hull Moving Average (HMA 55) sebagai arah tren utama, dan Relative Strength Index (RSI 2) oversold ekstrim (<10).\n"
             "• SELL: Harga ditutup di bawah Hull Moving Average (HMA 55) sebagai arah tren utama, dan Relative Strength Index (RSI 2) overbought ekstrim (>90).")
        ]

        for strat, desc in strategies_info:
            self.create_info_item(scroll_frame, strat, desc)

    def create_info_item(self, parent, title, desc):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=15, pady=8)
        
        lbl_title = ctk.CTkLabel(
            frame, text=title, 
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#e67e22", anchor="w"
        )
        lbl_title.pack(fill="x", padx=0, pady=(0, 2))
        
        lbl_desc = ctk.CTkLabel(
            frame, text=desc, 
            font=ctk.CTkFont(size=11), justify="left", anchor="w", wraplength=800
        )
        lbl_desc.pack(fill="x", padx=5, pady=0)

    # --- SINKRONISASI LOGGING KONSOL ---
    def setup_logging_redirect(self):
        """Menghubungkan print standard out ke textbox GUI."""
        sys.stdout = RedirectText(self.console_textbox)
        sys.stderr = RedirectText(self.console_textbox)

    def clear_console_logs(self):
        self.console_textbox.configure(state="normal")
        self.console_textbox.delete("1.0", "end")
        self.console_textbox.configure(state="disabled")

    # --- KONTROL ROBOT THREADING ---
    def start_robot(self):
        if self.robot_thread and self.robot_thread.is_alive():
            return

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        
        # Ubah Status Badge ke RUNNING
        self.status_dot.configure(text_color="#2ecc71")
        self.status_text.configure(text="RUNNING")
        
        # Start Uptime Timer
        self.start_time = time.time()
        
        # Reset stop signal dan jalankan thread
        robot.gui_stop_signal = False
        self.robot_thread = threading.Thread(target=self._run_robot_loop, daemon=True)
        self.robot_thread.start()

    def _run_robot_loop(self):
        print("\n[GUI Controller] Menyalakan robot autopilot di background thread...")
        try:
            robot.main()
        except Exception as e:
            print(f"[ERROR Thread] Gangguan eksekusi robot: {e}")
        finally:
            self.stop_robot()

    def stop_robot(self):
        if not robot.gui_stop_signal:
            robot.gui_stop_signal = True
            print("\n[GUI Controller] Mengirim sinyal stop ke robot...")
        
        # Reset visual state di UI thread secara aman
        self.after(0, self._reset_ui_standby)

    def _reset_ui_standby(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_dot.configure(text_color="#95a5a6")
        self.status_text.configure(text="STANDBY")
        self.lbl_uptime.configure(text="00:00:00")

    # --- THREADING UNTUK UTILITAS DATABASE ---
    def run_sync_db(self):
        self.btn_sync_db.configure(state="disabled", text="Syncing DB...")
        threading.Thread(target=self._worker_sync_db, daemon=True).start()

    def _worker_sync_db(self):
        try:
            update_db.main()
            messagebox.showinfo("Sync Success", "DuckDB price database successfully synchronized!")
        except Exception as e:
            messagebox.showerror("Sync Error", f"DB Sync failed: {e}")
        finally:
            self.after(0, lambda: self.btn_sync_db.configure(state="normal", text="Sync DuckDB Prices"))

    def run_sync_news(self):
        self.btn_sync_news.configure(state="disabled", text="Syncing News...")
        threading.Thread(target=self._worker_sync_news, daemon=True).start()

    def _worker_sync_news(self):
        try:
            update_news.main()
            messagebox.showinfo("Sync Success", "Economic news calendar successfully synchronized!")
        except Exception as e:
            messagebox.showerror("Sync Error", f"News Sync failed: {e}")
        finally:
            self.after(0, lambda: self.btn_sync_news.configure(state="normal", text="Sync Economic News"))

    def run_backtest(self):
        self.btn_backtest.configure(state="disabled", text="Running Backtest...")
        threading.Thread(target=self._worker_backtest, daemon=True).start()

    def _worker_backtest(self):
        try:
            backtest_best.main()
            messagebox.showinfo("Backtest Success", "WFO Session backtest finished successfully! Check SQLite backtest_results or Terminal logs.")
        except Exception as e:
            messagebox.showerror("Backtest Error", f"Backtest failed: {e}")
        finally:
            self.after(0, lambda: self.btn_backtest.configure(state="normal", text="Run WFO Backtest"))

    # --- PEMBACAAN DATA REAL-TIME ---
    def check_connection_status(self):
        """Memeriksa apakah MT5 aktif terhubung."""
        try:
            if mt5.initialize():
                account = mt5.account_info()
                if account is not None:
                    self.is_connected_mt5 = True
                    self.lbl_broker.configure(text=f"Broker: {account.company}")
                    self.lbl_account.configure(text=f"Account: {account.login} ({'Live' if account.trade_mode == 1 or account.trade_mode == 2 else 'Demo'})")
                else:
                    self.is_connected_mt5 = False
                    self.lbl_broker.configure(text="Broker: Disconnected")
                    self.lbl_account.configure(text="Account: Not logged in")
            else:
                self.is_connected_mt5 = False
                self.lbl_broker.configure(text="Broker: Offline (Failed)")
                self.lbl_account.configure(text="Account: N/A")
        except Exception:
            self.is_connected_mt5 = False
            self.lbl_broker.configure(text="Broker: Error Connection")
            
        # Periksa ulang setiap 5 detik
        self.after(5000, self.check_connection_status)

    def update_realtime_data(self):
        """Pembaruan data keuangan, posisi, dan leaderboard secara real-time."""
        if self.is_connected_mt5:
            account = mt5.account_info()
            if account is not None:
                self.lbl_balance.configure(text=f"${account.balance:,.2f} {account.currency}")
                self.lbl_equity.configure(text=f"${account.equity:,.2f} {account.currency}")
                self.lbl_margin.configure(text=f"${account.margin_free:,.2f} {account.currency}")
                self.lbl_leverage.configure(text=f"1:{account.leverage}")

            # 1. Update WIB Time
            now_wib = datetime.now(WIB)
            self.lbl_time_wib.configure(text=now_wib.strftime("%Y-%m-%d %H:%M:%S"))

            # 2. Update Sesi Trading Aktif
            session = robot.get_current_session()
            self.lbl_session.configure(text=f"Sesi Trading: {session if session else 'TRANSISI'}")

            # 3. Update Status Market Open
            market_open = robot.is_market_open()
            self.lbl_market_status.configure(
                text="MARKET: OPEN" if market_open else "MARKET: CLOSED",
                text_color="#2ecc71" if market_open else "#e74c3c"
            )

            # 4. Update Uptime Robot
            if self.status_text.cget("text") == "RUNNING" and hasattr(self, 'start_time'):
                elapsed = int(time.time() - self.start_time)
                hrs, rem = divmod(elapsed, 3600)
                mins, secs = divmod(rem, 60)
                self.lbl_uptime.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")

            # 5. Refresh Active Positions Treeview
            self.refresh_positions_tree()

            # 6. Update Risk Status (Daily Loss & Consecutive Losses)
            self.update_risk_display(account)

            # 7. Load Leaderboard & Param jika kosong
            if len(self.tree_leader.get_children()) == 0:
                self.refresh_leaderboard_tree()
        
        # Ulangi pembaruan data setiap 2 detik
        self.after(2000, self.update_realtime_data)

    def update_risk_display(self, account):
        """Update daily loss & consecutive losses display from risk_manager."""
        try:
            status = risk_manager.get_risk_status()
            balance = account.balance

            # --- Daily Loss ---
            start_bal = status.get("daily_start_balance")
            if start_bal is not None and start_bal > 0:
                loss_pct = (start_bal - balance) / start_bal * 100
                if loss_pct < 0:
                    loss_pct = 0.0  # profit, tampilkan 0%
                loss_text = f"{loss_pct:.1f}%"
                # Red jika >= 5%, orange jika >= 3%, hijau jika normal
                if loss_pct >= 5.0:
                    self.lbl_daily_loss.configure(text=loss_text, text_color="#e74c3c")
                elif loss_pct >= 3.0:
                    self.lbl_daily_loss.configure(text=loss_text, text_color="#e67e22")
                else:
                    self.lbl_daily_loss.configure(text=loss_text, text_color="#2ecc71")
            else:
                self.lbl_daily_loss.configure(text="N/A", text_color="#7f8c8d")

            # --- Consecutive Losses ---
            consec = status.get("consecutive_losses", 0)
            consec_text = f"{consec} / 3"
            if consec >= 3:
                self.lbl_consec_loss.configure(text=consec_text, text_color="#e74c3c")
            elif consec >= 2:
                self.lbl_consec_loss.configure(text=consec_text, text_color="#e67e22")
            else:
                self.lbl_consec_loss.configure(text=consec_text, text_color="#2ecc71")
        except Exception:
            self.lbl_daily_loss.configure(text="N/A", text_color="#7f8c8d")
            self.lbl_consec_loss.configure(text="N/A", text_color="#7f8c8d")

    def refresh_positions_tree(self):
        """Menyinkronkan data posisi aktif dari MT5 ke Treeview."""
        # Dapatkan ID item terpilih agar tidak hilang saat refresh
        selected_item = self.tree_pos.selection()
        selected_ticket = None
        if selected_item:
            selected_ticket = self.tree_pos.item(selected_item[0])["values"][0]

        # Kosongkan Treeview lama
        for item in self.tree_pos.get_children():
            self.tree_pos.delete(item)

        # Pull data posisi MT5 dengan Magic Number kita
        robot_pos = executor.get_active_positions()
        
        for pos in robot_pos:
            direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            pnl = pos.profit + pos.swap + pos.commission
            item_id = self.tree_pos.insert(
                "", "end", 
                values=(pos.ticket, pos.symbol, direction, pos.volume, pos.price_open, pos.sl, pos.tp, f"{pnl:+.2f}")
            )
            # Re-select jika tiket ini yang sedang dipilih sebelumnya
            if selected_ticket and pos.ticket == int(selected_ticket):
                self.tree_pos.selection_set(item_id)

    def refresh_leaderboard_tree(self):
        """Memuat daftar strategi terbaik yang dideteksi oleh DB."""
        # Bersihkan data lama
        for item in self.tree_leader.get_children():
            self.tree_leader.delete(item)

        # Baca data konfigurasi terbaik saat ini
        best_config = robot.get_best_config()
        eligible_pairs_count = 0
        
        for sym, c in sorted(best_config.items()):
            strat = c.get("strategy") or "OFF"
            sl = c.get("sl", "-")
            tp = c.get("tp", "-")
            source = c.get("source", "?")
            session = c.get("session", "default")
            pnl = c.get("oos_net_profit", "-")
            
            pnl_str = f"+{pnl:.1f} pips" if isinstance(pnl, (int, float)) else "-"
            source_label = f"{source} ({session})"
            
            if strat != "OFF" and strat is not None:
                eligible_pairs_count += 1
                
            self.tree_leader.insert("", "end", values=(sym, strat, sl, tp, source_label, pnl_str))

        self.lbl_active_pairs.configure(text=f"{eligible_pairs_count} / 10 Active")

    # --- MANUAL TRADING FUNCTIONS ---
    def manual_close_position(self):
        selected_item = self.tree_pos.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select an active position row from the list first.")
            return

        values = self.tree_pos.item(selected_item[0])["values"]
        ticket = int(values[0])
        symbol = str(values[1])
        
        confirm = messagebox.askyesno("Close Position", f"Are you sure you want to CLOSE position ticket {ticket} ({symbol})?")
        if confirm:
            print(f"\n[GUI Manual Action] Mengirim perintah penutupan manual untuk tiket {ticket}...")
            success = executor.close_position_by_ticket(ticket)
            if success:
                messagebox.showinfo("Position Closed", f"Successfully closed position ticket {ticket}!")
                self.refresh_positions_tree()
            else:
                messagebox.showerror("Error", f"Failed to close position ticket {ticket}. Check logs.")

    def manual_move_be(self):
        selected_item = self.tree_pos.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select an active position row from the list first.")
            return

        values = self.tree_pos.item(selected_item[0])["values"]
        ticket = int(values[0])
        symbol = str(values[1])
        entry_price = float(values[4])
        current_sl = float(values[5])

        if current_sl == entry_price:
            messagebox.showinfo("SL Already BE", "Stop Loss is already set to Break-Even price.")
            return

        confirm = messagebox.askyesno("Modify Stop Loss", f"Modify Stop Loss of ticket {ticket} ({symbol}) to Entry Price: {entry_price}?")
        if confirm:
            print(f"\n[GUI Manual Action] Memindahkan SL tiket {ticket} ke Break-Even ({entry_price})...")
            success = executor.modify_position_sl(ticket, entry_price)
            if success:
                messagebox.showinfo("SL Modified", f"Successfully modified Stop Loss of ticket {ticket} to Break-Even!")
                self.refresh_positions_tree()
            else:
                messagebox.showerror("Error", f"Failed to modify SL of ticket {ticket}. Check logs.")

    # --- PENGATURAN TAMPILAN ---
    def change_appearance_mode(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def on_closing(self):
        # Pastikan robot dimatikan sebelum GUI ditutup
        if self.status_text.cget("text") == "RUNNING":
            robot.gui_stop_signal = True
            print("\n[GUI Closing] Mematikan robot sebelum keluar...")
            
        # Matikan koneksi MT5
        mt5.shutdown()
        self.destroy()

if __name__ == "__main__":
    app = TradingTerminalGUI()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
