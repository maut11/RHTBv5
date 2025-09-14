#!/usr/bin/env python3
"""
Log Cleanup Utility for RobinStocks Trading Bot
Removes RobinStocks API noise from existing log files to reduce size and improve readability
"""

import re
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple
import argparse


class LogCleanupUtility:
    """Standalone utility to clean existing log files of broker API noise"""
    
    def __init__(self):
        """Initialize the cleanup utility with RobinStocks noise patterns"""
        
        # Define RobinStocks API noise patterns
        self.robinstocks_noise_patterns = [
            # RobinStocks specific noise
            r'.*robin_stocks.*DEBUG.*',
            r'.*robin_stocks\.robinhood.*DEBUG.*',
            r'.*robin_stocks\.authentication.*DEBUG.*',
            r'.*robin_stocks\.orders.*DEBUG.*',
            r'.*robin_stocks\.options.*DEBUG.*',
            
            # HTTP/Network noise
            r'.*requests.*DEBUG.*Connection pool is full.*',
            r'.*urllib3.*DEBUG.*',
            r'.*urllib3\.connectionpool.*DEBUG.*',
            r'.*requests\.packages\.urllib3.*DEBUG.*',
            
            # Authentication noise
            r'.*pyotp.*DEBUG.*',
            
            # Discord bot noise (if applicable)
            r'.*discord.*DEBUG.*',
            
            # OpenAI noise
            r'.*openai.*DEBUG.*',
            
            # General HTTP noise patterns
            r'.*HTTP/1\.1.*DEBUG.*',
            r'.*Connection pool.*DEBUG.*',
            r'.*Starting new HTTP.*DEBUG.*',
            r'.*Resetting dropped connection.*DEBUG.*'
        ]
        
        # Compile patterns for better performance
        self.compiled_patterns = [re.compile(pattern) for pattern in self.robinstocks_noise_patterns]
        
        self.stats = {
            'files_processed': 0,
            'lines_removed': 0,
            'bytes_saved': 0,
            'processing_errors': 0
        }
    
    def is_broker_noise(self, line: str) -> bool:
        """
        Check if a line matches RobinStocks API noise patterns
        
        Args:
            line: Log line to check
            
        Returns:
            bool: True if line is noise, False otherwise
        """
        line_stripped = line.strip()
        return any(pattern.match(line_stripped) for pattern in self.compiled_patterns)
    
    def clean_log_file(self, input_file: Path, output_file: Path = None, dry_run: bool = False) -> Dict[str, int]:
        """
        Clean a single log file of broker API noise
        
        Args:
            input_file: Path to input log file
            output_file: Path to output file (None = overwrite original)
            dry_run: If True, don't write changes, just count what would be removed
            
        Returns:
            dict: Statistics about the cleaning operation
        """
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        # Use original file if no output specified
        if output_file is None:
            output_file = input_file
        
        stats = {
            'original_lines': 0,
            'cleaned_lines': 0,
            'lines_removed': 0,
            'original_size': 0,
            'cleaned_size': 0,
            'bytes_saved': 0
        }
        
        # Get original file size
        stats['original_size'] = input_file.stat().st_size
        
        try:
            cleaned_lines = []
            
            with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    stats['original_lines'] += 1
                    
                    if not self.is_broker_noise(line):
                        cleaned_lines.append(line)
                        stats['cleaned_lines'] += 1
                    else:
                        stats['lines_removed'] += 1
            
            # Write cleaned content if not dry run
            if not dry_run:
                # Create output directory if needed
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.writelines(cleaned_lines)
                
                # Get cleaned file size
                stats['cleaned_size'] = output_file.stat().st_size
            else:
                # Estimate cleaned size for dry run
                stats['cleaned_size'] = sum(len(line.encode('utf-8')) for line in cleaned_lines)
            
            stats['bytes_saved'] = stats['original_size'] - stats['cleaned_size']
            
            return stats
            
        except Exception as e:
            self.stats['processing_errors'] += 1
            raise Exception(f"Error processing {input_file}: {str(e)}")
    
    def clean_directory(self, log_dir: Path, pattern: str = "*.log", dry_run: bool = False) -> Dict[str, any]:
        """
        Clean all log files in a directory matching the pattern
        
        Args:
            log_dir: Directory containing log files
            pattern: File pattern to match (e.g., "*.log")
            dry_run: If True, don't write changes
            
        Returns:
            dict: Overall statistics
        """
        if not log_dir.exists() or not log_dir.is_dir():
            raise ValueError(f"Invalid log directory: {log_dir}")
        
        log_files = list(log_dir.glob(pattern))
        if not log_files:
            print(f"No log files found matching pattern '{pattern}' in {log_dir}")
            return self.stats
        
        print(f"Found {len(log_files)} log files to process...")
        
        for log_file in log_files:
            try:
                print(f"Processing: {log_file.name}", end="")
                
                file_stats = self.clean_log_file(log_file, dry_run=dry_run)
                
                self.stats['files_processed'] += 1
                self.stats['lines_removed'] += file_stats['lines_removed']
                self.stats['bytes_saved'] += file_stats['bytes_saved']
                
                # Print file-specific results
                if file_stats['lines_removed'] > 0:
                    size_mb = file_stats['bytes_saved'] / (1024 * 1024)
                    print(f" -> Removed {file_stats['lines_removed']} lines, saved {size_mb:.2f}MB")
                else:
                    print(" -> No noise found")
                
            except Exception as e:
                print(f" -> Error: {str(e)}")
        
        return self.stats
    
    def print_summary(self, dry_run: bool = False):
        """Print summary of cleaning operation"""
        action = "Would remove" if dry_run else "Removed"
        
        print(f"\n{'='*50}")
        print(f"Log Cleanup Summary ({'DRY RUN' if dry_run else 'COMPLETED'})")
        print(f"{'='*50}")
        print(f"Files processed: {self.stats['files_processed']}")
        print(f"Lines {action.lower()}: {self.stats['lines_removed']:,}")
        print(f"Bytes saved: {self.stats['bytes_saved'] / (1024*1024):.2f} MB")
        
        if self.stats['processing_errors'] > 0:
            print(f"Processing errors: {self.stats['processing_errors']}")
        
        print(f"{'='*50}")


def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(
        description="Clean RobinStocks API noise from trading bot log files"
    )
    
    parser.add_argument(
        "log_path",
        type=str,
        help="Path to log file or directory to clean"
    )
    
    parser.add_argument(
        "--pattern",
        type=str,
        default="*.log",
        help="File pattern for directory mode (default: *.log)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files"
    )
    
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process directories recursively"
    )
    
    args = parser.parse_args()
    
    # Initialize cleanup utility
    cleaner = LogCleanupUtility()
    log_path = Path(args.log_path)
    
    try:
        if log_path.is_file():
            # Single file mode
            print(f"Cleaning single file: {log_path}")
            stats = cleaner.clean_log_file(log_path, dry_run=args.dry_run)
            
            cleaner.stats['files_processed'] = 1
            cleaner.stats['lines_removed'] = stats['lines_removed']
            cleaner.stats['bytes_saved'] = stats['bytes_saved']
            
        elif log_path.is_dir():
            # Directory mode
            print(f"Cleaning directory: {log_path}")
            
            if args.recursive:
                pattern = f"**/{args.pattern}"
            else:
                pattern = args.pattern
                
            cleaner.clean_directory(log_path, pattern, dry_run=args.dry_run)
            
        else:
            print(f"Error: Path not found: {log_path}")
            sys.exit(1)
        
        # Print summary
        cleaner.print_summary(dry_run=args.dry_run)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()