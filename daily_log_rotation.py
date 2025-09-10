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
    Setup daily rotating logging system with automatic cleanup
    
    Returns:
        logging.Logger: Configured main logger
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(exist_ok=True, parents=True)
    
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
    
    # Daily rotating debug handler
    debug_handler = DailyRotatingFileHandler(log_dir, 'debug', retention_days=30)
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(debug_handler)
    
    # Daily rotating error handler
    error_handler = DailyRotatingFileHandler(log_dir, 'errors', retention_days=30)
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
    
    # Add daily rotating handler to root logger
    root_debug_handler = DailyRotatingFileHandler(log_dir, 'debug', retention_days=30)
    root_debug_handler.setLevel(logging.DEBUG)
    root_debug_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(root_debug_handler)
    
    current_date = datetime.now().strftime('%Y-%m-%d')
    main_logger.info("="*50)
    main_logger.info("Daily rotating logging system initialized")
    main_logger.info(f"Debug log: {log_dir}/{current_date}_debug.log")
    main_logger.info(f"Error log: {log_dir}/{current_date}_errors.log")
    main_logger.info(f"Retention: {30} days with automatic cleanup")
    main_logger.info("="*50)
    
    return main_logger


if __name__ == "__main__":
    # Test the daily rotation system
    logger = setup_daily_rotating_logging("test_logs")
    
    logger.info("Testing daily rotating logging system")
    logger.error("Testing error logging")
    logger.debug("Testing debug logging")
    
    print("Daily rotation logging test complete")
