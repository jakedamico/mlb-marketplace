"""
MLB The Show 26 — Marketplace Automation GUI

Wraps the existing automation scripts with a modern GUI.
Runs automation in background threads, logs to the GUI.

Multi-emulator support:
  - Select 1-4 emulators from the GUI
  - Each emulator runs in its own thread, staggered by 120 seconds
  - Default ADB ports: 7555, 7557, 7559, 7561 (override in emulator_coords.json)
  - Thread-safe: each thread has its own device, screenshot cache, and state
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

# Stagger delay between emulator launches (seconds)
STAGGER_DELAY = 120


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

    Each thread registers itself with a prefix like "[EMU 1]".
    Non-registered threads fall through to the original stdout.
    """
    def __init__(self, log_queue: queue.Queue, original):
        self.queue = log_queue
        self.original = original
        self._prefixes = {}  # thread_id -> prefix string
        self._lock = threading.Lock()

    def register(self, prefix: str):
        """Register the current thread with a log prefix."""
        with self._lock:
            self._prefixes[threading.get_ident()] = prefix

    def unregister(self):
        """Unregister the current thread."""
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
            # Non-bot thread — write to original stdout
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
    """No-op context manager for reset() before _lock exists."""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("MLB The Show 26 — Marketplace Bot")
        self.geometry("780x950")
        self.minsize(700, 850)
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
            ("Gold + Silver  (Sell → Buy)", "gold-silver", SILVER),
            ("Gold + Silver  (Buy → Sell)", "gold-silver-buy", SILVER),
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
                "Gold + Silver: OVR 74-84 filter, sells/buys gold and silver cards\n"
                "All Tiers: OVR 74+ filter, sells/buys silver, gold, and diamond cards\n"
                "Silver Only: OVR 74-79 filter, sells/buys silver cards only\n"
                "Buy order: Diamond → Gold → Silver"
            ),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
            justify="left",
        ).pack(anchor="w")

        # ── Emulator count ──
        emu_frame = ctk.CTkFrame(content, fg_color=BG_CARD, corner_radius=10)
        emu_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            emu_frame, text="EMULATORS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_DIM,
        ).pack(anchor="w", padx=14, pady=(10, 4))

        emu_inner = ctk.CTkFrame(emu_frame, fg_color="transparent")
        emu_inner.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            emu_inner, text="Count:",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 8))

        max_emus = min(4, len(self._device_list))
        self.emu_count_var = ctk.StringVar(value="1")
        emu_options = [str(i) for i in range(1, max_emus + 1)]
        emu_dropdown = ctk.CTkOptionMenu(
            emu_inner, variable=self.emu_count_var, values=emu_options,
            font=ctk.CTkFont(size=13),
            fg_color=BG_MID, button_color=ACCENT_BLUE,
            button_hover_color="#1e5fa0",
            dropdown_fg_color=BG_MID,
            width=60, height=30,
            command=self._on_emu_count_change,
        )
        emu_dropdown.pack(side="left")

        self.emu_ports_label = ctk.CTkLabel(
            emu_inner,
            text=f"  Port: {self._device_list[0].split(':')[-1]}",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=TEXT_DIM,
        )
        self.emu_ports_label.pack(side="left", padx=(12, 0))

        emu_desc = ctk.CTkLabel(
            emu_frame,
            text=(
                f"Each emulator starts {STAGGER_DELAY}s apart. "
                f"Override ports in emulator_coords.json → ADB_DEVICES array."
            ),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
            justify="left",
        )
        emu_desc.pack(anchor="w", padx=14, pady=(0, 10))

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

    # ─── Emulator count change ────────────────────────────────────────

    def _on_emu_count_change(self, value):
        """Update the ports label when emulator count changes."""
        n = int(value)
        ports = [d.split(":")[-1] for d in self._device_list[:n]]
        self.emu_ports_label.configure(
            text=f"  Port{'s' if n > 1 else ''}: {', '.join(ports)}"
        )

    # ─── Actions ──────────────────────────────────────────────────────

    def _on_start(self):
        if self.running:
            return

        num_emus = int(self.emu_count_var.get())

        self.running = True
        self.stats.reset()
        self.stats.start_time = time.time()
        self.threads = []

        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="● RUNNING", text_color=ACCENT_GREEN)

        # Build argv from mode selection
        mode = self.mode_var.get()
        argv = ["main.py"]

        if mode == "gold-diamond":
            pass
        elif mode == "gold-diamond-buy":
            argv.append("--buy-first")
        elif mode == "gold-silver":
            argv.append("--gold-silver")
        elif mode == "gold-silver-buy":
            argv.extend(["--gold-silver", "--buy-first"])
        elif mode == "all":
            argv.append("--all")
        elif mode == "all-buy":
            argv.extend(["--all", "--buy-first"])
        elif mode == "silver":
            argv.append("--silver")
        elif mode == "silver-buy":
            argv.extend(["--silver", "--buy-first"])

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

        # Track active threads
        with self._active_lock:
            self._active_count = num_emus

        if multi_emu:
            self._log(f"Starting {num_emus} emulators ({STAGGER_DELAY}s stagger)...\n")
        else:
            self._log(f"Starting: {' '.join(argv)}\n")

        # Launch emulator threads
        for i in range(num_emus):
            device = self._device_list[i] if i < len(self._device_list) \
                else f"127.0.0.1:{7555 + i * 2}"

            t = threading.Thread(
                target=self._run_emulator,
                args=(argv, i, device, multi_emu),
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
        self._log("\n*** STOP requested — all emulators will halt after current action ***\n")

    def _run_emulator(self, argv, emu_index, device, multi_emulator):
        """
        Run a single emulator instance in a background thread.
        Handles stagger delay, thread registration, and cleanup.
        """
        num_emus = int(self.emu_count_var.get())

        # Register thread with log prefix
        if multi_emulator:
            prefix = f"[EMU {emu_index + 1}] "
        else:
            prefix = ""
        self._redirector.register(prefix)

        try:
            # Stagger delay (skip for first emulator)
            if emu_index > 0:
                delay = emu_index * STAGGER_DELAY
                print(f"Waiting {delay}s before starting...")
                end = time.time() + delay
                while time.time() < end:
                    if not self.running:
                        raise KeyboardInterrupt("Stop requested during stagger")
                    self._original_sleep(min(1.0, max(0, end - time.time())))

            print(f"Starting on {device}: {' '.join(argv)}")

            # Import and run
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
        """Called when a single emulator thread finishes."""
        with self._active_lock:
            self._active_count -= 1
            remaining = self._active_count

        if remaining <= 0:
            # All emulators done — restore stdout and sleep
            self._restore_globals()
            self.log_queue.put("__DONE__")

    def _restore_globals(self):
        """Restore sys.stdout and time.sleep after all threads finish."""
        if self._redirector:
            sys.stdout = self._redirector.original
            sys.stderr = self._redirector.original
            self._redirector = None
        if self._original_sleep:
            time.sleep = self._original_sleep
            self._original_sleep = None
        self.running = False

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
        """Parse log messages to update stats (thread-safe)."""
        if "Order placed" in msg or "[9] Order placed" in msg:
            self.stats.increment("cards_bought")
        if "Sold:" in msg or "Sell order placed" in msg:
            self.stats.increment("cards_sold")
        if "complete. Starting next cycle" in msg:
            self.stats.increment("cycles_completed")
        if "API error" in msg or "ERROR" in msg:
            self.stats.increment("errors")

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