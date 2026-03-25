"""
MLB The Show 26 — Marketplace Automation GUI

Wraps the existing automation scripts with a modern GUI.
Runs automation in background threads, logs to the GUI.
"""

import customtkinter as ctk
import threading
import sys
import io
import time
import json
import os
import queue

# ─── Theme ────────────────────────────────────────────────────────────────

ctk.set_appearance_mode("dark")

# MLB-inspired colors
BG_DARK = "#0c1829"
BG_MID = "#122240"
BG_CARD = "#1a2d4a"
ACCENT_BLUE = "#2d7dca"
ACCENT_GOLD = "#c9a227"
ACCENT_GREEN = "#4caf50"
ACCENT_RED = "#f44336"
TEXT_PRIMARY = "#e8edf3"
TEXT_DIM = "#7a8ba3"
DIAMOND = "#a855f7"
GOLD = "#eab308"
SILVER = "#94a3b8"


class LogRedirector:
    """Captures print() output and sends it to a queue for the GUI."""
    def __init__(self, log_queue: queue.Queue):
        self.queue = log_queue
        self.buffer = ""

    def write(self, text):
        if text.strip():
            self.queue.put(text)

    def flush(self):
        pass


class StatsTracker:
    """Tracks session statistics."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.stubs_start = 0
        self.stubs_current = 0
        self.cards_bought = 0
        self.cards_sold = 0
        self.cycles_completed = 0
        self.errors = 0
        self.start_time = None

    def elapsed(self) -> str:
        if not self.start_time:
            return "00:00:00"
        s = int(time.time() - self.start_time)
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("MLB The Show 26 — Marketplace Bot")
        self.geometry("780x850")
        self.minsize(700, 750)
        self.configure(fg_color=BG_DARK)

        self.log_queue = queue.Queue()
        self.stats = StatsTracker()
        self.running = False
        self.thread = None

        self._build_ui()
        self._poll_log_queue()

    # ─── UI Layout ────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color=BG_MID, corner_radius=0, height=60)
        header.pack(fill="x")
        header.pack_propagate(False)

        title_label = ctk.CTkLabel(
            header, text="MLB The Show 26",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_label.pack(side="left", padx=20, pady=12)

        subtitle = ctk.CTkLabel(
            header, text="MARKETPLACE BOT",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=ACCENT_BLUE,
        )
        subtitle.pack(side="left", padx=(0, 20), pady=12)

        # Status indicator
        self.status_label = ctk.CTkLabel(
            header, text="● IDLE",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color=TEXT_DIM,
        )
        self.status_label.pack(side="right", padx=20, pady=12)

        # Main content
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=(12, 16))

        # ── Mode selection ──
        mode_frame = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=10)
        mode_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            mode_frame, text="MODE",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        self.mode_var = ctk.StringVar(value="gold-diamond")
        modes = [
            ("Gold + Diamond  (Sell → Buy)", "gold-diamond", GOLD),
            ("Gold + Diamond  (Buy → Sell)", "gold-diamond-buy", GOLD),
            ("All Tiers  (Sell → Buy)", "all", SILVER),
            ("All Tiers  (Buy → Sell)", "all-buy", SILVER),
            ("Silver Only  (Sell → Buy)", "silver", SILVER),
            ("Silver Only  (Buy → Sell)", "silver-buy", SILVER),
        ]
        for label, val, color in modes:
            rb = ctk.CTkRadioButton(
                mode_frame, text=label, variable=self.mode_var, value=val,
                font=ctk.CTkFont(size=13),
                text_color=TEXT_PRIMARY,
                fg_color=color,
                hover_color=color,
                border_color=TEXT_DIM,
                radiobutton_width=18, radiobutton_height=18,
            )
            rb.pack(anchor="w", padx=20, pady=3)

        # Mode descriptions
        desc_frame = ctk.CTkFrame(mode_frame, fg_color="transparent")
        desc_frame.pack(fill="x", padx=20, pady=(6, 10))

        ctk.CTkLabel(
            desc_frame,
            text=(
                "Gold + Diamond: OVR 80+ filter, sells/buys gold and diamond cards\n"
                "All Tiers: OVR 74+ filter, sells/buys silver, gold, and diamond cards\n"
                "Silver Only: OVR 74-79 filter, sells/buys silver cards only\n"
                "Buy order: Diamond → Gold → Silver"
            ),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
            justify="left",
        ).pack(anchor="w")

        # ── Stats panel ──
        stats_frame = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=10)
        stats_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            stats_frame, text="SESSION",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        stats_grid = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_grid.pack(fill="x", padx=14, pady=(0, 10))
        for i in range(5):
            stats_grid.columnconfigure(i, weight=1)

        stat_items = [
            ("ELAPSED", "elapsed"),
            ("BOUGHT", "bought"),
            ("SOLD", "sold"),
            ("CYCLES", "cycles"),
            ("ERRORS", "errors"),
        ]
        self.stat_labels = {}
        for i, (title, key) in enumerate(stat_items):
            f = ctk.CTkFrame(stats_grid, fg_color="transparent")
            f.grid(row=0, column=i, sticky="nsew", padx=4)
            ctk.CTkLabel(
                f, text=title,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=TEXT_DIM,
            ).pack()
            val_label = ctk.CTkLabel(
                f, text="0" if key != "elapsed" else "00:00:00",
                font=ctk.CTkFont(family="Consolas", size=18, weight="bold"),
                text_color=TEXT_PRIMARY,
            )
            val_label.pack()
            self.stat_labels[key] = val_label

        # ── Control buttons ──
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 10))

        self.start_btn = ctk.CTkButton(
            btn_frame, text="▶  START", command=self._on_start,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT_GREEN, hover_color="#388e3c",
            text_color="white", height=44, corner_radius=8,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="■  STOP", command=self._on_stop,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color=ACCENT_RED, hover_color="#c62828",
            text_color="white", height=44, corner_radius=8,
            state="disabled",
        )
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(5, 0))

        # ── Log output ──
        log_frame = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=10)
        log_frame.pack(fill="both", expand=True)

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_header.pack(fill="x", padx=14, pady=(8, 0))

        ctk.CTkLabel(
            log_header, text="LOG",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(side="left")

        clear_btn = ctk.CTkButton(
            log_header, text="Clear", command=self._clear_log,
            font=ctk.CTkFont(size=11),
            fg_color="transparent", hover_color=BG_MID,
            text_color=TEXT_DIM, width=50, height=24,
        )
        clear_btn.pack(side="right")

        self.log_text = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=BG_DARK, text_color=TEXT_PRIMARY,
            corner_radius=6, border_width=0,
            wrap="word",
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(4, 10))

    # ─── Actions ──────────────────────────────────────────────────────

    def _on_start(self):
        if self.running:
            return

        self.running = True
        self.stats.reset()
        self.stats.start_time = time.time()

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="● RUNNING", text_color=ACCENT_GREEN)

        # Build argv from mode selection
        mode = self.mode_var.get()
        argv = ["main.py"]

        if mode == "gold-diamond":
            pass  # default
        elif mode == "gold-diamond-buy":
            argv.append("--buy-first")
        elif mode == "all":
            argv.append("--all")
        elif mode == "all-buy":
            argv.extend(["--all", "--buy-first"])
        elif mode == "silver":
            argv.append("--silver")
        elif mode == "silver-buy":
            argv.extend(["--silver", "--buy-first"])

        self._log(f"Starting: {' '.join(argv)}\n")

        self.thread = threading.Thread(target=self._run_bot, args=(argv,), daemon=True)
        self.thread.start()
        self._update_stats()

    def _on_stop(self):
        if not self.running:
            return
        self.running = False
        self.status_label.configure(text="● STOPPING...", text_color=ACCENT_GOLD)
        self._log("\n*** STOP requested — will halt after current action ***\n")

    def _run_bot(self, argv):
        """Run the automation in a background thread."""
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        redirector = LogRedirector(self.log_queue)
        sys.stdout = redirector
        sys.stderr = redirector

        old_argv = sys.argv
        sys.argv = argv

        _original_sleep = time.sleep

        def _interruptible_sleep(seconds):
            end = time.time() + seconds
            while time.time() < end:
                if not self.running:
                    raise KeyboardInterrupt("Stop requested")
                _original_sleep(min(0.25, max(0, end - time.time())))

        time.sleep = _interruptible_sleep

        try:
            import importlib
            import adb_screen
            import automation
            import main as main_module
            importlib.reload(adb_screen)
            importlib.reload(automation)
            importlib.reload(main_module)

            main_module.main()

        except KeyboardInterrupt:
            self.log_queue.put("\n*** Bot stopped ***\n")
        except Exception as e:
            self.log_queue.put(f"\n*** ERROR: {e} ***\n")
            import traceback
            self.log_queue.put(traceback.format_exc())
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.argv = old_argv
            time.sleep = _original_sleep
            self.running = False
            self.log_queue.put("__DONE__")

    def _poll_log_queue(self):
        """Poll the log queue and append to the text widget."""
        while True:
            try:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status_label.configure(text="● IDLE", text_color=TEXT_DIM)
                    continue
                self._log(msg)
                self._parse_stats(msg)
            except queue.Empty:
                break
        self.after(100, self._poll_log_queue)

    def _log(self, text: str):
        """Append text to the log widget."""
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _parse_stats(self, msg: str):
        """Parse log messages to update stats."""
        if "Order placed" in msg or "[9] Order placed" in msg:
            self.stats.cards_bought += 1
        if "Sold:" in msg or "Sell order placed" in msg:
            self.stats.cards_sold += 1
        if "complete. Starting next cycle" in msg:
            self.stats.cycles_completed += 1
        if "API error" in msg or "ERROR" in msg:
            self.stats.errors += 1

    def _update_stats(self):
        """Periodically update the stats display."""
        if self.stats.start_time:
            self.stat_labels["elapsed"].configure(text=self.stats.elapsed())
        self.stat_labels["bought"].configure(text=str(self.stats.cards_bought))
        self.stat_labels["sold"].configure(text=str(self.stats.cards_sold))
        self.stat_labels["cycles"].configure(text=str(self.stats.cycles_completed))
        self.stat_labels["errors"].configure(text=str(self.stats.errors))

        if self.running:
            self.after(1000, self._update_stats)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")
    app = App()
    app.mainloop()