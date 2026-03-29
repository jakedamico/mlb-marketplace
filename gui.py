"""
MLB The Show 26 — Marketplace Automation GUI

Wraps the existing automation scripts with a modern GUI.
Runs automation in background threads, logs to the GUI.

Single emulator: full sell+buy cycles as before.
Two emulators: EMU 1 = dedicated seller, EMU 2 = dedicated buyer.
  Each cancels its own order type between rounds.
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

# Default ADB ports for MuMu emulator instances
DEFAULT_PORTS = [7555, 7557, 7559, 7561]


def _load_device_list() -> list[str]:
    """
    Load ADB device addresses from emulator_coords.json if available.
    Falls back to default port pattern: 127.0.0.1:7555, 7557, 7559, 7561
    """
    try:
        with open("emulator_coords.json", "r") as f:
            coords = json.load(f)
        devices = coords.get("ADB_DEVICES")
        if isinstance(devices, list) and devices:
            return [str(d) for d in devices]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return [f"127.0.0.1:{port}" for port in DEFAULT_PORTS]


class ThreadAwareRedirector:
    """
    Replaces sys.stdout to route print() output from multiple emulator
    threads into the GUI log queue with per-thread prefixes.
    """
    def __init__(self, log_queue: queue.Queue, original):
        self.queue = log_queue
        self.original = original
        self._prefixes = {}
        self._lock = threading.Lock()

    def register(self, prefix: str):
        with self._lock:
            self._prefixes[threading.get_ident()] = prefix

    def unregister(self):
        with self._lock:
            self._prefixes.pop(threading.get_ident(), None)

    def write(self, text):
        if not text.strip():
            return
        tid = threading.get_ident()
        with self._lock:
            prefix = self._prefixes.get(tid)
        if prefix is not None:
            self.queue.put(f"{prefix}{text}")
        else:
            self.original.write(text)

    def flush(self):
        self.original.flush()


class StatsTracker:
    """Tracks session statistics (thread-safe for multi-emulator)."""
    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock if hasattr(self, '_lock') else _DummyLock():
            self.stubs_start = 0
            self.stubs_current = 0
            self.cards_bought = 0
            self.cards_sold = 0
            self.cycles_completed = 0
            self.errors = 0
            self.start_time = None

    def increment(self, field: str, amount: int = 1):
        with self._lock:
            setattr(self, field, getattr(self, field) + amount)

    def elapsed(self) -> str:
        if not self.start_time:
            return "00:00:00"
        s = int(time.time() - self.start_time)
        h, r = divmod(s, 3600)
        m, sec = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"


class _DummyLock:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("MLB The Show 26 — Marketplace Bot")
        self.geometry("1020x820")
        self.minsize(900, 700)
        self.configure(fg_color=BG_DARK)

        self.log_queue = queue.Queue()
        self.stats = StatsTracker()
        self.running = False
        self.threads = []
        self._active_count = 0
        self._active_lock = threading.Lock()
        self._original_sleep = None
        self._redirector = None
        self._device_list = _load_device_list()

        self.log_widgets = []

        self._build_ui()
        self._poll_log_queue()

    # ─── UI Layout ────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color=BG_MID, corner_radius=0, height=52)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="MLB The Show 26",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=20, pady=10)

        ctk.CTkLabel(
            header, text="MARKETPLACE BOT",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=ACCENT_BLUE,
        ).pack(side="left", padx=(0, 20), pady=10)

        self.status_label = ctk.CTkLabel(
            header, text="● IDLE",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=TEXT_DIM,
        )
        self.status_label.pack(side="right", padx=20, pady=10)

        # ── Main content: left controls + right logs ──
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        body.columnconfigure(0, weight=0, minsize=330)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(body, fg_color="transparent", width=320)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._build_controls(left)

        self._right_frame = ctk.CTkFrame(body, fg_color="transparent")
        self._right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self._build_log_panel()

    def _build_controls(self, parent):
        # ── Mode selection ──
        mode_frame = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        mode_frame.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            mode_frame, text="MODE",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        self.mode_var = ctk.StringVar(value="gold-diamond")
        modes = [
            ("Gold + Diamond  (Sell → Buy)", "gold-diamond", GOLD),
            ("Gold + Diamond  (Buy → Sell)", "gold-diamond-buy", GOLD),
            ("Gold + Silver  (Sell → Buy)", "gold-silver", SILVER),
            ("Gold + Silver  (Buy → Sell)", "gold-silver-buy", SILVER),
            ("All Tiers  (Sell → Buy)", "all", SILVER),
            ("All Tiers  (Buy → Sell)", "all-buy", SILVER),
            ("Silver Only  (Sell → Buy)", "silver", SILVER),
            ("Silver Only  (Buy → Sell)", "silver-buy", SILVER),
        ]
        for label, val, color in modes:
            ctk.CTkRadioButton(
                mode_frame, text=label, variable=self.mode_var, value=val,
                font=ctk.CTkFont(size=12),
                text_color=TEXT_PRIMARY,
                fg_color=color, hover_color=color,
                border_color=TEXT_DIM,
                radiobutton_width=16, radiobutton_height=16,
            ).pack(anchor="w", padx=16, pady=2)

        ctk.CTkLabel(
            mode_frame,
            text=(
                "Buy order: Diamond → Gold → Silver\n"
                "Gold+Diamond: OVR 80+  |  All: OVR 74+\n"
                "Gold+Silver: OVR 74-84  |  Silver: OVR 74-79"
            ),
            font=ctk.CTkFont(size=10),
            text_color=TEXT_DIM, justify="left",
        ).pack(anchor="w", padx=16, pady=(4, 8))

        # ── Diamond settings ──
        diamond_frame = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        diamond_frame.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            diamond_frame, text="DIAMOND SETTINGS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        dp_row = ctk.CTkFrame(diamond_frame, fg_color="transparent")
        dp_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(
            dp_row, text="Max buy price:",
            font=ctk.CTkFont(size=12), text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 6))

        self.max_diamond_price_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            dp_row, textvariable=self.max_diamond_price_var,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=BG_DARK, text_color=TEXT_PRIMARY,
            border_color=TEXT_DIM, placeholder_text="No limit",
            width=100, height=28,
        ).pack(side="left")

        ctk.CTkLabel(
            dp_row, text="stubs",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
        ).pack(side="left", padx=(4, 0))

        # ── Emulator count ──
        emu_frame = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        emu_frame.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            emu_frame, text="EMULATORS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        emu_row = ctk.CTkFrame(emu_frame, fg_color="transparent")
        emu_row.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(
            emu_row, text="Count:",
            font=ctk.CTkFont(size=12), text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 6))

        max_emus = min(2, len(self._device_list))
        self.emu_count_var = ctk.StringVar(value="1")
        ctk.CTkOptionMenu(
            emu_row, variable=self.emu_count_var,
            values=[str(i) for i in range(1, max_emus + 1)],
            font=ctk.CTkFont(size=12),
            fg_color=BG_MID, button_color=ACCENT_BLUE,
            button_hover_color="#1e5fa0", dropdown_fg_color=BG_MID,
            width=55, height=28,
            command=self._on_emu_count_change,
        ).pack(side="left")

        self.emu_ports_label = ctk.CTkLabel(
            emu_row,
            text=f"  Port: {self._device_list[0].split(':')[-1]}",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color=TEXT_DIM,
        )
        self.emu_ports_label.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            emu_frame,
            text=(
                "1 emulator: full sell + buy cycles.\n"
                "2 emulators: EMU 1 sells, EMU 2 buys.\n"
                "Each cancels its own orders between rounds."
            ),
            font=ctk.CTkFont(size=10),
            text_color=TEXT_DIM, justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        # ── Stats panel ──
        stats_frame = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=10)
        stats_frame.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            stats_frame, text="SESSION",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=12, pady=(8, 2))

        stats_grid = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_grid.pack(fill="x", padx=8, pady=(0, 8))
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
            f.grid(row=0, column=i, sticky="nsew", padx=2)
            ctk.CTkLabel(
                f, text=title,
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=TEXT_DIM,
            ).pack()
            val_label = ctk.CTkLabel(
                f, text="0" if key != "elapsed" else "00:00:00",
                font=ctk.CTkFont(family="Consolas", size=15, weight="bold"),
                text_color=TEXT_PRIMARY,
            )
            val_label.pack()
            self.stat_labels[key] = val_label

        # ── Control buttons ──
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(0, 4))

        self.start_btn = ctk.CTkButton(
            btn_frame, text="▶  START", command=self._on_start,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT_GREEN, hover_color="#388e3c",
            text_color="white", height=40, corner_radius=8,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.stop_btn = ctk.CTkButton(
            btn_frame, text="■  STOP", command=self._on_stop,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT_RED, hover_color="#c62828",
            text_color="white", height=40, corner_radius=8,
            state="disabled",
        )
        self.stop_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

    # ─── Log panel (right side) ───────────────────────────────────────

    def _build_log_panel(self):
        for widget in self._right_frame.winfo_children():
            widget.destroy()
        self.log_widgets.clear()

        num_emus = int(self.emu_count_var.get())

        self._right_frame.rowconfigure(0, weight=1)
        if num_emus > 1:
            self._right_frame.rowconfigure(1, weight=1)
        else:
            self._right_frame.rowconfigure(1, weight=0)
        self._right_frame.columnconfigure(0, weight=1)

        for i in range(num_emus):
            log_frame = ctk.CTkFrame(self._right_frame, fg_color=BG_CARD, corner_radius=10)
            log_frame.grid(row=i, column=0, sticky="nsew",
                           pady=(0, 4) if i == 0 and num_emus > 1 else (0, 0))

            log_header = ctk.CTkFrame(log_frame, fg_color="transparent")
            log_header.pack(fill="x", padx=10, pady=(6, 0))

            if num_emus > 1:
                role = "SELLER" if i == 0 else "BUYER"
                port = self._device_list[i].split(":")[-1] if i < len(self._device_list) else "?"
                label_text = f"EMU {i + 1} — {role}  ({port})"
            else:
                label_text = "LOG"

            ctk.CTkLabel(
                log_header, text=label_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=TEXT_DIM,
            ).pack(side="left")

            ctk.CTkButton(
                log_header, text="Clear",
                command=lambda idx=i: self._clear_log(idx),
                font=ctk.CTkFont(size=10),
                fg_color="transparent", hover_color=BG_MID,
                text_color=TEXT_DIM, width=44, height=20,
            ).pack(side="right")

            textbox = ctk.CTkTextbox(
                log_frame,
                font=ctk.CTkFont(family="Consolas", size=11),
                fg_color=BG_DARK, text_color=TEXT_PRIMARY,
                corner_radius=6, border_width=0, wrap="word",
            )
            textbox.pack(fill="both", expand=True, padx=8, pady=(2, 8))

            self.log_widgets.append((log_frame, textbox))

    # ─── Emulator count change ────────────────────────────────────────

    def _on_emu_count_change(self, value):
        n = int(value)
        ports = [d.split(":")[-1] for d in self._device_list[:n]]
        self.emu_ports_label.configure(
            text=f"  Port{'s' if n > 1 else ''}: {', '.join(ports)}"
        )
        if not self.running:
            self._build_log_panel()

    # ─── Log helpers ──────────────────────────────────────────────────

    def _log_to(self, emu_idx: int, text: str):
        if emu_idx < len(self.log_widgets):
            _, textbox = self.log_widgets[emu_idx]
            # Only auto-scroll if user is already at the bottom
            at_bottom = textbox.yview()[1] >= 0.95
            textbox.insert("end", text + "\n")
            if at_bottom:
                textbox.see("end")

    def _clear_log(self, emu_idx: int = 0):
        if emu_idx < len(self.log_widgets):
            _, textbox = self.log_widgets[emu_idx]
            textbox.delete("1.0", "end")

    # ─── Actions ──────────────────────────────────────────────────────

    def _on_start(self):
        if self.running:
            return

        num_emus = int(self.emu_count_var.get())
        self._build_log_panel()

        self.running = True
        self.stats.reset()
        self.stats.start_time = time.time()
        self.threads = []

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="● RUNNING", text_color=ACCENT_GREEN)

        # Build base argv from mode selection
        mode = self.mode_var.get()
        base_argv = ["main.py"]

        if mode == "gold-diamond":
            pass
        elif mode == "gold-diamond-buy":
            base_argv.append("--buy-first")
        elif mode == "gold-silver":
            base_argv.append("--gold-silver")
        elif mode == "gold-silver-buy":
            base_argv.extend(["--gold-silver", "--buy-first"])
        elif mode == "all":
            base_argv.append("--all")
        elif mode == "all-buy":
            base_argv.extend(["--all", "--buy-first"])
        elif mode == "silver":
            base_argv.append("--silver")
        elif mode == "silver-buy":
            base_argv.extend(["--silver", "--buy-first"])

        # Max diamond price
        max_dp = self.max_diamond_price_var.get().strip().replace(",", "")
        if max_dp:
            try:
                int(max_dp)
                base_argv.extend(["--max-diamond-price", max_dp])
            except ValueError:
                self._log_to(0, "WARNING: Invalid max diamond price — ignoring.")

        multi_emu = num_emus > 1

        # Install thread-aware stdout redirector
        self._original_sleep = time.sleep
        self._redirector = ThreadAwareRedirector(self.log_queue, sys.stdout)
        sys.stdout = self._redirector
        sys.stderr = self._redirector

        # Monkey-patch time.sleep for interruptible waits
        app_ref = self
        original_sleep = self._original_sleep

        def _interruptible_sleep(seconds):
            end = time.time() + seconds
            while time.time() < end:
                if not app_ref.running:
                    raise KeyboardInterrupt("Stop requested")
                original_sleep(min(0.25, max(0, end - time.time())))

        time.sleep = _interruptible_sleep

        with self._active_lock:
            self._active_count = num_emus

        if multi_emu:
            self._log_to(0, "Starting 2 emulators: EMU 1 = Seller, EMU 2 = Buyer")
            self._log_to(0, "Each cancels its own orders between rounds.\n")
            self._log_to(1, "Waiting for seller to start first...\n")
        else:
            self._log_to(0, f"Starting: {' '.join(base_argv)}\n")

        # Launch emulator threads
        for i in range(num_emus):
            device = self._device_list[i] if i < len(self._device_list) \
                else f"127.0.0.1:{7555 + i * 2}"

            if multi_emu:
                # EMU 1 = seller, EMU 2 = buyer
                # Strip --buy-first since it doesn't apply to dedicated modes
                emu_argv = [a for a in base_argv if a != "--buy-first"]
                if i == 0:
                    emu_argv.append("--sell-only")
                else:
                    emu_argv.append("--buy-only")
            else:
                emu_argv = list(base_argv)

            t = threading.Thread(
                target=self._run_emulator,
                args=(emu_argv, i, device, multi_emu),
                daemon=True,
            )
            t.start()
            self.threads.append(t)

        self._update_stats()

    def _on_stop(self):
        if not self.running:
            return
        self.running = False
        self.status_label.configure(text="● STOPPING...", text_color=ACCENT_GOLD)
        for i in range(len(self.log_widgets)):
            self._log_to(i, "\n*** STOP requested — halting after current action ***")

    def _run_emulator(self, argv, emu_index, device, multi_emulator):
        """Run a single emulator instance in a background thread."""
        prefix = f"[EMU {emu_index + 1}] "
        self._redirector.register(prefix)

        try:
            if "--sell-only" in argv:
                role = "Seller"
            elif "--buy-only" in argv:
                role = "Buyer"
            else:
                role = "Combined"
            print(f"Starting on {device} ({role}): {' '.join(argv)}")

            import main as main_module
            main_module.main(
                args=argv,
                emu_index=emu_index,
                multi_emulator=multi_emulator,
                device=device,
            )

        except KeyboardInterrupt:
            print(f"Bot stopped.")
        except Exception as e:
            print(f"*** ERROR: {e} ***")
            import traceback
            print(traceback.format_exc())
        finally:
            self._redirector.unregister()
            self._on_emulator_done()

    def _on_emulator_done(self):
        with self._active_lock:
            self._active_count -= 1
            remaining = self._active_count

        if remaining <= 0:
            self._restore_globals()
            self.log_queue.put("__DONE__")

    def _restore_globals(self):
        if self._redirector:
            sys.stdout = self._redirector.original
            sys.stderr = self._redirector.original
            self._redirector = None
        if self._original_sleep:
            time.sleep = self._original_sleep
            self._original_sleep = None
        self.running = False

    # ─── Log queue polling & routing ──────────────────────────────────

    def _poll_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
                if msg == "__DONE__":
                    self.start_btn.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.status_label.configure(text="● IDLE", text_color=TEXT_DIM)
                    continue

                emu_idx, clean_msg = self._parse_emu_prefix(msg)
                self._log_to(emu_idx, clean_msg)
                self._parse_stats(msg)
            except queue.Empty:
                break
        self.after(100, self._poll_log_queue)

    def _parse_emu_prefix(self, msg: str) -> tuple[int, str]:
        if msg.startswith("[EMU "):
            try:
                end = msg.index("]")
                num = int(msg[5:end])
                clean = msg[end + 2:]
                idx = num - 1
                if idx >= len(self.log_widgets):
                    idx = 0
                return idx, clean
            except (ValueError, IndexError):
                pass
        return 0, msg

    def _parse_stats(self, msg: str):
        if "Order placed" in msg or "[9] Order placed" in msg:
            self.stats.increment("cards_bought")
        if "Sold:" in msg or "Sell order placed" in msg:
            self.stats.increment("cards_sold")
        if "complete. Starting next cycle" in msg:
            self.stats.increment("cycles_completed")
        if "API error" in msg or "ERROR" in msg:
            self.stats.increment("errors")

    def _update_stats(self):
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