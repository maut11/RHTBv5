# ai_logging.py - AI-Readable JSONL Logging System
"""
Daily rotating JSON Lines logging for AI-assisted analysis.
Captures all bot activity in structured, machine-parseable format.
"""

import logging
import logging.handlers
import json
import datetime
import traceback
import sys
import os
from pathlib import Path
from typing import Optional

# Configuration
DEFAULT_LOG_DIR = "logs"
DEFAULT_RETENTION_DAYS = 14


class JSONFormatter(logging.Formatter):
    """
    Formats log records as JSON objects for AI parsing.
    Captures standard fields plus any 'extra' data passed to logger.
    """
    def format(self, record: logging.LogRecord) -> str:
        # Base structured log record
        log_record = {
            "timestamp": datetime.datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            # Add structured stack trace for deeper analysis
            if record.exc_info[2]:
                log_record["stack_trace"] = traceback.format_tb(record.exc_info[2])

        # Merge 'extra' fields (filtering out standard LogRecord attributes)
        # This allows: logger.info("Trade", extra={"symbol": "SPY", "price": 400})
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName', 'levelname',
            'levelno', 'lineno', 'module', 'msecs', 'pathname', 'process',
            'processName', 'relativeCreated', 'stack_info', 'exc_info', 'exc_text',
            'thread', 'threadName', 'taskName', 'message'
        }
        extra_data = {k: v for k, v in record.__dict__.items()
                      if k not in standard_attrs and k not in log_record}
        if extra_data:
            log_record["data"] = extra_data

        return json.dumps(log_record, default=str)


class DailyRotatingJSONHandler(logging.handlers.TimedRotatingFileHandler):
    """
    Daily rotating handler that names files as 'bot_YYYY-MM-DD.log'
    and automatically cleans up old files.
    """
    def __init__(self, log_dir: str = DEFAULT_LOG_DIR, retention_days: int = DEFAULT_RETENTION_DAYS):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days

        # Current log file
        today = datetime.date.today()
        filename = self.log_dir / f"bot_{today}.log"

        super().__init__(
            filename=str(filename),
            when='midnight',
            interval=1,
            backupCount=0,  # We handle cleanup ourselves
            encoding='utf-8'
        )

        # Clean up old logs on startup
        self._cleanup_old_logs()

    def doRollover(self):
        """Override to use bot_YYYY-MM-DD.log naming convention."""
        if self.stream:
            self.stream.close()
            self.stream = None

        # New filename for today
        today = datetime.date.today()
        new_filename = self.log_dir / f"bot_{today}.log"
        self.baseFilename = str(new_filename)

        # Open new file
        self.stream = self._open()

        # Clean up old logs
        self._cleanup_old_logs()

    def _cleanup_old_logs(self):
        """Delete log files older than retention_days."""
        if not self.log_dir.exists():
            return

        cutoff_date = datetime.date.today() - datetime.timedelta(days=self.retention_days)

        for log_file in self.log_dir.glob("bot_*.log"):
            try:
                # Extract date from filename: bot_YYYY-MM-DD.log
                date_str = log_file.stem.replace("bot_", "")
                file_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

                if file_date < cutoff_date:
                    log_file.unlink()
            except (ValueError, OSError):
                # Skip files that don't match the pattern or can't be deleted
                pass


class StreamToLogger:
    """
    Redirects writes to a logger instance.
    Used to capture print() statements.
    """
    def __init__(self, logger: logging.Logger, level: int = logging.INFO):
        self.logger = logger
        self.level = level
        self.linebuf = ''
        self._terminal = None

    def set_terminal(self, terminal):
        """Store reference to original terminal for dual output."""
        self._terminal = terminal

    def write(self, buf: str):
        # Write to terminal if available (for immediate console feedback)
        if self._terminal:
            self._terminal.write(buf)

        # Buffer and log complete lines
        for line in buf.rstrip().splitlines():
            if line.strip():
                self.logger.log(self.level, line.rstrip())

    def flush(self):
        if self._terminal and hasattr(self._terminal, 'flush'):
            self._terminal.flush()


def setup_ai_logging(log_dir: str = DEFAULT_LOG_DIR, retention_days: int = DEFAULT_RETENTION_DAYS) -> logging.Logger:
    """
    Setup AI-readable logging system with:
    - JSONL file output (daily rotating)
    - Human-readable console output
    - Print statement capture

    Args:
        log_dir: Directory for log files (default: "logs")
        retention_days: Days to keep old logs (default: 14)

    Returns:
        Configured 'main' logger
    """
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # Get root logger and main logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    main_logger = logging.getLogger('main')
    main_logger.setLevel(logging.DEBUG)

    # Clear existing handlers
    root_logger.handlers.clear()
    main_logger.handlers.clear()

    # 1. JSON File Handler (The "AI Memory")
    json_handler = DailyRotatingJSONHandler(log_dir, retention_days)
    json_handler.setFormatter(JSONFormatter())
    json_handler.setLevel(logging.DEBUG)  # Capture everything
    root_logger.addHandler(json_handler)

    # 2. Console Handler (Human readable)
    console_handler = logging.StreamHandler(sys.__stdout__)  # Use original stdout
    console_handler.setFormatter(logging.Formatter(
        '%(levelname)s - %(message)s'
    ))
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    # 3. Error file handler (for quick error lookup)
    error_handler = logging.FileHandler(log_path / "errors.log", encoding='utf-8')
    error_handler.setFormatter(JSONFormatter())
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)

    # 4. Redirect stdout/stderr to capture print statements
    stdout_logger = StreamToLogger(root_logger, logging.INFO)
    stdout_logger.set_terminal(sys.__stdout__)
    sys.stdout = stdout_logger

    stderr_logger = StreamToLogger(root_logger, logging.ERROR)
    stderr_logger.set_terminal(sys.__stderr__)
    sys.stderr = stderr_logger

    # Log startup
    main_logger.info("AI Logging System Initialized", extra={
        "event_type": "startup",
        "config": {
            "log_dir": str(log_dir),
            "retention_days": retention_days,
            "format": "JSONL"
        }
    })

    return main_logger


def log_event(event_type: str, message: str = "", **kwargs) -> None:
    """
    Convenience function for structured event logging.

    Args:
        event_type: Type of event (e.g., "discord_message", "trade_execution")
        message: Human-readable message
        **kwargs: Additional structured data

    Example:
        log_event("trade_execution", "Buy order placed",
                  symbol="SPY", quantity=5, price=450.20)
    """
    logger = logging.getLogger('main')
    logger.info(message or event_type, extra={"event_type": event_type, **kwargs})


def log_error(component: str, error: Exception, context: Optional[dict] = None) -> None:
    """
    Convenience function for structured error logging.

    Args:
        component: Component where error occurred (e.g., "trader", "parser")
        error: The exception that was raised
        context: Additional context about what was happening
    """
    logger = logging.getLogger('main')
    logger.error(
        str(error),
        exc_info=True,
        extra={
            "event_type": "error",
            "component": component,
            "error_type": type(error).__name__,
            "context": context or {}
        }
    )
