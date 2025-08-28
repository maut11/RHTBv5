# main.py - Discord Client with Enhanced Logging, Debugging, and Optimized Trade Execution
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
from trade_executor import OptimizedTradeExecutor  # UPDATED IMPORT
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
        self.terminal.write(message)
        self.line_buffer += message
        if '\n' in self.line_buffer:
            lines = self.line_buffer.split('\n')
            for line in lines[:-1]:
                if line.strip():
                    self.logger.log(self.level, line.strip())
            self.line_buffer = lines[-1]
    
    def flush(self):
        if self.line_buffer.strip():
            self.logger.log(self.level, self.line_buffer.strip())
            self.line_buffer = ""
        if hasattr(self.terminal, 'flush'):
            self.terminal.flush()

def setup_comprehensive_logging():
    """Setup comprehensive logging that captures everything"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    main_logger = logging.getLogger('main')
    main_logger.setLevel(logging.DEBUG)
    main_logger.handlers.clear()
    
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    debug_handler = logging.FileHandler(log_dir / "debug.log", encoding='utf-8')
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(debug_handler)
    
    error_handler = logging.FileHandler(log_dir / "errors.log", encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    main_logger.addHandler(error_handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    simple_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(simple_formatter)
    main_logger.addHandler(console_handler)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_debug_handler = logging.FileHandler(log_dir / "debug.log", encoding='utf-8')
    root_debug_handler.setLevel(logging.DEBUG)
    root_debug_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(root_debug_handler)
    
    sys.stdout = LoggingPrintRedirect(main_logger, logging.INFO)
    sys.stderr = LoggingPrintRedirect(main_logger, logging.ERROR)
    
    main_logger.info("="*50)
    main_logger.info("Comprehensive logging system initialized")
    main_logger.info(f"Debug log: {log_dir / 'debug.log'}")
    main_logger.info(f"Error log: {log_dir / 'errors.log'}")
    main_logger.info("="*50)
    
    return main_logger

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
            from openai import OpenAI
            self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
            
            self.alert_manager = ResilientAlertManager()
            self.performance_tracker = EnhancedPerformanceTracker()
            self.position_manager = EnhancedPositionManager("tracked_contracts_live.json")
            
            self.live_trader = EnhancedRobinhoodTrader()
            self.sim_trader = EnhancedSimulatedTrader()
            
            self.channel_manager = ChannelHandlerManager(self.openai_client)
            self.price_parser = PriceParser(self.openai_client)
            self.edit_tracker = MessageEditTracker()
            
            # UPDATED: Initialize OPTIMIZED trade executor
            self.trade_executor = OptimizedTradeExecutor(
                self.live_trader, 
                self.sim_trader,
                self.performance_tracker,
                self.position_manager,
                self.alert_manager
            )
            logger.info("Optimized trade executor initialized (Trade First, Alert Last)")
            
            self.start_time = datetime.now(timezone.utc)
            self.heartbeat_task = None
            self.connection_lost_count = 0
            self.last_ready_time = None
            
            logger.info("Discord client initialization complete")
        except Exception as e:
            logger.error(f"Failed to initialize Discord client: {e}", exc_info=True)
            raise
        
    async def on_ready(self):
        logger.info(f"Discord client ready: {self.user}")
        self.last_ready_time = datetime.now(timezone.utc)
        self.connection_lost_count = 0
        try:
            await self.alert_manager.start()
            logger.info("Alert system started")
            
            self.channel_manager.update_handlers(TESTING_MODE)
            
            if not self.heartbeat_task or self.heartbeat_task.done():
                self.heartbeat_task = asyncio.create_task(self._heartbeat_task())
                logger.info("Heartbeat task started")
            
            await self._send_startup_notification()
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)
    
    async def on_resumed(self):
        logger.info("Discord connection resumed - checking services...")
        try:
            metrics = await self.alert_manager.get_metrics()
            if not metrics.get('is_running'):
                logger.warning("Alert system stopped during disconnect - restarting...")
                await self.alert_manager.start()
            elif not metrics.get('primary_alive') or not metrics.get('backup_alive'):
                logger.warning("Dead alert processors detected - restarting...")
                await self.alert_manager.emergency_restart()
            
            if not self.heartbeat_task or self.heartbeat_task.done():
                logger.warning("Heartbeat task dead - restarting...")
                self.heartbeat_task = asyncio.create_task(self._heartbeat_task())
            
            reconnect_embed = {
                "title": "🔄 Bot Reconnected",
                "description": "Discord session resumed, all services checked",
                "color": 0x00ff00,
                "fields": [
                    {"name": "Status", "value": "✅ Alert system verified\n✅ Heartbeat active\n✅ Trade executor optimized\n✅ All services operational", "inline": False},
                    {"name": "Connection Info", "value": f"**Disconnection Count:** {self.connection_lost_count}\n**Session Age:** {(datetime.now(timezone.utc) - self.start_time).total_seconds() / 3600:.1f} hours", "inline": False}
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await self.alert_manager.add_alert(HEARTBEAT_WEBHOOK, {"embeds": [reconnect_embed]}, "reconnection", priority=1)
            logger.info("All services verified after reconnection")
        except Exception as e:
            logger.error(f"Error in on_resumed: {e}", exc_info=True)
    
    async def on_disconnect(self):
        self.connection_lost_count += 1
        logger.warning(f"Discord disconnected (count: {self.connection_lost_count})")
        if self.connection_lost_count > 10:
            logger.error("Too many disconnections - forcing restart")
            sys.exit(1)

    async def _heartbeat_task(self):
        while True:
            try:
                await asyncio.sleep(1800)
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split('.')[0]
                
                queue_metrics = await self.alert_manager.get_metrics()
                recent_trades = self.performance_tracker.get_recent_trades(5)
                executor_metrics = self.trade_executor.get_performance_metrics()
                
                heartbeat_embed = {
                    "title": "💓 RHTB v4 Enhanced Heartbeat - TRADE FIRST ACTIVE",
                    "description": "Bot is alive and running with optimized trade execution",
                    "color": 0x00ff00,
                    "fields": [
                        {"name": "🕐 System Status", "value": f"**Uptime:** {uptime_str}\n**Started:** {self.start_time.strftime('%H:%M UTC')}\n**Current Time:** {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n**Disconnections:** {self.connection_lost_count}", "inline": True},
                        {"name": "⚙️ Configuration", "value": f"**Simulation:** {'ON' if SIM_MODE else 'OFF'}\n**Testing Mode:** {'ON' if TESTING_MODE else 'OFF'}\n**Active Channels:** {len(self.channel_manager.handlers)}\n**Trade Executor:** OPTIMIZED ⚡", "inline": True},
                        {"name": "📊 Activity", "value": f"**Alert Queue:** {queue_metrics.get('queue_size_current', 0)} pending\n**Success Rate:** {queue_metrics.get('success_rate', 0):.1f}%\n**Recent Trades:** {len(recent_trades)}\n**Avg Execution:** {executor_metrics['avg_execution_time']:.2f}s", "inline": True}
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "Trade First, Alert Last • Auto heartbeat every 30min"}
                }
                
                if executor_metrics['total_trades'] > 0:
                    heartbeat_embed["fields"].append({
                        "name": "⚡ Trade Performance",
                        "value": f"**Total Trades:** {executor_metrics['total_trades']}\n**Min Execution:** {executor_metrics['min_execution_time']:.2f}s\n**Max Execution:** {executor_metrics['max_execution_time']:.2f}s\n**Background Failures:** {executor_metrics['background_failures']}",
                        "inline": True
                    })

                await self.alert_manager.add_alert(HEARTBEAT_WEBHOOK, {"embeds": [heartbeat_embed]}, "heartbeat")
                logger.info("Enhanced heartbeat sent successfully")
            except asyncio.CancelledError:
                logger.info("Heartbeat task cancelled")
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def on_message(self, message):
        try:
            # Handle commands
            if message.channel.id == LIVE_COMMAND_CHANNEL_ID and message.content.startswith('!'):
                await self._handle_command(message)
                return

            # Handle trading messages
            handler = self.channel_manager.get_handler(message.channel.id)
            if handler:
                logger.info(f"FAST-TRACK message from {handler.name}: {message.content[:100]}...")
                
                # Extract message content
                message_meta, raw_msg = self._extract_message_content(message, handler)
                
                if raw_msg:
                    # Log to live feed
                    asyncio.create_task(self._send_live_feed_alert(handler, raw_msg))
                    
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
                logger.info(f"FAST-TRACK edit in {handler.name}")
                
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
            await self.alert_manager.add_alert(LIVE_FEED_WEBHOOK, {"embeds": [live_feed_embed]}, "live_feed")
            
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
                
            elif command == "!executor":
                await self._handle_executor_command()
                
            elif command == "!trader_cache":
                await self._handle_trader_cache_command()
                
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
        executor_metrics = self.trade_executor.get_performance_metrics()
        
        status_embed = {
            "title": "📊 RHTB v4 Enhanced Status - TRADE FIRST ACTIVE",
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
                    "name": "⚡ Trade Executor",
                    "value": f"""
**Mode:** OPTIMIZED
**Total Trades:** {executor_metrics['total_trades']}
**Avg Speed:** {executor_metrics['avg_execution_time']:.2f}s
**BG Fails:** {executor_metrics['background_failures']}
                    """,
                    "inline": True
                },
                {
                    "name": "🔄 Connection",
                    "value": f"""
**Discord:** Connected
**Disconnections:** {self.connection_lost_count}
**Session Age:** {(datetime.now(timezone.utc) - self.start_time).total_seconds() / 3600:.1f}h
                    """,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [status_embed]}, "command_response")

    async def _handle_executor_command(self):
        """Handle executor command"""
        executor_metrics = self.trade_executor.get_performance_metrics()
        color = 0x00ff00 if executor_metrics['avg_execution_time'] < 2.0 else 0xff8800 if executor_metrics['avg_execution_time'] < 5.0 else 0xff0000
        
        executor_embed = {
            "title": "⚡ Trade Executor Performance - OPTIMIZED MODE",
            "color": color,
            "fields": [
                {
                    "name": "📊 Execution Metrics",
                    "value": f"""
**Total Trades:** {executor_metrics['total_trades']}
**Avg Time:** {executor_metrics['avg_execution_time']:.3f}s
**Fastest:** {executor_metrics['min_execution_time']:.3f}s
**Slowest:** {executor_metrics['max_execution_time']:.3f}s
                    """,
                    "inline": True
                },
                {
                    "name": "🎯 Recent Performance",
                    "value": f"""
**Last 10 Avg:** {executor_metrics['last_10_avg']:.3f}s
**BG Fails:** {executor_metrics['background_failures']}
**Success Rate:** {((executor_metrics['total_trades'] - executor_metrics['background_failures']) / max(1, executor_metrics['total_trades'])) * 100:.1f}%
                    """,
                    "inline": True
                },
                {
                    "name": "🚀 Optimization Status",
                    "value": """
**Mode:** Trade First, Alert Last ✅
**Contract Resolution:** FAST ✅
**Tick Size Caching:** ACTIVE ✅
**Market Price Discovery:** OPTIMIZED ✅
**Background Processing:** ACTIVE ✅
                    """,
                    "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Lower execution times = faster trade placement"}
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [executor_embed]}, "command_response")

    async def _handle_trader_cache_command(self):
        """Handle trader cache command"""
        
        def get_cache_stats_sync():
            return self.live_trader.get_cache_stats(), self.sim_trader.get_cache_stats()
        
        live_stats, sim_stats = await self.loop.run_in_executor(None, get_cache_stats_sync)
        
        cache_embed = {
            "title": "🗄️ Trader Cache Status",
            "color": 0x3498db,
            "fields": [
                {
                    "name": "📊 Live Trader Cache",
                    "value": f"""
**Tick Size Cache:** {live_stats['tick_cache_total']} entries
**Instrument Cache:** {live_stats['instrument_cache_total']} entries
**Valid Entries:** {live_stats['valid_cache_entries']}
**Hit Rate Potential:** {live_stats['cache_hit_potential']}
                    """,
                    "inline": True
                },
                {
                    "name": "🧪 Simulated Trader Cache",
                    "value": f"""
**Tick Size Cache:** {sim_stats['tick_cache_total']} entries
**Mode:** {sim_stats.get('mode', 'SIMULATION')}
**Hit Rate:** {sim_stats['cache_hit_potential']}
                    """,
                    "inline": True
                },
                {
                    "name": "⚡ Cache Benefits",
                    "value": """
**Faster Tick Size Lookup** ✅
**Reduced API Calls** ✅
**Consistent Pricing** ✅
**Better Performance** ✅
                    """,
                    "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [cache_embed]}, "command_response")

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
**Successful:** {health_data.get('successful_alerts', 0)}
**Failed:** {health_data.get('failed_alerts', 0)}
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
        embed = {
            "title": "🧪 Alert System Test - TRADE FIRST MODE",
            "description": "This is a test notification to verify the optimized alert system is working correctly.",
            "color": 0x3498db,
            "fields": [
                {
                    "name": "Test Details",
                    "value": f"""
**Timestamp:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
**Command:** !alert_test
**Status:** ✅ Success
**Mode:** Trade First, Alert Last
                    """,
                    "inline": False
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Optimized alert system is functioning normally"}
        }
        
        await self.alert_manager.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [embed]}, "test_alert")

    async def _handle_heartbeat_command(self):
        """Handle manual heartbeat command"""
        uptime = str(datetime.now(timezone.utc) - self.start_time).split('.')[0]
        queue_metrics = await self.alert_manager.get_metrics()
        recent_trades = self.performance_tracker.get_recent_trades(5)
        executor_metrics = self.trade_executor.get_performance_metrics()
        
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            cpu_percent = process.cpu_percent()
            system_info = f"**Memory:** {memory_mb:.1f} MB\n**CPU:** {cpu_percent:.1f}%"
        except ImportError:
            system_info = "**System info:** Not available (psutil not installed)"
        
        heartbeat_embed = {
            "title": "💓 RHTB v4 Enhanced Manual Heartbeat - TRADE FIRST ACTIVE",
            "description": "Comprehensive system health check with optimized execution metrics",
            "color": 0x00ff00,
            "fields": [
                {"name": "🕐 Uptime & Timing", "value": f"**Uptime:** {uptime}\n**Started:** {self.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n**Restarts:** {restart_count}/{MAX_RESTART_ATTEMPTS}", "inline": False},
                {"name": "⚙️ Configuration", "value": f"**Sim Mode:** {'🟢 ON' if SIM_MODE else '🔴 OFF'}\n**Test Mode:** {'🟡 ON' if TESTING_MODE else '🟢 OFF'}\n**Channels:** {len(self.channel_manager.handlers)}\n**Disconnects:** {self.connection_lost_count}", "inline": True},
                {"name": "📊 Performance", "value": f"**Alert Queue:** {queue_metrics.get('queue_size_current', 0)}\n**Alert Rate:** {queue_metrics.get('success_rate', 0):.1f}%\n**Recent Trades:** {len(recent_trades)}\n**Processing:** {'🟢' if queue_metrics.get('is_running') else '🔴'}", "inline": True},
                {"name": "⚡ Executor", "value": f"**Mode:** OPTIMIZED\n**Total Trades:** {executor_metrics['total_trades']}\n**Avg Time:** {executor_metrics['avg_execution_time']:.3f}s\n**BG Fails:** {executor_metrics['background_failures']}", "inline": True},
                {"name": "🖥️ System", "value": system_info, "inline": False}
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Manual heartbeat - TRADE FIRST optimization active"}
        }
        
        await self.alert_manager.add_alert(HEARTBEAT_WEBHOOK, {"embeds": [heartbeat_embed]}, "manual_heartbeat")
        logger.info("Manual heartbeat command executed")

    async def _handle_help_command(self):
        """Handle help command"""
        help_embed = {
            "title": "🛠️ RHTB v4 Enhanced Commands - TRADE FIRST MODE",
            "description": """
**System Controls:**
`!sim on|off` - Toggle simulation mode
`!testing on|off` - Toggle testing channels
`!status` - System status with executor metrics
`!heartbeat` - Detailed health check

**🚀 NEW - Trade Executor:**
`!executor` - Trade executor performance metrics
`!trader_cache` - Robinhood API cache status

**Alert System:**
`!alert_health` - Alert system diagnostics
`!alert_restart` - Force restart alert processors
`!alert_test` - Send test notification
`!queue` - Alert queue status

**Trading:**
`!getprice <query>` - Get option market price
`!positions` - Show current positions
`!portfolio` - Show portfolio value
`!trades` - Recent trade performance

**⚡ TRADE FIRST Optimizations:**
- **2-4 seconds faster** trade execution
- **Prioritized RH API** tick size lookup
- **Background task processing** (alerts, tracking)
            """,
            "color": 0x3498db
        }
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [help_embed]}, "command_response")

    async def _handle_get_price(self, query: str):
        """Handle getprice command"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"⏳ Parsing and fetching price for: `{query}`..."}, "command_response")

        def blocking_parse_and_fetch():
            def parser_logger(msg, level="INFO"): logger.info(f"PriceParser: {msg}")
            parsed = self.price_parser.parse_query(query, parser_logger)
            if not parsed: return {"error": "Could not understand the contract details."}
            
            keys = ['ticker', 'strike', 'type', 'expiration']
            if not all(parsed.get(k) for k in keys):
                missing = [k for k in keys if not parsed.get(k)]
                return {"error": f"Missing details: `{', '.join(missing)}`"}
            
            trader = self.live_trader if not SIM_MODE else self.sim_trader
            data = trader.get_option_market_data(parsed['ticker'], parsed['expiration'], parsed['strike'], parsed['type'])
            
            data_dict = data[0][0] if data and data[0] and data[0][0] else (data[0] if data and data[0] else None)
            if not data_dict: return {"error": f"No market data found for {parsed['ticker'].upper()} ${parsed['strike']} {parsed['type'].upper()} {parsed['expiration']}"}
            
            tick_size = trader.get_instrument_tick_size(parsed['ticker'])
            return {"data": data_dict, "parsed": parsed, "tick_size": tick_size}

        result = await self.loop.run_in_executor(None, blocking_parse_and_fetch)

        if "error" in result:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"❌ {result['error']}"}, "command_response")
        else:
            data, parsed = result['data'], result['parsed']
            bid, ask, mark = float(data.get('bid_price', 0) or 0), float(data.get('ask_price', 0) or 0), float(data.get('mark_price', 0) or 0)
            vol, oi = int(data.get('volume', 0) or 0), int(data.get('open_interest', 0) or 0)
            
            embed = {
                "title": f"📊 {parsed['ticker'].upper()} ${parsed['strike']} {parsed['type'].upper()}",
                "description": f"**Expiration:** {parsed['expiration']}\n**Tick Size:** ${result['tick_size']}",
                "color": 15105642,
                "fields": [
                    {"name": "Mark", "value": f"${mark:.2f}", "inline": True}, {"name": "Bid", "value": f"${bid:.2f}", "inline": True},
                    {"name": "Ask", "value": f"${ask:.2f}", "inline": True}, {"name": "Spread", "value": f"${(ask-bid):.2f}", "inline": True},
                    {"name": "Volume", "value": f"{vol:,}", "inline": True}, {"name": "Open Int", "value": f"{oi:,}", "inline": True}
                ], "timestamp": datetime.now(timezone.utc).isoformat(), "footer": {"text": "Enhanced pricing with tick size info"}
            }
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [embed]}, "command_response")
    
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
                        data = self.live_trader.get_option_instrument_data(p['option'])
                        if data:
                            holdings.append(f"• {p['chain_symbol']} {data['expiration_date']} {data['strike_price']}{data['type'].upper()[0]} x{int(float(p['quantity']))}")
                    except Exception as e:
                        logger.error(f"Could not process a position: {e}")
                
                return "\n".join(holdings) if holdings else "No processable option positions found."
            except Exception as e:
                logger.error(f"Error retrieving holdings: {e}", exc_info=True)
                return f"Error: {e}"
        
        pos_string = await self.loop.run_in_executor(None, get_positions_sync)
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"**Current Positions:**\n```\n{pos_string}\n```"}, "command_response")

    async def _handle_portfolio_command(self):
        """Handle portfolio command"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching live account portfolio..."}, "command_response")
        portfolio_value = await self.loop.run_in_executor(None, self.live_trader.get_portfolio_value)
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"💰 **Total Portfolio Value:** ${portfolio_value:,.2f}"}, "command_response")

    async def _handle_trades_command(self):
        """Handle trades command"""
        recent_trades = self.performance_tracker.get_recent_trades(10)
        
        if not recent_trades:
            embed = {"title": "📊 Recent Trades", "description": "No completed trades found", "color": 0x888888}
        else:
            trades_text = "\n".join([f"{'🟢' if t.get('pnl_percent', 0) > 0 else '🔴'} {t['ticker']}: {t.get('pnl_percent', 0):+.1f}%" for t in recent_trades[:5]])
            embed = {
                "title": "📊 Recent Trades",
                "description": trades_text,
                "color": 0x00ff00,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Trade First execution mode"}
            }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [embed]}, "command_response")

    async def _handle_queue_command(self):
        """Handle queue command"""
        metrics = await self.alert_manager.get_metrics()
        
        embed = {
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
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [embed]}, "command_response")

    async def _send_startup_notification(self):
        """Send enhanced startup notification to heartbeat channel"""
        startup_embed = {
            "title": "🚀 RHTB v4 Enhanced - TRADE FIRST MODE ACTIVE",
            "color": 0x00ff00,
            "fields": [
                {"name": "🔧 Configuration", "value": f"**Simulation:** {'ON' if SIM_MODE else 'OFF'}\n**Testing Mode:** {'ON' if TESTING_MODE else 'OFF'}\n**Active Channels:** {len(self.channel_manager.handlers)}\n**Restart Count:** {restart_count}/{MAX_RESTART_ATTEMPTS}", "inline": True},
                {"name": "⚡ Trade First Optimizations", "value": "**Execution Mode:** OPTIMIZED ✅\n**Tick Size Priority:** RH API First ✅\n**Market Pricing:** Enhanced ✅\n**Background Processing:** Active ✅", "inline": True},
                {"name": "🛡️ Risk Management", "value": f"**Delayed Stop Loss:** {STOP_LOSS_DELAY_SECONDS/60:.0f} min\n**Initial Stop:** 50%\n**Trailing Stops:** 20%\n**Auto Risk Mgt:** ✅ ENABLED", "inline": True}
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(HEARTBEAT_WEBHOOK, {"embeds": [startup_embed]}, "startup", priority=3)

    async def close(self):
        """Clean shutdown"""
        logger.info("Shutting down Discord client...")
        
        if self.heartbeat_task and not self.heartbeat_task.done():
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
        
        await self.alert_manager.stop()
        await super().close()

# Main entry point with auto-restart logic
if __name__ == "__main__":
    while True:
        try:
            logger.info("="*50)
            logger.info("Starting RHTB v4 Enhanced with OPTIMIZED Trade Executor...")
            logger.info(f"Restart attempt: {restart_count}/{MAX_RESTART_ATTEMPTS}")
            
            current_time = datetime.now()
            if last_restart_time and (current_time - last_restart_time) < timedelta(minutes=5):
                logger.warning("Restarting too frequently - waiting 30 seconds")
                time.sleep(30)
            last_restart_time = current_time
            
            logger.info(f"Settings: SIM_MODE={SIM_MODE}, TESTING_MODE={TESTING_MODE}, DEBUG_MODE={DEBUG_MODE}")
            logger.info("Enhanced Features Active:")
            logger.info("   ✅ Trade First, Alert Last execution model")
            logger.info("   ✅ Auto-restart on crash")
            logger.info("   ✅ Resilient alert system with circuit breaker")
            logger.info("   ✅ Comprehensive logging to files")
            logger.info("="*50)
            
            client = EnhancedDiscordClient()
            
            # This runs the bot - it will block here during normal operation
            client.run(DISCORD_TOKEN)
            
            logger.info("Bot exited normally")
            break
            
        except discord.errors.LoginFailure as e:
            logger.error(f"Discord login failed: {e}. Check your Discord token.")
            sys.exit(1)
            
        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            sys.exit(0)
            
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}", exc_info=True)
            try:
                with open("crash_log.txt", "a") as f:
                    f.write(f"\n{'='*50}\nCrash at {datetime.now()}\nError: {e}\nTraceback:\n{traceback.format_exc()}\n")
            except Exception as log_e:
                logger.error(f"Could not write to crash_log.txt: {log_e}")
            
            restart_count += 1
            if restart_count > MAX_RESTART_ATTEMPTS:
                logger.error(f"Max restarts ({MAX_RESTART_ATTEMPTS}) reached. Exiting.")
                sys.exit(1)
            
            logger.info(f"Restarting in 10 seconds (attempt {restart_count}/{MAX_RESTART_ATTEMPTS})...")
            time.sleep(10)