#!/usr/bin/env python3
# scheduler.py — Trading bot supervisor
#
# Launched by macOS launchd at 5:30 AM PST on weekdays.
# Starts main.py, monitors it, and shuts everything down at 1:30 PM PST.
# If the bot crashes, restarts it automatically (up to MAX_RESTARTS).

import os
import sys
import signal
import subprocess
import time
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ── Config ────────────────────────────────────────────────────────────
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BOT_DIR, "venv", "bin", "python")
BOT_SCRIPT = os.path.join(BOT_DIR, "main.py")

TIMEZONE = ZoneInfo("America/Los_Angeles")
SHUTDOWN_HOUR = 13   # 1:30 PM PST
SHUTDOWN_MINUTE = 30
MAX_RESTARTS = 5
RESTART_COOLDOWN = 15  # seconds between crash restarts

# ── Logging ───────────────────────────────────────────────────────────
os.makedirs(os.path.join(BOT_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [scheduler] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(BOT_DIR, "logs", "scheduler.log")),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scheduler")

# ── Globals ───────────────────────────────────────────────────────────
bot_process = None
shutting_down = False


def now_pst():
    return datetime.now(TIMEZONE)


def past_shutdown():
    t = now_pst()
    return (t.hour > SHUTDOWN_HOUR or
            (t.hour == SHUTDOWN_HOUR and t.minute >= SHUTDOWN_MINUTE))


def is_weekday():
    return now_pst().weekday() < 5  # Mon=0 .. Fri=4


def stop_bot(reason="scheduled"):
    """Send SIGTERM to the bot process and wait for graceful exit."""
    global bot_process
    if bot_process is None:
        return

    log.info(f"Stopping bot (reason: {reason}) pid={bot_process.pid}")
    try:
        bot_process.terminate()  # SIGTERM
        bot_process.wait(timeout=30)
        log.info("Bot stopped gracefully")
    except subprocess.TimeoutExpired:
        log.warning("Bot did not exit in 30s — sending SIGKILL")
        bot_process.kill()
        bot_process.wait(timeout=10)
    except Exception as e:
        log.error(f"Error stopping bot: {e}")
    finally:
        bot_process = None


def handle_signal(signum, frame):
    """Handle SIGTERM/SIGINT from launchd or manual kill."""
    global shutting_down
    sig_name = signal.Signals(signum).name
    log.info(f"Received {sig_name} — shutting down")
    shutting_down = True
    stop_bot(reason=sig_name)
    sys.exit(0)


def start_bot():
    """Launch main.py as a subprocess."""
    global bot_process
    log.info(f"Starting bot: {VENV_PYTHON} {BOT_SCRIPT}")
    bot_process = subprocess.Popen(
        [VENV_PYTHON, BOT_SCRIPT],
        cwd=BOT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log.info(f"Bot started pid={bot_process.pid}")
    return bot_process


def main():
    global shutting_down

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("=" * 50)
    log.info("Scheduler started")
    log.info(f"  Time:     {now_pst().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    log.info(f"  Shutdown: {SHUTDOWN_HOUR}:{SHUTDOWN_MINUTE:02d} PST")
    log.info(f"  Bot dir:  {BOT_DIR}")
    log.info("=" * 50)

    force = os.environ.get("RHTB_FORCE_START", "").strip() == "1"
    if force:
        log.info("RHTB_FORCE_START=1 — skipping time/day guards")

    # Weekend guard
    if not force and not is_weekday():
        log.info("Weekend — nothing to do. Exiting.")
        return

    # Already past shutdown time (e.g. manual late launch)
    if not force and past_shutdown():
        log.info("Past shutdown time — nothing to do. Exiting.")
        return

    restart_count = 0
    start_bot()

    # ── Main loop: poll bot health + check shutdown time ──────────
    while not shutting_down:
        time.sleep(5)

        # Time check (skipped when force-started for testing)
        if not force and past_shutdown():
            log.info("Shutdown time reached")
            stop_bot(reason="scheduled_shutdown")
            break

        # Bot health check
        if bot_process is not None:
            retcode = bot_process.poll()
            if retcode is not None:
                # Bot exited
                log.warning(f"Bot exited with code {retcode}")

                if not force and past_shutdown():
                    break

                restart_count += 1
                if restart_count > MAX_RESTARTS:
                    log.error(f"Max restarts ({MAX_RESTARTS}) exceeded — giving up")
                    break

                log.info(f"Restarting bot in {RESTART_COOLDOWN}s "
                         f"(attempt {restart_count}/{MAX_RESTARTS})")
                time.sleep(RESTART_COOLDOWN)

                if (not force and past_shutdown()) or shutting_down:
                    break

                start_bot()

    log.info("Scheduler exiting")


if __name__ == "__main__":
    main()
