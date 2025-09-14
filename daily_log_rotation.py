"""
Daily Log Rotation System
Implements YYYY-MM-DD log file naming with automatic 30-day cleanup
"""
import logging
import logging.handlers
from datetime import datetime, timedelta
from pathlib import Path
import glob
import os


class DailyRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    Custom handler that creates daily log files with YYYY-MM-DD naming
    and automatically cleans up files older than 30 days
    """
    
    def __init__(self, log_dir, log_type, retention_days=30):
        """
        Initialize daily rotating handler
        
        Args:
            log_dir: Directory for log files
            log_type: Type of log (debug, errors)
            retention_days: Days to retain log files (default 30)
        """
        self.log_dir = Path(log_dir)
        self.log_type = log_type
        self.retention_days = retention_days
        
        # Create log directory if it doesn't exist
        self.log_dir.mkdir(exist_ok=True, parents=True)
        
        # Generate current log filename
        current_date = datetime.now().strftime('%Y-%m-%d')
        log_filename = self.log_dir / f"{current_date}_{log_type}.log"
        
        # Initialize parent with daily rotation at midnight
        super().__init__(
            filename=str(log_filename),
            when='midnight',
            interval=1,
            backupCount=retention_days,
            encoding='utf-8'
        )
        
        # Clean up old log files immediately
        self._cleanup_old_logs()
    
    def doRollover(self):
        """
        Override to use YYYY-MM-DD naming instead of default suffix
        """
        if self.stream:
            self.stream.close()
            self.stream = None
        
        # Generate new filename with current date
        current_date = datetime.now().strftime('%Y-%m-%d')
        new_filename = self.log_dir / f"{current_date}_{self.log_type}.log"
        self.baseFilename = str(new_filename)
        
        # Clean up old files
        self._cleanup_old_logs()
        
        if not self.delay:
            self.stream = self._open()
    
    def _cleanup_old_logs(self):
        """Remove log files older than retention_days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=self.retention_days)
            pattern = str(self.log_dir / f"*_{self.log_type}.log")
            
            for log_file in glob.glob(pattern):
                log_path = Path(log_file)
                filename = log_path.stem
                
                # Extract date from filename (YYYY-MM-DD_type format)
                try:
                    date_part = filename.split(f'_{self.log_type}')[0]
                    file_date = datetime.strptime(date_part, '%Y-%m-%d')
                    
                    if file_date < cutoff_date:
                        os.remove(log_file)
                        print(f"Removed old log file: {log_file}")
                        
                except (ValueError, IndexError):
                    # Skip files that don't match expected format
                    continue
                    
        except Exception as e:
            print(f"Warning: Could not cleanup old log files: {e}")


def setup_daily_rotating_logging(log_dir="logs"):
    """
    Setup daily rotating logging system with organized folder structure and automatic cleanup
    
    Returns:
        logging.Logger: Configured main logger
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(exist_ok=True, parents=True)
    
    # Create organized subdirectories
    (log_dir / "debug").mkdir(exist_ok=True)
    (log_dir / "errors").mkdir(exist_ok=True)
    (log_dir / "alert_manager").mkdir(exist_ok=True)
    (log_dir / "trading").mkdir(exist_ok=True)
    (log_dir / "parsing_feedback").mkdir(exist_ok=True)
    
    # Get main logger
    main_logger = logging.getLogger('main')
    main_logger.setLevel(logging.DEBUG)
    
    # Clear existing handlers
    main_logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Daily rotating debug handler (organized into debug folder)
    debug_handler = DailyRotatingFileHandler(log_dir / "debug", 'debug', retention_days=30)
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(debug_handler)
    
    # Daily rotating error handler (organized into errors folder)
    error_handler = DailyRotatingFileHandler(log_dir / "errors", 'errors', retention_days=30)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(error_handler)
    
    # Console handler (for immediate visibility)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    simple_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(simple_formatter)
    main_logger.addHandler(console_handler)
    
    # Setup root logger to catch everything from all modules
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Add daily rotating handler to root logger for debug folder
    root_debug_handler = DailyRotatingFileHandler(log_dir / "debug", 'debug', retention_days=30)
    root_debug_handler.setLevel(logging.DEBUG)
    root_debug_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(root_debug_handler)
    
    # Filter out broker API noise from debug logs
    _filter_broker_noise(main_logger, root_logger)
    
    # Setup specialized loggers
    _setup_specialized_loggers(log_dir, detailed_formatter)
    
    # Setup backward compatibility
    setup_backward_compatible_logging(log_dir)
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    main_logger.info("="*50)
    main_logger.info("Enhanced daily rotating logging system initialized")
    main_logger.info(f"Debug log: {log_dir}/debug/{current_date}_debug.log")
    main_logger.info(f"Error log: {log_dir}/errors/{current_date}_errors.log")
    main_logger.info(f"Trading log: {log_dir}/trading/{current_date}_trading.log")
    main_logger.info(f"Alert Manager log: {log_dir}/alert_manager/{current_date}_alert_manager.log")
    main_logger.info(f"Retention: {30} days with automatic cleanup")
    main_logger.info("="*50)
    
    return main_logger


def _filter_broker_noise(main_logger, root_logger):
    """
    Filter out RobinStocks and broker API noise by setting their loggers to WARNING level
    """
    robinstocks_api_loggers = [
        'robin_stocks',
        'robin_stocks.robinhood',
        'robin_stocks.authentication',
        'robin_stocks.orders',
        'robin_stocks.options',
        'requests.packages.urllib3',
        'urllib3.connectionpool',
        'urllib3',
        'requests',
        'pyotp',
        'discord',
        'openai'
    ]
    
    for logger_name in robinstocks_api_loggers:
        noisy_logger = logging.getLogger(logger_name)
        noisy_logger.setLevel(logging.WARNING)
        main_logger.info(f"RobinStocks logger '{logger_name}' filtered to WARNING level")


def _setup_specialized_loggers(log_dir, detailed_formatter):
    """
    Setup specialized loggers for different components with organized folder structure
    """
    # Trading-specific logger
    trading_logger = logging.getLogger('trading')
    trading_logger.setLevel(logging.INFO)
    trading_handler = DailyRotatingFileHandler(log_dir / "trading", 'trading', retention_days=30)
    trading_handler.setLevel(logging.INFO)
    trading_handler.setFormatter(detailed_formatter)
    trading_logger.addHandler(trading_handler)
    
    # Alert manager logger
    alert_logger = logging.getLogger('alert_manager')
    alert_logger.setLevel(logging.INFO)
    alert_handler = DailyRotatingFileHandler(log_dir / "alert_manager", 'alert_manager', retention_days=30)
    alert_handler.setLevel(logging.INFO)
    alert_handler.setFormatter(detailed_formatter)
    alert_logger.addHandler(alert_handler)


def get_organized_logger(component_name):
    """
    Get a logger for a specific component that will write to the organized structure
    
    Args:
        component_name: Name of the component (trading, alert_manager, etc.)
        
    Returns:
        logging.Logger: Logger configured for the component
    """
    return logging.getLogger(component_name)


def setup_backward_compatible_logging(log_dir="logs"):
    """
    Maintain backward compatibility with existing log file references
    Creates symlinks from old flat structure to new organized structure
    
    Args:
        log_dir: Base log directory
    """
    log_dir = Path(log_dir)
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Create backward compatibility symlinks for existing code
    compatibility_mappings = {
        f"{current_date}_debug.log": f"debug/{current_date}_debug.log",
        f"{current_date}_errors.log": f"errors/{current_date}_errors.log",
        "trading_main.log": f"trading/{current_date}_trading.log",
        "alert_manager.log": f"alert_manager/{current_date}_alert_manager.log"
    }
    
    for old_path, new_path in compatibility_mappings.items():
        old_file = log_dir / old_path
        new_file = log_dir / new_path
        
        # Remove existing symlink if it exists
        if old_file.is_symlink():
            old_file.unlink()
        
        # Create symlink if target exists (only create links to existing files)
        if new_file.exists() and not old_file.exists():
            try:
                old_file.symlink_to(new_path)
            except OSError:
                # On systems that don't support symlinks, copy the file instead
                pass


if __name__ == "__main__":
    # Test the daily rotation system
    logger = setup_daily_rotating_logging("test_logs")
    
    logger.info("Testing daily rotating logging system")
    logger.error("Testing error logging")
    logger.debug("Testing debug logging")
    
    print("Daily rotation logging test complete")
