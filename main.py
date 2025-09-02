# main.py - Discord Client with Enhanced Logging and Debugging
# Test edit by Claude to demonstrate direct code modification capabilities
import os
import sys
import asyncio
import discord
import traceback
import time
import threading
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path

from config import *
from alert_manager import ResilientAlertManager
from trade_executor import TradeExecutor
from performance_tracker import EnhancedPerformanceTracker
from position_manager import EnhancedPositionManager
from trader import EnhancedRobinhoodTrader, EnhancedSimulatedTrader

# Import all channel parsers
from channels.sean import SeanParser
from channels.will import WillParser
from channels.eva import EvaParser
from channels.ryan import RyanParser
from channels.fifi import FiFiParser
from channels.price_parser import PriceParser

# Load Environment
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_USER_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Global Configuration
SIM_MODE = False
TESTING_MODE = False
DEBUG_MODE = True

# Channel IDs
LIVE_COMMAND_CHANNEL_ID = 1401792635483717747

# Auto-restart configuration
MAX_RESTART_ATTEMPTS = 5
restart_count = 0
last_restart_time = None

# ============= ENHANCED LOGGING SETUP =============
class LoggingPrintRedirect:
    """Redirects print statements to both console and log file"""
    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level
        self.terminal = sys.stdout
        self.line_buffer = ""
        
    def write(self, message):
        # Write to terminal
        self.terminal.write(message)
        
        # Buffer until we have a complete line
        self.line_buffer += message
        
        # If we have a newline, log the complete line
        if '\n' in self.line_buffer:
            lines = self.line_buffer.split('\n')
            # Log all complete lines
            for line in lines[:-1]:
                if line.strip():  # Don't log empty lines
                    self.logger.log(self.level, line.strip())
            # Keep any incomplete line in the buffer
            self.line_buffer = lines[-1]
    
    def flush(self):
        if self.line_buffer.strip():
            self.logger.log(self.level, self.line_buffer.strip())
            self.line_buffer = ""
        if hasattr(self.terminal, 'flush'):
            self.terminal.flush()

def setup_comprehensive_logging():
    """Setup comprehensive logging that captures everything"""
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Setup main logger
    main_logger = logging.getLogger('main')
    main_logger.setLevel(logging.DEBUG)
    
    # Clear existing handlers
    main_logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler for debug.log (everything)
    debug_handler = logging.FileHandler(log_dir / "debug.log", encoding='utf-8')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(debug_handler)
    
    # File handler for errors.log (errors only)
    error_handler = logging.FileHandler(log_dir / "errors.log", encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(error_handler)
    
    # Console handler (for immediate visibility)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    simple_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(simple_formatter)
    main_logger.addHandler(console_handler)
    
    # Setup root logger to catch everything
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Add file handler to root logger to catch all module logs
    root_debug_handler = logging.FileHandler(log_dir / "debug.log", encoding='utf-8')
    root_debug_handler.setLevel(logging.DEBUG)
    root_debug_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(root_debug_handler)
    
    # Redirect print statements to logger
    sys.stdout = LoggingPrintRedirect(main_logger, logging.INFO)
    sys.stderr = LoggingPrintRedirect(main_logger, logging.ERROR)
    
    main_logger.info("="*50)
    main_logger.info("Comprehensive logging system initialized")
    main_logger.info(f"Debug log: {log_dir / 'debug.log'}")
    main_logger.info(f"Error log: {log_dir / 'errors.log'}")
    main_logger.info("="*50)
    
    return main_logger

# Initialize logging before anything else
logger = setup_comprehensive_logging()

# ============= END LOGGING SETUP =============

class MessageEditTracker:
    def __init__(self):
        self.processed_messages = {}
        self.lock = asyncio.Lock()
        
    async def mark_processed(self, message_id: str, action: str, order_id: str = None):
        async with self.lock:
            self.processed_messages[message_id] = {
                'action': action,
                'order_id': order_id,
                'timestamp': datetime.now(timezone.utc),
                'trade_id': None
            }
    
    async def get_processed_info(self, message_id: str):
        async with self.lock:
            return self.processed_messages.get(message_id)

class ChannelHandlerManager:
    def __init__(self, openai_client):
        self.openai_client = openai_client
        self.handlers = {}
        
    def update_handlers(self, testing_mode: bool):
        """Build channel handlers dynamically based on mode"""
        self.handlers.clear()
        
        for name, config in CHANNELS_CONFIG.items():
            parser_class_name = config.get("parser")
            if parser_class_name in globals():
                parser_class = globals()[parser_class_name]
                
                channel_id = config.get("test_id") if testing_mode else config.get("live_id")
                
                if channel_id:
                    parser_instance = parser_class(
                        self.openai_client, channel_id, {**config, "name": name}
                    )
                    self.handlers[channel_id] = parser_instance
        
        mode = "TESTING" if testing_mode else "PRODUCTION"
        logger.info(f"Handlers updated for {mode} mode: {list(self.handlers.keys())}")
        
    def get_handler(self, channel_id: int):
        return self.handlers.get(channel_id)

class EnhancedDiscordClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        logger.info("Initializing Enhanced Discord Client")
        
        try:
            # Initialize core systems
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
            logger.info("OpenAI client initialized")
            
            # Initialize managers
            self.alert_manager = ResilientAlertManager()
            logger.info("Alert manager initialized")
            
            self.performance_tracker = EnhancedPerformanceTracker()
            logger.info("Performance tracker initialized")
            
            self.position_manager = EnhancedPositionManager("tracked_contracts_live.json")
            logger.info("Position manager initialized")
            
            # Initialize traders
            self.live_trader = EnhancedRobinhoodTrader()
            logger.info("Live trader initialized")
            
            self.sim_trader = EnhancedSimulatedTrader()
            logger.info("Simulated trader initialized")
            
            # Initialize handlers and utilities
            self.channel_manager = ChannelHandlerManager(self.openai_client)
            self.price_parser = PriceParser(self.openai_client)
            self.edit_tracker = MessageEditTracker()
            
            # Initialize trade executor with proper event loop reference
            self.trade_executor = TradeExecutor(
                self.live_trader, 
                self.sim_trader,
                self.performance_tracker,
                self.position_manager,
                self.alert_manager
            )
            logger.info("Trade executor initialized")
            
            # System state
            self.start_time = datetime.now(timezone.utc)
            self.heartbeat_task = None
            self.connection_lost_count = 0
            self.last_ready_time = None
            
            logger.info("Discord client initialization complete")
            
        except Exception as e:
            logger.error(f"Failed to initialize Discord client: {e}", exc_info=True)
            raise
        
    async def on_ready(self):
        """Called when Discord connection is established"""
        logger.info(f"Discord client ready: {self.user}")
        self.last_ready_time = datetime.now(timezone.utc)
        self.connection_lost_count = 0  # Reset on successful connection
        
        try:
            # Start alert system
            await self.alert_manager.start()
            logger.info("Alert system started")
            
            # Update channel handlers
            self.channel_manager.update_handlers(TESTING_MODE)
            
            # Start heartbeat task
            if not self.heartbeat_task or self.heartbeat_task.done():
                self.heartbeat_task = asyncio.create_task(self._heartbeat_task())
                logger.info("Heartbeat task started")
            
            # Send startup notification
            await self._send_startup_notification()
            
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)
    
    async def on_resumed(self):
        """Called when Discord resumes after disconnection"""
        logger.info("Discord connection resumed - checking services...")
        
        try:
            # Check and restart alert system if needed
            metrics = await self.alert_manager.get_metrics()
            if not metrics.get('is_running'):
                logger.warning("Alert system stopped during disconnect - restarting...")
                await self.alert_manager.start()
            else:
                # Verify processors are alive
                if not metrics.get('primary_alive') or not metrics.get('backup_alive'):
                    logger.warning("Dead alert processors detected - restarting...")
                    await self.alert_manager.emergency_restart()
            
            # Restart heartbeat if needed
            if not self.heartbeat_task or self.heartbeat_task.done():
                logger.warning("Heartbeat task dead - restarting...")
                self.heartbeat_task = asyncio.create_task(self._heartbeat_task())
            
            # Send reconnection notification
            reconnect_embed = {
                "title": "🔄 Bot Reconnected",
                "description": "Discord session resumed, all services checked",
                "color": 0x00ff00,
                "fields": [
                    {
                        "name": "Status",
                        "value": "✅ Alert system verified\n✅ Heartbeat active\n✅ All services operational",
                        "inline": False
                    },
                    {
                        "name": "Connection Info",
                        "value": f"**Disconnection Count:** {self.connection_lost_count}\n**Session Age:** {(datetime.now(timezone.utc) - self.start_time).total_seconds() / 3600:.1f} hours",
                        "inline": False
                    }
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            await self.alert_manager.add_alert(
                HEARTBEAT_WEBHOOK,
                {"embeds": [reconnect_embed]},
                "reconnection",
                priority=1
            )
            
            logger.info("All services verified after reconnection")
            
        except Exception as e:
            logger.error(f"Error in on_resumed: {e}", exc_info=True)
    
    async def on_disconnect(self):
        """Called when Discord disconnects"""
        self.connection_lost_count += 1
        logger.warning(f"Discord disconnected (count: {self.connection_lost_count})")
        
        # Don't stop services on normal disconnects - Discord will reconnect
        # Only force restart if too many disconnections
        if self.connection_lost_count > 10:
            logger.error("Too many disconnections - forcing restart")
            sys.exit(1)  # This will trigger the restart logic

    async def _heartbeat_task(self):
        """Send periodic heartbeat to dedicated heartbeat channel"""
        while True:
            try:
                await asyncio.sleep(1800)  # Every 30 minutes
                
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split('.')[0]
                
                # Get current metrics
                queue_metrics = await self.alert_manager.get_metrics()
                recent_trades = self.performance_tracker.get_recent_trades(5)
                
                heartbeat_embed = {
                    "title": "💓 RHTB v4 Enhanced Heartbeat",
                    "description": "Bot is alive and running normally",
                    "color": 0x00ff00,
                    "fields": [
                        {
                            "name": "🕐 System Status",
                            "value": f"""
**Uptime:** {uptime_str}
**Started:** {self.start_time.strftime('%H:%M UTC')}
**Current Time:** {datetime.now(timezone.utc).strftime('%H:%M UTC')}
**Disconnections:** {self.connection_lost_count}
                            """,
                            "inline": True
                        },
                        {
                            "name": "⚙️ Configuration",
                            "value": f"""
**Simulation:** {'ON' if SIM_MODE else 'OFF'}
**Testing Mode:** {'ON' if TESTING_MODE else 'OFF'}
**Active Channels:** {len(self.channel_manager.handlers)}
                            """,
                            "inline": True
                        },
                        {
                            "name": "📊 Activity",
                            "value": f"""
**Alert Queue:** {queue_metrics.get('queue_size_current', 0)} pending
**Success Rate:** {queue_metrics.get('success_rate', 0):.1f}%
**Recent Trades:** {len(recent_trades)}
                            """,
                            "inline": True
                        }
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "Automatic heartbeat every 30 minutes"}
                }
                
                await self.alert_manager.add_alert(
                    HEARTBEAT_WEBHOOK, 
                    {"embeds": [heartbeat_embed]}, 
                    "heartbeat"
                )
                
                logger.info("Heartbeat sent successfully")
                
            except asyncio.CancelledError:
                logger.info("Heartbeat task cancelled")
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait a minute before retrying

    async def on_message(self, message):
        """Enhanced message handling with proper async context"""
        try:
            # Handle commands
            if message.channel.id == LIVE_COMMAND_CHANNEL_ID and message.content.startswith('!'):
                await self._handle_command(message)
                return

            # Handle trading messages
            handler = self.channel_manager.get_handler(message.channel.id)
            if handler:
                logger.info(f"Message received from {handler.name}: {message.content[:100]}...")
                
                # Extract message content
                message_meta, raw_msg = self._extract_message_content(message, handler)
                
                if raw_msg:
                    # Log to live feed
                    await self._send_live_feed_alert(handler, raw_msg)
                    
                    # Process trade with proper async context
                    received_ts = datetime.now(timezone.utc)
                    await self.trade_executor.process_trade(
                        handler, message_meta, raw_msg, SIM_MODE, received_ts, 
                        str(message.id), False, self.loop
                    )
                    
        except Exception as e:
            logger.error(f"Message handling error: {e}", exc_info=True)
            await self.alert_manager.send_error_alert(f"Message handling error: {e}")

    async def on_message_edit(self, before, after):
        """Handle message edits"""
        try:
            if before.content == after.content and before.embeds == after.embeds:
                return
                
            handler = self.channel_manager.get_handler(after.channel.id)
            if handler:
                logger.info(f"Message edit detected in {handler.name}")
                
                processed_info = await self.edit_tracker.get_processed_info(str(after.id))
                if processed_info:
                    message_meta, raw_msg = self._extract_message_content(after, handler)
                    
                    if raw_msg:
                        received_ts = datetime.now(timezone.utc)
                        await self.trade_executor.process_trade(
                            handler, message_meta, raw_msg, SIM_MODE, received_ts, 
                            str(after.id), True, self.loop
                        )
                        
        except Exception as e:
            logger.error(f"Edit handling error: {e}", exc_info=True)

    def _extract_message_content(self, message, handler):
        """Extract message content for processing"""
        try:
            current_embed_title = ""
            current_embed_desc = ""
            
            if message.embeds:
                embed = message.embeds[0]
                current_embed_title = embed.title or ""
                current_embed_desc = embed.description or ""
            
            current_content = message.content or ""
            current_full_text = f"Title: {current_embed_title}\nDesc: {current_embed_desc}" if current_embed_title else current_content
            
            # Handle replies
            if message.reference and isinstance(message.reference.resolved, discord.Message):
                original_msg = message.reference.resolved
                original_embed_title = ""
                original_embed_desc = ""
                
                if original_msg.embeds:
                    orig_embed = original_msg.embeds[0]
                    original_embed_title = orig_embed.title or ""
                    original_embed_desc = orig_embed.description or ""
                
                original_content = original_msg.content or ""
                original_full_text = f"Title: {original_embed_title}\nDesc: {original_embed_desc}" if original_embed_title else original_content
                
                message_meta = (current_full_text, original_full_text)
                raw_msg = f"Reply: '{current_full_text}'\nOriginal: '{original_full_text}'"
            else:
                message_meta = (current_embed_title, current_embed_desc) if current_embed_title else current_content
                raw_msg = current_full_text
            
            return message_meta, raw_msg
            
        except Exception as e:
            logger.error(f"Content extraction error: {e}", exc_info=True)
            return None, ""

    async def _send_live_feed_alert(self, handler, content):
        """Send message to live feed"""
        try:
            live_feed_embed = {
                "author": {"name": f"{handler.name}'s Channel"},
                "description": content[:2000],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "color": handler.color,
                "footer": {"text": "TESTING MODE" if TESTING_MODE else "PRODUCTION"}
            }
            await self.alert_manager.add_alert(
                LIVE_FEED_WEBHOOK, {"embeds": [live_feed_embed]}, "live_feed"
            )
            
        except Exception as e:
            logger.error(f"Live feed alert error: {e}", exc_info=True)

    async def _handle_command(self, message):
        """Enhanced command handling with all commands"""
        try:
            global SIM_MODE, TESTING_MODE, DEBUG_MODE
            
            content = message.content
            parts = content.split()
            command = parts[0].lower()
            
            logger.info(f"Command received: {command}")
            
            if command == "!sim":
                if len(parts) > 1 and parts[1] in ["on", "true"]:
                    SIM_MODE = True
                    response = "✅ **Simulation Mode is now ON.** Orders will be simulated."
                elif len(parts) > 1 and parts[1] in ["off", "false"]:
                    SIM_MODE = False
                    response = "🚨 **Simulation Mode is now OFF.** Orders will be sent to live broker."
                else:
                    response = "Usage: `!sim on` or `!sim off`"
                
                logger.info(f"Simulation mode changed to: {SIM_MODE}")
                await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": response}, "command_response")
            
            elif command == "!testing":
                if len(parts) > 1 and parts[1] in ["on", "true"]:
                    TESTING_MODE = True
                    response = "✅ **Testing Mode is now ON.** Listening to SIMULATED channels."
                elif len(parts) > 1 and parts[1] in ["off", "false"]:
                    TESTING_MODE = False
                    response = "🚨 **Testing Mode is now OFF.** Listening to LIVE channels."
                else:
                    response = "Usage: `!testing on` or `!testing off`"
                
                logger.info(f"Testing mode changed to: {TESTING_MODE}")
                await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": response}, "command_response")
                await asyncio.sleep(1)
                self.channel_manager.update_handlers(TESTING_MODE)
            
            elif command == "!status":
                await self._handle_status_command()
                
            elif command == "!alert_health":
                await self._handle_alert_health_command()
                
            elif command == "!alert_restart":
                await self._handle_alert_restart_command()
                
            elif command == "!alert_test":
                await self._handle_alert_test_command()
                
            elif command == "!heartbeat":
                await self._handle_heartbeat_command()
                
            elif command == "!help":
                await self._handle_help_command()
                
            elif command == "!getprice":
                query = content[len("!getprice"):].strip()
                if query:
                    await self._handle_get_price(query)
                else:
                    await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                        "content": "Usage: `!getprice <options contract query>`\nExample: `!getprice $SPY 500c this friday`"
                    }, "command_response")
            
            elif command == "!positions":
                await self._handle_positions_command()
                
            elif command == "!portfolio":
                await self._handle_portfolio_command()
                
            elif command == "!trades":
                await self._handle_trades_command()
                
            elif command == "!queue":
                await self._handle_queue_command()
                
            elif command == "!mintick":
                query = content[len("!mintick"):].strip()
                if query:
                    await self._handle_mintick_command(query)
                else:
                    await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                        "content": "Usage: `!mintick <ticker symbol>`\nExample: `!mintick SPY` or `!mintick TSLA`"
                    }, "command_response")
                      
            else:
                await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                    "content": f"Unknown command: {command}. Use `!help` for available commands."
                }, "command_response")
                
        except Exception as e:
            logger.error(f"Command handling error: {e}", exc_info=True)
            await self.alert_manager.send_error_alert(f"Command error: {e}")

    async def _handle_status_command(self):
        """Handle status command"""
        queue_metrics = await self.alert_manager.get_metrics()
        
        status_embed = {
            "title": "📊 RHTB v4 Enhanced Status",
            "color": 0x00ff00,
            "fields": [
                {
                    "name": "🔧 Configuration",
                    "value": f"""
**Simulation:** {'ON' if SIM_MODE else 'OFF'}
**Testing:** {'ON' if TESTING_MODE else 'OFF'}
**Debug:** {'ON' if DEBUG_MODE else 'OFF'}
**Channels:** {len(self.channel_manager.handlers)}
**Restarts:** {restart_count}/{MAX_RESTART_ATTEMPTS}
                    """,
                    "inline": True
                },
                {
                    "name": "📨 Alert System",
                    "value": f"""
**Health:** {queue_metrics.get('health_status', 'Unknown')}
**Success Rate:** {queue_metrics.get('success_rate', 0):.1f}%
**Queue Size:** {queue_metrics.get('queue_size_current', 0)}
**Processors:** {queue_metrics.get('active_processors', 0)}
                    """,
                    "inline": True
                },
                {
                    "name": "🔄 Connection",
                    "value": f"""
**Discord:** Connected
**Robinhood:** {await self._check_robinhood_connection()}
**Disconnections:** {self.connection_lost_count}
**Session Age:** {(datetime.now(timezone.utc) - self.start_time).total_seconds() / 3600:.1f}h
                    """,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [status_embed]}, "command_response")

    async def _check_robinhood_connection(self):
        """Check Robinhood connection status"""
        try:
            if SIM_MODE:
                return "🟢 SIMULATED"
            
            # Test connection by getting portfolio value
            portfolio_value = await self._get_portfolio_async()
            if portfolio_value is not None:
                return f"🟢 Connected (${portfolio_value:,.2f})"
            else:
                return "🔴 Failed"
        except Exception as e:
            return f"🔴 Error: {str(e)[:20]}..."

    async def _get_portfolio_async(self):
        """Get portfolio value asynchronously"""
        try:
            # Use thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            portfolio_value = await loop.run_in_executor(
                None, 
                self.live_trader.get_portfolio_value
            )
            return portfolio_value
        except Exception:
            return None

    async def _handle_alert_health_command(self):
        """Handle alert health command"""
        health_data = await self.alert_manager.get_health_status()
        
        color = 0x00ff00 if health_data.get('status') == 'HEALTHY' else 0xff8800 if health_data.get('status') == 'WARNING' else 0xff0000
        
        health_embed = {
            "title": f"🏥 Alert System Health - {health_data.get('status', 'UNKNOWN')}",
            "color": color,
            "fields": [
                {
                    "name": "📊 Processor Status",
                    "value": f"""
**Primary:** {'🟢 Running' if health_data.get('primary_alive') else '🔴 Dead'}
**Backup:** {'🟢 Running' if health_data.get('backup_alive') else '🔴 Dead'}
**Circuit Breaker:** {health_data.get('circuit_state', 'Unknown')}
                    """,
                    "inline": True
                },
                {
                    "name": "📈 Metrics",
                    "value": f"""
**Successful Alerts:** {health_data.get('successful_alerts', 0)}
**Failed Alerts:** {health_data.get('failed_alerts', 0)}
**Restarts:** {health_data.get('restarts', 0)}
**Last Alert:** {health_data.get('last_alert_age', 'Unknown')}s ago
                    """,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [health_embed]}, "command_response")

    async def _handle_alert_restart_command(self):
        """Handle alert restart command"""
        try:
            await self.alert_manager.emergency_restart()
            
            restart_embed = {
                "title": "🔄 Alert System Emergency Restart",
                "description": "Alert system has been restarted successfully",
                "color": 0x00ff00,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [restart_embed]}, "command_response")
            
        except Exception as e:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                "content": f"❌ Failed to restart alert system: {e}"
            }, "command_response")

    async def _handle_alert_test_command(self):
        """Handle alert test command"""
        test_embed = {
            "title": "🧪 Alert System Test",
            "description": "This is a test notification to verify the alert system is working correctly.",
            "color": 0x3498db,
            "fields": [
                {
                    "name": "Test Details",
                    "value": f"""
**Timestamp:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
**Command:** !alert_test
**Status:** ✅ Success
                    """,
                    "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Alert system is functioning normally"}
        }
        
        await self.alert_manager.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [test_embed]}, "test_alert")

    async def _handle_heartbeat_command(self):
        """Handle manual heartbeat command"""
        uptime = datetime.now(timezone.utc) - self.start_time
        uptime_str = str(uptime).split('.')[0]
        
        queue_metrics = await self.alert_manager.get_metrics()
        recent_trades = self.performance_tracker.get_recent_trades(5)
        
        # Get memory/system info if possible
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()
            system_info = f"**Memory:** {memory_mb:.1f} MB\n**CPU:** {cpu_percent:.1f}%"
        except:
            system_info = "**System info:** Not available"
        
        heartbeat_embed = {
            "title": "💓 RHTB v4 Enhanced Manual Heartbeat",
            "description": "Comprehensive system health check",
            "color": 0x00ff00,
            "fields": [
                {
                    "name": "🕐 Uptime & Timing",
                    "value": f"""
**Current Uptime:** {uptime_str}
**Started At:** {self.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Current Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
**Restarts:** {restart_count}/{MAX_RESTART_ATTEMPTS}
                    """,
                    "inline": False
                },
                {
                    "name": "⚙️ Configuration Status",
                    "value": f"""
**Simulation Mode:** {'🟢 ON' if SIM_MODE else '🔴 OFF (LIVE TRADING)'}
**Testing Mode:** {'🟡 ON (Test Channels)' if TESTING_MODE else '🟢 OFF (Live Channels)'}
**Debug Mode:** {'🟢 ON' if DEBUG_MODE else '🔴 OFF'}
**Active Channels:** {len(self.channel_manager.handlers)}
**Disconnections:** {self.connection_lost_count}
                   """,
                   "inline": True
                },
                {
                   "name": "📊 Performance Metrics",
                   "value": f"""
**Alert Queue Size:** {queue_metrics.get('queue_size_current', 0)}
**Total Alerts Sent:** {queue_metrics.get('total_alerts', 0)}
**Alert Success Rate:** {queue_metrics.get('success_rate', 0):.1f}%
**Recent Trades:** {len(recent_trades)} completed
**Processing Status:** {'🟢 Active' if queue_metrics.get('is_running') else '🔴 Stopped'}
                   """,
                   "inline": True
                },
                {
                   "name": "🖥️ System Resources",
                   "value": system_info,
                   "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Manual heartbeat requested"}
        }
        
        # Add recent trades info if available
        if recent_trades:
            trades_text = ""
            for trade in recent_trades[:3]:
                pnl_emoji = "🟢" if trade.get('pnl_percent', 0) > 0 else "🔴"
                pnl = trade.get('pnl_percent', 0)
                trades_text += f"{pnl_emoji} {trade['ticker']}: {pnl:+.1f}%\n"
            
            heartbeat_embed["fields"].append({
                "name": "💹 Recent Trades",
                "value": trades_text,
                "inline": True
            })
        
        await self.alert_manager.add_alert(HEARTBEAT_WEBHOOK, {"embeds": [heartbeat_embed]}, "manual_heartbeat")
        logger.info("Manual heartbeat command executed")

    async def _handle_help_command(self):
        """Handle help command"""
        help_embed = {
            "title": "🛠️ RHTB v4 Enhanced Commands",
            "description": """
**System Controls:**
`!sim on|off` - Toggle simulation mode
`!testing on|off` - Toggle testing channels
`!status` - System status overview
`!heartbeat` - Detailed health check

**Alert System:**
`!alert_health` - Alert system diagnostics
`!alert_restart` - Force restart alert processors
`!alert_test` - Send test notification
`!queue` - Alert queue status

**Trading:**
`!getprice <query>` - Get option market price
`!mintick <symbol>` - Get minimum tick size for symbol
`!positions` - Show current positions
`!portfolio` - Show portfolio value
`!trades` - Recent trade performance

**🛡️ Enhanced Features:**
- Auto-restart on crash (max 5 attempts)
- Auto-recovery after Discord disconnects
- Resilient alert system with circuit breaker
- Channel-isolated position tracking
- Real-time health monitoring
- Comprehensive logging to debug.log & errors.log
            """,
            "color": 0x3498db
        }
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [help_embed]}, "command_response")

    async def _handle_get_price(self, query: str):
        """Handle getprice command"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, 
                                            {"content": f"⏳ Parsing and fetching price for: `{query}`..."}, 
                                            "command_response")

        def blocking_parse_and_fetch():
            def parser_logger(msg, level="INFO"):
                logger.info(f"PriceParser: {msg}")

            parsed_contract = self.price_parser.parse_query(query, parser_logger)

            if not parsed_contract:
                return {"error": "Could not understand the contract details."}

            ticker = parsed_contract.get('ticker')
            strike = parsed_contract.get('strike')
            opt_type = parsed_contract.get('type')
            expiration = parsed_contract.get('expiration')

            if not all([ticker, strike, opt_type, expiration]):
                missing = [k for k, v in {'ticker': ticker, 'strike': strike, 'type': opt_type, 'expiration': expiration}.items() if not v]
                return {"error": f"Missing details: `{', '.join(missing)}`"}

            trader = self.live_trader if not SIM_MODE else self.sim_trader
            market_data = trader.get_option_market_data(ticker, expiration, strike, opt_type)
            
            market_data_dict = None
            if market_data and isinstance(market_data, list):
                if market_data[0] and isinstance(market_data[0], list):
                    if len(market_data[0]) > 0 and market_data[0][0] and isinstance(market_data[0][0], dict):
                        market_data_dict = market_data[0][0]
                elif market_data[0] and isinstance(market_data[0], dict):
                    market_data_dict = market_data[0]

            if not market_data_dict:
                return {"error": f"No market data found for {ticker.upper()} ${strike} {opt_type.upper()} {expiration}"}
            
            return {"success": True, "data": market_data_dict, "parsed": parsed_contract}

        result = await self.loop.run_in_executor(None, blocking_parse_and_fetch)

        if "error" in result:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"❌ {result['error']}"}, "command_response")
        else:
            data = result['data']
            parsed = result['parsed']
            
            bid = float(data.get('bid_price', 0) or 0)
            ask = float(data.get('ask_price', 0) or 0)
            mark = float(data.get('mark_price', 0) or 0)
            volume = int(data.get('volume', 0) or 0)
            open_interest = int(data.get('open_interest', 0) or 0)
            
            price_embed = {
                "title": f"📊 {parsed.get('ticker').upper()} ${parsed.get('strike')} {parsed.get('type').upper()}",
                "description": f"**Expiration:** {parsed.get('expiration')}",
                "color": 15105642,
                "fields": [
                    {"name": "Mark Price", "value": f"${mark:.2f}", "inline": True},
                    {"name": "Bid Price", "value": f"${bid:.2f}", "inline": True},
                    {"name": "Ask Price", "value": f"${ask:.2f}", "inline": True},
                    {"name": "Spread", "value": f"${(ask - bid):.2f}", "inline": True},
                    {"name": "Volume", "value": f"{volume:,}", "inline": True},
                    {"name": "Open Interest", "value": f"{open_interest:,}", "inline": True}
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [price_embed]}, "command_response")

    async def _handle_positions_command(self):
        """Handle positions command"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching live account positions..."}, "command_response")
        
        def get_positions_sync():
            try:
                positions = self.live_trader.get_open_option_positions()
                if not positions:
                    return "No open option positions."
                
                holdings = []
                for p in positions:
                    try:
                        instrument_data = self.live_trader.get_option_instrument_data(p['option'])
                        if instrument_data:
                            holdings.append(f"• {p['chain_symbol']} {instrument_data['expiration_date']} {instrument_data['strike_price']}{instrument_data['type'].upper()[0]} x{int(float(p['quantity']))}")
                    except Exception as e:
                        logger.error(f"Could not process a position: {e}")
                
                return "\n".join(holdings) if holdings else "No processable option positions found."
            except Exception as e:
                logger.error(f"Error retrieving holdings: {e}", exc_info=True)
                return f"Error retrieving holdings: {e}"
        
        pos_string = await self.loop.run_in_executor(None, get_positions_sync)
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"**Current Positions:**\n```\n{pos_string}\n```"}, "command_response")

    async def _handle_portfolio_command(self):
        """Handle portfolio command"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching live account portfolio value..."}, "command_response")
        
        def get_portfolio_sync():
            return self.live_trader.get_portfolio_value()
        
        portfolio_value = await self.loop.run_in_executor(None, get_portfolio_sync)
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"💰 **Total Portfolio Value:** ${portfolio_value:,.2f}"}, "command_response")

    async def _handle_trades_command(self):
        """Handle trades command"""
        recent_trades = self.performance_tracker.get_recent_trades(10)
        
        if recent_trades:
            trades_text = ""
            for trade in recent_trades[:5]:
                pnl_emoji = "🟢" if trade.get('pnl_percent', 0) > 0 else "🔴"
                trades_text += f"{pnl_emoji} {trade['ticker']}: {trade.get('pnl_percent', 0):+.1f}%\n"
            
            trades_embed = {
                "title": "📊 Recent Trades",
                "description": trades_text,
                "color": 0x00ff00,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        else:
            trades_embed = {
                "title": "📊 Recent Trades",
                "description": "No completed trades found",
                "color": 0x888888
            }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [trades_embed]}, "command_response")

    async def _handle_queue_command(self):
        """Handle queue command"""
        metrics = await self.alert_manager.get_metrics()
        
        queue_embed = {
            "title": "📊 Alert Queue Status",
            "color": 0x00ff00 if metrics.get('success_rate', 0) > 90 else 0xff8800,
            "fields": [
                {
                    "name": "📈 Metrics",
                    "value": f"""
**Total Processed:** {metrics.get('total_alerts', 0)}
**Success Rate:** {metrics.get('success_rate', 0):.1f}%
**Current Queue:** {metrics.get('queue_size_current', 0)}
**Processing:** {'Yes' if metrics.get('is_running') else 'No'}
                    """,
                    "inline": True
                }
            ]
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [queue_embed]}, "command_response")

    async def _handle_mintick_command(self, query: str):
        """Handle mintick command to get minimum tick size for a symbol"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, 
                                            {"content": f"⏳ Fetching minimum tick size for: `{query}`..."}, 
                                            "command_response")

        def get_tick_size_sync():
            try:
                # Normalize the symbol
                symbol = query.upper().strip()
                
                # Use the live trader's tick size method
                trader = self.live_trader if not SIM_MODE else self.sim_trader
                tick_size = trader.get_instrument_tick_size(symbol)
                
                if tick_size is None or tick_size <= 0:
                    return {"error": f"Could not determine tick size for {symbol}. Symbol may not exist or may not be tradeable."}
                
                # Get additional info if possible
                try:
                    from config import get_broker_symbol
                    broker_symbol = get_broker_symbol(symbol)
                    
                    # Try to get instrument info for additional context
                    instruments = None
                    if hasattr(trader, 'logged_in') and trader.logged_in:
                        try:
                            import robin_stocks.robinhood as r
                            instruments = r.get_instruments_by_symbols(broker_symbol)
                        except:
                            instruments = None
                    
                    additional_info = {}
                    if instruments and isinstance(instruments, list) and len(instruments) > 0:
                        inst = instruments[0]
                        additional_info = {
                            'name': inst.get('simple_name', inst.get('name', 'N/A')),
                            'tradeable': inst.get('tradeable', 'Unknown'),
                            'type': inst.get('type', 'Unknown')
                        }
                    
                    return {
                        "success": True, 
                        "symbol": symbol,
                        "broker_symbol": broker_symbol,
                        "tick_size": tick_size,
                        "info": additional_info
                    }
                    
                except Exception as e:
                    # Still return tick size even if we can't get additional info
                    return {
                        "success": True,
                        "symbol": symbol,
                        "tick_size": tick_size,
                        "info": {}
                    }
                    
            except Exception as e:
                logger.error(f"Error getting tick size for {query}: {e}", exc_info=True)
                return {"error": f"Error fetching tick size: {str(e)}"}

        result = await self.loop.run_in_executor(None, get_tick_size_sync)

        if "error" in result:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"❌ {result['error']}"}, "command_response")
        else:
            symbol = result['symbol']
            tick_size = result['tick_size']
            info = result.get('info', {})
            
            # Create embed with tick size information
            embed = {
                "title": f"📏 Minimum Tick Size - {symbol}",
                "description": f"**Minimum tick size:** ${tick_size:.4f}".rstrip('0').rstrip('.'),
                "color": 0x00ff00,
                "fields": [
                    {
                        "name": "Tick Size Details",
                        "value": f"""
**Symbol:** {symbol}
**Min Tick:** ${tick_size:.4f}
**Decimal Places:** {len(str(tick_size).split('.')[-1])}
                        """.strip(),
                        "inline": True
                    }
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Tick size determines minimum price increments for trading"}
            }
            
            # Add additional info if available
            if info.get('name'):
                embed["fields"].append({
                    "name": "Instrument Info",
                    "value": f"""
**Name:** {info.get('name', 'N/A')}
**Tradeable:** {info.get('tradeable', 'Unknown')}
**Type:** {info.get('type', 'Unknown')}
                    """.strip(),
                    "inline": True
                })
            
            # Add usage examples
            trader = self.live_trader if not SIM_MODE else self.sim_trader
            example_prices = []
            for base_price in [10.00, 50.00, 100.00]:
                rounded_up = trader.round_to_tick(base_price + tick_size/2, symbol, round_up_for_buy=True)
                rounded_down = trader.round_to_tick(base_price + tick_size/2, symbol, round_up_for_buy=False)
                example_prices.append(f"${base_price:.2f} → ↑${rounded_up:.4f}".rstrip('0').rstrip('.') + f" ↓${rounded_down:.4f}".rstrip('0').rstrip('.'))
            
            embed["fields"].append({
                "name": "Price Rounding Examples",
                "value": "\n".join(example_prices[:2]),
                "inline": False
            })
            
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [embed]}, "command_response")

    async def _send_startup_notification(self):
        """Send enhanced startup notification to heartbeat channel"""
        startup_embed = {
            "title": "🚀 RHTB v4 Enhanced - System Online",
            "color": 0x00ff00,
            "fields": [
                {
                    "name": "🔧 Configuration",
                    "value": f"""
**Simulation:** {'ON' if SIM_MODE else 'OFF'}
**Testing Mode:** {'ON' if TESTING_MODE else 'OFF'}
**Active Channels:** {len(self.channel_manager.handlers)}
**Restart Count:** {restart_count}/{MAX_RESTART_ATTEMPTS}
                    """,
                    "inline": True
                },
                {
                    "name": "🛡️ Enhanced Features",
                    "value": """
**Auto-Restart:** ✅ Enabled
**Reconnect Handler:** ✅ Active
**Alert Recovery:** ✅ Ready
**Health Monitor:** ✅ Running
**Comprehensive Logging:** ✅ Active
                    """,
                    "inline": True
                },
                {
                    "name": "📁 Logging System",
                    "value": f"""
**Debug Log:** logs/debug.log
**Error Log:** logs/errors.log
**Analytics DB:** logs/debug_analytics.db
**All print() statements:** ✅ Captured
                    """,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(HEARTBEAT_WEBHOOK, {"embeds": [startup_embed]}, "startup", priority=3)

    async def close(self):
        """Clean shutdown"""
        logger.info("Shutting down Discord client...")
        
        # Cancel heartbeat task
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        # Stop alert manager
        await self.alert_manager.stop()
        
        # Call parent close
        await super().close()

# Main entry point with auto-restart logic
if __name__ == "__main__":
    while True:
        try:
            logger.info("="*50)
            logger.info("Starting RHTB v4 Enhanced...")
            logger.info(f"Restart attempt: {restart_count}/{MAX_RESTART_ATTEMPTS}")
            
            # Track restart frequency
            current_time = datetime.now()
            if last_restart_time:
                time_since_last = current_time - last_restart_time
                if time_since_last < timedelta(minutes=5):
                    logger.warning("Restarting too frequently - waiting 30 seconds")
                    time.sleep(30)
            
            last_restart_time = current_time
            
            logger.info(f"Settings: SIM_MODE={SIM_MODE}, TESTING_MODE={TESTING_MODE}, DEBUG_MODE={DEBUG_MODE}")
            
            logger.info("Enhanced Features Active:")
            logger.info("   ✅ Auto-restart on crash (max 5 attempts)")
            logger.info("   ✅ Auto-recovery after Discord disconnects")
            logger.info("   ✅ Resilient alert system with circuit breaker")
            logger.info("   ✅ Channel-isolated position tracking")
            logger.info("   ✅ Real-time health monitoring")
            logger.info("   ✅ Comprehensive logging to files")
            logger.info("")
            logger.info("Automatic Risk Management Active:")
            logger.info(f"   ⏱️ Delayed stop loss: {STOP_LOSS_DELAY_SECONDS/60:.0f} minutes after buy")
            logger.info("   📉 Initial stop loss: 50% protection")
            logger.info("   📈 Trailing stops: 20% on partial exits")
            logger.info("   🎯 Market-based exit pricing")
            logger.info("   ⚡ Enhanced order monitoring with auto-cancel")
            logger.info("="*50)
            
            # Create and run the bot
            client = EnhancedDiscordClient()
            
            # This runs the bot - it will block here during normal operation
            client.run(DISCORD_TOKEN)
            
            # If we get here, bot exited normally
            logger.info("Bot exited normally")
            break
            
        except discord.errors.LoginFailure as e:
            # Don't restart on auth failures
            logger.error(f"Discord login failed: {e}")
            print(f"❌ Discord login failed: {e}")
            print("Check your Discord token in .env file!")
            sys.exit(1)
            
        except KeyboardInterrupt:
            # User stopped the bot
            logger.info("Bot stopped by user")
            print("\n👋 Bot stopped by user")
            sys.exit(0)
            
        except asyncio.CancelledError:
            # Normal asyncio cancellation - might be from Discord reconnect
            logger.warning("Async tasks cancelled - this is usually normal")
            continue
            
        except Exception as e:
            # Actual crash - this triggers restart
            logger.error(f"Bot crashed with error: {e}", exc_info=True)
            
            # Log crash to file
            try:
                with open("crash_log.txt", "a") as f:
                    f.write(f"\n{'='*50}\n")
                    f.write(f"Crash at {datetime.now()}\n")
                    f.write(f"Error: {e}\n")
                    f.write(f"Traceback:\n{traceback.format_exc()}\n")
            except:
                pass
            
            restart_count += 1
            if restart_count > MAX_RESTART_ATTEMPTS:
                logger.error(f"Max restarts ({MAX_RESTART_ATTEMPTS}) reached")
                print(f"❌ Max restarts ({MAX_RESTART_ATTEMPTS}) reached")
                print("Check crash_log.txt and logs/errors.log for details")
                sys.exit(1)
            
            logger.info(f"Restarting in 10 seconds (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})...")
            time.sleep(10)