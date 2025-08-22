# main.py - Fixed Discord Client & Message Routing with All Commands
import os
import asyncio
import discord
from datetime import datetime, timezone
from dotenv import load_dotenv
import threading
import time

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
        print(f"✅ Handlers updated for {mode} mode: {list(self.handlers.keys())}")
        
    def get_handler(self, channel_id: int):
        return self.handlers.get(channel_id)

class EnhancedDiscordClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize core systems
        from openai import OpenAI
        self.openai_client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Initialize managers
        self.alert_manager = ResilientAlertManager()
        self.performance_tracker = EnhancedPerformanceTracker()
        self.position_manager = EnhancedPositionManager("tracked_contracts_live.json")
        
        # Initialize traders
        self.live_trader = EnhancedRobinhoodTrader()
        self.sim_trader = EnhancedSimulatedTrader()
        
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
        
        # System state
        self.start_time = datetime.now(timezone.utc)
        self.heartbeat_task = None
        
    async def on_ready(self):
        print(f"✅ Discord client ready: {self.user}")
        
        # Start alert system
        await self.alert_manager.start()
        
        # Update channel handlers
        self.channel_manager.update_handlers(TESTING_MODE)
        
        # Start heartbeat task
        if not self.heartbeat_task:
            self.heartbeat_task = asyncio.create_task(self._heartbeat_task())
            print("💓 Heartbeat task started (30min intervals)")
        
        # Send startup notification
        await self._send_startup_notification()

    async def _heartbeat_task(self):
        """Send periodic heartbeat to confirm bot is alive"""
        while True:
            try:
                await asyncio.sleep(1800)  # Every 30 minutes
                
                uptime = datetime.now(timezone.utc) - self.start_time
                uptime_str = str(uptime).split('.')[0]  # Remove microseconds
                
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
                    ALL_NOTIFICATION_WEBHOOK, 
                    {"embeds": [heartbeat_embed]}, 
                    "heartbeat"
                )
                
                print("💓 Heartbeat sent successfully")
                
            except Exception as e:
                print(f"❌ Heartbeat error: {e}")

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
                print(f"📨 Message received from {handler.name}: {message.content[:100]}...")
                
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
            print(f"❌ Message handling error: {e}")
            await self.alert_manager.send_error_alert(f"Message handling error: {e}")

    async def on_message_edit(self, before, after):
        """Handle message edits"""
        try:
            if before.content == after.content and before.embeds == after.embeds:
                return
                
            handler = self.channel_manager.get_handler(after.channel.id)
            if handler:
                print(f"📝 Message edit detected in {handler.name}")
                
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
            print(f"❌ Edit handling error: {e}")

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
            print(f"❌ Content extraction error: {e}")
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
            print(f"❌ Live feed alert error: {e}")

    async def _handle_command(self, message):
        """Enhanced command handling with all missing commands"""
        try:
            global SIM_MODE, TESTING_MODE, DEBUG_MODE
            
            content = message.content
            parts = content.split()
            command = parts[0].lower()
            
            print(f"🎮 Command received: {command}")
            
            if command == "!sim":
                if len(parts) > 1 and parts[1] in ["on", "true"]:
                    SIM_MODE = True
                    response = "✅ **Simulation Mode is now ON.** Orders will be simulated."
                elif len(parts) > 1 and parts[1] in ["off", "false"]:
                    SIM_MODE = False
                    response = "🚨 **Simulation Mode is now OFF.** Orders will be sent to live broker."
                else:
                    response = "Usage: `!sim on` or `!sim off`"
                
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
                    
            else:
                await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                    "content": f"Unknown command: {command}. Use `!help` for available commands."
                }, "command_response")
                
        except Exception as e:
            print(f"❌ Command handling error: {e}")
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
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [status_embed]}, "command_response")

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
        """Handle heartbeat command"""
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
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [heartbeat_embed]}, "manual_heartbeat")
        print("💓 Manual heartbeat command executed")

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
`!positions` - Show current positions
`!portfolio` - Show portfolio value
`!trades` - Recent trade performance

**🛡️ Enhanced Features:**
• Resilient alert system with auto-recovery
• Channel-isolated position tracking
• Comprehensive error handling
• Real-time health monitoring
• Automatic stop loss management
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
                print(f"[{level}] PriceParser: {msg}")

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
                        print(f"Could not process a position: {e}")
                
                return "\n".join(holdings) if holdings else "No processable option positions found."
            except Exception as e:
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
**Processing:** {'Yes' if metrics.get('is_processing') else 'No'}
                    """,
                    "inline": True
                }
            ]
        }
        
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [queue_embed]}, "command_response")

    async def _send_startup_notification(self):
        """Send enhanced startup notification"""
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
                    """,
                    "inline": True
                },
                {
                    "name": "🛡️ Enhanced Features",
                    "value": """
**Resilient Alert System:** ✅
**Channel Isolation:** ✅
**Auto Error Recovery:** ✅
**Health Monitoring:** ✅
                    """,
                    "inline": True
                },
                {
                    "name": "🛡️ Risk Management",
                    "value": f"""
**Delayed Stop Loss:** {STOP_LOSS_DELAY_SECONDS/60:.0f} minutes
**Initial Stop:** 50% loss protection
**Trailing Stops:** 20% trailing on trims
**Auto Risk Management:** ✅ ENABLED
                    """,
                    "inline": True
                }
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.alert_manager.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [startup_embed]}, "startup", priority=3)

    async def on_disconnect(self):
        """Clean shutdown"""
        print("🔌 Discord client disconnecting...")
        
        # Stop heartbeat task
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
            print("💓 Heartbeat task stopped")
        
        # Stop alert manager
        await self.alert_manager.stop()

def main():
    try:
        print("🚀 Starting RHTB v4 Enhanced...")
        print(f"Settings: SIM_MODE={SIM_MODE}, TESTING_MODE={TESTING_MODE}, DEBUG_MODE={DEBUG_MODE}")
        
        print("📊 Enhanced Features Active:")
        print("   ✅ Resilient alert system with auto-recovery")
        print("   ✅ Channel-isolated position tracking")  
        print("   ✅ Comprehensive error handling and recovery")
        print("   ✅ Real-time health monitoring")
        print("   ✅ All commands restored and enhanced")
        print("")
        print("🛡️ Automatic Risk Management Active:")
        print(f"   ⏱️ Delayed stop loss: {STOP_LOSS_DELAY_SECONDS/60:.0f} minutes after buy")
        print("   📉 Initial stop loss: 50% protection")
        print("   📈 Trailing stops: 20% on partial exits")
        print("   🎯 Market-based exit pricing")
        print("   ⚡ Enhanced order monitoring with auto-cancel")
        print("")
        
        client = EnhancedDiscordClient()
        client.run(DISCORD_TOKEN)
        
    except Exception as e:
        print(f"❌ Critical startup error: {e}")
        raise

if __name__ == "__main__":
    main()