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
from position_ledger import PositionLedger
from trader import EnhancedRobinhoodTrader, EnhancedSimulatedTrader

# Import channel parsers
from channels.sean import SeanParser
from channels.price_parser import PriceParser

# Import AI logging system
from ai_logging import setup_ai_logging

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

# ============= AI-READABLE LOGGING SETUP =============
# Initialize AI logging system (JSONL format with daily rotation)
logger = setup_ai_logging(log_dir="logs", retention_days=14)
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

            self.position_ledger = PositionLedger(POSITION_LEDGER_DB)
            logger.info("Position ledger initialized")

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
                self.alert_manager,
                self.position_ledger
            )
            logger.info("Trade executor initialized")
            
            # System state
            self.start_time = datetime.now(timezone.utc)
            self.heartbeat_task = None
            self.ledger_sync_task = None
            self.fill_monitor_task = None  # Monitors pending buy orders for fills
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

            # Sync position ledger with Robinhood
            if self.live_trader and not TESTING_MODE:
                logger.info("Syncing position ledger with Robinhood...")
                loop = asyncio.get_event_loop()
                sync_result = await loop.run_in_executor(
                    None,
                    self.position_ledger.sync_from_robinhood,
                    self.live_trader
                )
                logger.info(f"Ledger sync complete: added={sync_result.positions_added}, "
                           f"updated={sync_result.positions_updated}, orphaned={sync_result.positions_orphaned}")

            # Start heartbeat task
            if not self.heartbeat_task or self.heartbeat_task.done():
                self.heartbeat_task = asyncio.create_task(self._heartbeat_task())
                logger.info("Heartbeat task started")

            # Start ledger sync task (periodic reconciliation with Robinhood)
            if not TESTING_MODE:
                if not self.ledger_sync_task or self.ledger_sync_task.done():
                    self.ledger_sync_task = asyncio.create_task(self._ledger_sync_task())
                    logger.info("Ledger sync task started")

            # Start fill monitoring task (polls pending orders for fills)
            if not TESTING_MODE:
                if not self.fill_monitor_task or self.fill_monitor_task.done():
                    self.fill_monitor_task = asyncio.create_task(self._fill_monitor_task())
                    logger.info("Fill monitor task started")

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

    async def _ledger_sync_task(self):
        """Periodic reconciliation of position ledger with Robinhood."""
        while True:
            try:
                await asyncio.sleep(LEDGER_SYNC_INTERVAL)

                if self.live_trader and self.position_ledger:
                    logger.debug("Running periodic ledger sync...")
                    loop = asyncio.get_event_loop()
                    sync_result = await loop.run_in_executor(
                        None,
                        self.position_ledger.sync_from_robinhood,
                        self.live_trader
                    )

                    # Only log if changes occurred
                    if sync_result.positions_added or sync_result.positions_updated or sync_result.positions_orphaned:
                        logger.info(f"Ledger sync: added={sync_result.positions_added}, "
                                   f"updated={sync_result.positions_updated}, orphaned={sync_result.positions_orphaned}")

                    # Clean up expired locks
                    self.position_ledger.cleanup_expired_locks(LEDGER_LOCK_TIMEOUT)

            except asyncio.CancelledError:
                logger.info("Ledger sync task cancelled")
                break
            except Exception as e:
                logger.error(f"Ledger sync error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait a minute before retrying

    async def _fill_monitor_task(self):
        """Monitor pending buy orders and transition positions when filled."""
        while True:
            try:
                await asyncio.sleep(FILL_MONITORING_INTERVAL)

                if not self.live_trader or not self.position_ledger:
                    continue

                # Get all positions in 'opening' status
                opening_positions = self.position_ledger.get_opening_positions()

                if not opening_positions:
                    continue

                logger.debug(f"Checking {len(opening_positions)} pending orders for fills...")

                for position in opening_positions:
                    try:
                        order_id = position.order_id
                        ccid = position.ccid

                        if not order_id:
                            logger.warning(f"Opening position {ccid} has no order_id - skipping")
                            continue

                        # Check order status with Robinhood
                        loop = asyncio.get_event_loop()
                        order_info = await loop.run_in_executor(
                            None,
                            self._get_order_status,
                            order_id
                        )

                        if not order_info:
                            logger.warning(f"Could not get order status for {order_id}")
                            continue

                        order_state = order_info.get('state', '').lower()

                        # Handle different order states
                        if order_state == 'filled':
                            # Order filled - transition to 'open'
                            fill_price = float(order_info.get('average_price', 0) or position.entry_price)
                            fill_qty = int(float(order_info.get('cumulative_quantity', 0) or position.quantity))

                            self.position_ledger.transition_to_open(ccid, fill_price)

                            logger.info(f"✅ Order FILLED: {ccid} @ ${fill_price:.2f} x{fill_qty}")

                            # Update position manager and performance tracker
                            await self._handle_fill_complete(position, fill_price, fill_qty)

                        elif order_state in ('cancelled', 'rejected', 'failed'):
                            # Order failed - mark as cancelled
                            reason = f"Order {order_state}: {order_info.get('reject_reason', 'Unknown')}"
                            self.position_ledger.cancel_opening_position(ccid, reason)
                            logger.warning(f"❌ Order {order_state}: {ccid} - {reason}")

                        elif order_state in ('pending', 'queued', 'confirmed', 'partially_filled'):
                            # Check for timeout
                            created_at = position.created_at
                            if created_at:
                                age_seconds = (datetime.now(timezone.utc) - created_at).total_seconds()

                                if age_seconds > FILL_TIMEOUT_SECONDS:
                                    # Order timed out - attempt to cancel
                                    logger.warning(f"⏰ Order timeout ({age_seconds:.0f}s): {ccid} - attempting cancel")

                                    cancel_success = await loop.run_in_executor(
                                        None,
                                        self._cancel_order,
                                        order_id
                                    )

                                    if cancel_success:
                                        self.position_ledger.cancel_opening_position(ccid, f"Timeout after {age_seconds:.0f}s")
                                        logger.info(f"🚫 Order cancelled due to timeout: {ccid}")
                                    else:
                                        logger.error(f"Failed to cancel timed-out order: {ccid}")

                    except Exception as pe:
                        logger.error(f"Error processing opening position {position.ccid}: {pe}", exc_info=True)

            except asyncio.CancelledError:
                logger.info("Fill monitor task cancelled")
                break
            except Exception as e:
                logger.error(f"Fill monitor error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait a minute before retrying

    def _get_order_status(self, order_id: str) -> dict:
        """Get order status from Robinhood (blocking call)."""
        try:
            import robin_stocks.robinhood as r
            order_info = r.orders.get_option_order_info(order_id)
            return order_info if order_info else {}
        except Exception as e:
            logger.error(f"Error getting order status for {order_id}: {e}")
            return {}

    def _cancel_order(self, order_id: str) -> bool:
        """Cancel an order on Robinhood (blocking call)."""
        try:
            import robin_stocks.robinhood as r
            result = r.orders.cancel_option_order(order_id)
            return result is not None
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def _handle_fill_complete(self, position, fill_price: float, fill_qty: int):
        """Handle post-fill updates (position manager, performance tracker, alerts)."""
        try:
            # Build trade_obj from position data
            trade_obj = {
                'trade_id': position.trade_id,
                'ticker': position.trader_symbol or position.symbol,
                'symbol': position.symbol,
                'strike': position.strike,
                'type': position.option_type,
                'expiration': position.expiration,
                'price': fill_price,
                'quantity': fill_qty,
                'channel': position.channel,
                'channel_id': position.channel_id,
                'size': position.size,
                'status': 'active'
            }

            # Update position manager
            if self.position_manager:
                self.position_manager.add_position(position.channel_id, trade_obj)

            # Update performance tracker
            if self.performance_tracker:
                self.performance_tracker.record_entry(trade_obj)

            # Send fill notification
            fill_embed = {
                "title": "✅ Order Filled",
                "description": f"**{position.symbol}** ${position.strike} {position.option_type.upper()} {position.expiration}",
                "color": 0x00ff00,
                "fields": [
                    {"name": "Fill Price", "value": f"${fill_price:.2f}", "inline": True},
                    {"name": "Quantity", "value": str(fill_qty), "inline": True},
                    {"name": "Channel", "value": position.channel or "Unknown", "inline": True}
                ],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            await self.alert_manager.add_alert(
                ALL_NOTIFICATION_WEBHOOK,
                {"embeds": [fill_embed]},
                "fill_notification"
            )

        except Exception as e:
            logger.error(f"Error handling fill complete: {e}", exc_info=True)

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
                    # Fetch recent message history for context (last 5 messages)
                    message_history = await self.get_channel_message_history(
                        message.channel, limit=5, exclude_message_id=message.id
                    )
                    logger.debug(f"Fetched {len(message_history)} messages for context")

                    # Log to live feed
                    await self._send_live_feed_alert(handler, raw_msg)

                    # Process trade with proper async context
                    received_ts = datetime.now(timezone.utc)
                    await self.trade_executor.process_trade(
                        handler, message_meta, raw_msg, SIM_MODE, received_ts,
                        str(message.id), False, self.loop, message_history
                    )
                    
        except Exception as e:
            logger.error(f"Message handling error: {e}", exc_info=True)
            await self.alert_manager.send_error_alert(f"Message handling error: {e}")

    async def on_message_edit(self, before, after):
        """Handle message edits - log only, no trade execution to avoid duplicates"""
        try:
            if before.content == after.content and before.embeds == after.embeds:
                return

            handler = self.channel_manager.get_handler(after.channel.id)
            if handler:
                logger.info(f"Message edit detected in {handler.name} - logging only (no trade action)")

                # Extract original content (before edit)
                original_content = ""
                if before.embeds:
                    embed = before.embeds[0]
                    original_content = f"{embed.title or ''}: {embed.description or ''}".strip(': ')
                else:
                    original_content = before.content or ""

                # Extract edited content (after edit)
                edited_content = ""
                if after.embeds:
                    embed = after.embeds[0]
                    edited_content = f"{embed.title or ''}: {embed.description or ''}".strip(': ')
                else:
                    edited_content = after.content or ""

                # Send notification embed showing original vs edited
                edit_embed = {
                    "title": f"📝 Message Edit Detected - {handler.name}",
                    "description": "**⚠️ No trade action taken** - Edit logged for visibility only",
                    "color": 0xFFA500,  # Orange color
                    "fields": [
                        {
                            "name": "📜 Original Message",
                            "value": f"```{original_content[:1000]}```" if original_content else "*Empty*",
                            "inline": False
                        },
                        {
                            "name": "✏️ Edited Message",
                            "value": f"```{edited_content[:1000]}```" if edited_content else "*Empty*",
                            "inline": False
                        }
                    ],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": f"Message ID: {after.id}"}
                }

                await self.alert_manager.add_alert(
                    COMMANDS_WEBHOOK,
                    {"embeds": [edit_embed]},
                    "edit_notification"
                )
                logger.info(f"Edit notification sent for message {after.id}")

        except Exception as e:
            logger.error(f"Edit handling error: {e}", exc_info=True)

    def _extract_message_content(self, message, handler):
        """Extract message content for processing, including replies and forwards"""
        try:
            current_embed_title = ""
            current_embed_desc = ""

            if message.embeds:
                embed = message.embeds[0]
                current_embed_title = embed.title or ""
                current_embed_desc = embed.description or ""

            current_content = message.content or ""
            current_full_text = f"Title: {current_embed_title}\nDesc: {current_embed_desc}" if current_embed_title else current_content

            # Check for forwarded message (Discord forwards have message_snapshots attribute)
            is_forward = False
            forwarded_content = ""
            if hasattr(message, 'message_snapshots') and message.message_snapshots:
                is_forward = True
                # Extract forwarded message content
                for snapshot in message.message_snapshots:
                    if hasattr(snapshot, 'content') and snapshot.content:
                        forwarded_content = snapshot.content
                        break
                    elif hasattr(snapshot, 'embeds') and snapshot.embeds:
                        fwd_embed = snapshot.embeds[0]
                        forwarded_content = f"Title: {fwd_embed.title or ''}\nDesc: {fwd_embed.description or ''}"
                        break
                logger.info(f"Forwarded message detected from {handler.name}")

            # Handle forwards
            if is_forward and forwarded_content:
                # For forwards, the forwarded content is the main content to parse
                # Current content (if any) is like a comment on the forward
                if current_content:
                    message_meta = (current_content, forwarded_content)
                    raw_msg = f"Comment: '{current_content}'\nForwarded: '{forwarded_content}'"
                else:
                    message_meta = forwarded_content
                    raw_msg = f"Forwarded: '{forwarded_content}'"
            # Handle replies
            elif message.reference and isinstance(message.reference.resolved, discord.Message):
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

    async def get_channel_message_history(self, channel, limit=5, exclude_message_id=None):
        """
        Fetch recent message history from a channel for context.
        Returns messages in chronological order (oldest first).

        Args:
            channel: Discord channel object
            limit: Number of messages to fetch (default 5)
            exclude_message_id: Message ID to exclude (usually the current message)

        Returns:
            List of formatted message strings in chronological order
        """
        try:
            history = []
            async for msg in channel.history(limit=limit + 1):  # +1 in case we need to exclude current
                # Skip the message we're currently processing
                if exclude_message_id and msg.id == exclude_message_id:
                    continue

                # Extract content from message
                content = ""
                if msg.embeds:
                    embed = msg.embeds[0]
                    title = embed.title or ""
                    desc = embed.description or ""
                    content = f"{title}: {desc}" if title else desc
                else:
                    content = msg.content or ""

                if content:
                    # Format with timestamp for context
                    timestamp = msg.created_at.strftime("%H:%M:%S")
                    history.append(f"[{timestamp}] {content[:200]}")  # Truncate long messages

                if len(history) >= limit:
                    break

            # Reverse to chronological order (oldest first)
            return history[::-1]

        except Exception as e:
            logger.error(f"Error fetching message history: {e}", exc_info=True)
            return []

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
                
            elif command in ("!price", "!getprice"):
                # Extract query - handle both !price and !getprice
                if command == "!price":
                    query = content[len("!price"):].strip()
                else:
                    query = content[len("!getprice"):].strip()
                if query:
                    await self._handle_get_price(query)
                else:
                    await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                        "content": "Usage: `!price <options contract query>`\nExample: `!price SPY 600c 1/31` or `!price $TSLA 400p Feb 14`"
                    }, "command_response")
            
            elif command == "!positions":
                await self._handle_positions_command()
                
            elif command == "!portfolio":
                await self._handle_portfolio_command()
                
            elif command == "!trades":
                await self._handle_trades_command()

            elif command == "!pnl":
                # Parse optional days parameter (default 30)
                days_arg = content[len("!pnl"):].strip()
                days = 30
                if days_arg:
                    try:
                        days = int(days_arg)
                    except ValueError:
                        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                            "content": "Usage: `!pnl [days]`\nExample: `!pnl` (30 days) or `!pnl 7` (7 days)"
                        }, "command_response")
                        return
                await self._handle_pnl_command(days)

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
            
            elif command == "!clear":
                channel_arg = content[len("!clear"):].strip()
                if channel_arg:
                    await self._handle_clear_command(channel_arg)
                else:
                    await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {
                        "content": "Usage: `!clear <channel_name>`\nExample: `!clear ryan` or `!clear eva`\nClears fallback position history for the specified channel."
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
`!clear <channel>` - Clear fallback position history for channel
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

            if not parsed_contract or not isinstance(parsed_contract, dict):
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

            # Price data
            bid = float(data.get('bid_price', 0) or 0)
            ask = float(data.get('ask_price', 0) or 0)
            mark = float(data.get('mark_price', 0) or 0)
            prev_close = float(data.get('previous_close_price', 0) or 0)
            volume = int(data.get('volume', 0) or 0)
            open_interest = int(data.get('open_interest', 0) or 0)

            # Greeks
            delta = float(data.get('delta', 0) or 0)
            gamma = float(data.get('gamma', 0) or 0)
            theta = float(data.get('theta', 0) or 0)
            vega = float(data.get('vega', 0) or 0)
            rho = float(data.get('rho', 0) or 0)

            # IV
            iv = float(data.get('implied_volatility', 0) or 0)
            iv_pct = iv * 100 if iv < 1 else iv  # Handle decimal vs percentage

            # Price change
            price_change = mark - prev_close if prev_close > 0 else 0
            price_change_pct = (price_change / prev_close * 100) if prev_close > 0 else 0
            change_emoji = "📈" if price_change >= 0 else "📉"
            color = 0x00ff00 if price_change >= 0 else 0xff0000  # Green/Red based on change

            # Format Greeks block
            greeks_text = f"""```
Δ Delta: {delta:+.4f}
Γ Gamma: {gamma:.4f}
Θ Theta: {theta:.4f}
V Vega:  {vega:.4f}
ρ Rho:   {rho:+.4f}
```"""

            price_embed = {
                "title": f"📊 {parsed.get('ticker').upper()} ${parsed.get('strike')} {parsed.get('type').upper()}",
                "description": f"**Expiration:** {parsed.get('expiration')}\n{change_emoji} **Change:** {price_change:+.2f} ({price_change_pct:+.1f}%)",
                "color": color,
                "fields": [
                    {"name": "Mark Price", "value": f"${mark:.2f}", "inline": True},
                    {"name": "Bid / Ask", "value": f"${bid:.2f} / ${ask:.2f}", "inline": True},
                    {"name": "Spread", "value": f"${(ask - bid):.2f} ({((ask - bid) / mark * 100) if mark > 0 else 0:.1f}%)", "inline": True},
                    {"name": "Volume", "value": f"{volume:,}", "inline": True},
                    {"name": "Open Interest", "value": f"{open_interest:,}", "inline": True},
                    {"name": "IV", "value": f"{iv_pct:.1f}%", "inline": True},
                    {"name": "Greeks", "value": greeks_text, "inline": False},
                    {"name": "Prev Close", "value": f"${prev_close:.2f}", "inline": True}
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Data from Robinhood API"}
            }
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [price_embed]}, "command_response")

    async def _handle_positions_command(self):
        """Handle positions command - shows entry, current, and P&L per position"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching positions with P&L..."}, "command_response")

        def get_positions_with_pnl():
            try:
                positions = self.live_trader.get_open_option_positions()
                if not positions:
                    return {"positions": [], "total_value": 0, "total_pnl": 0}

                position_data = []
                total_value = 0
                total_pnl = 0

                for p in positions:
                    try:
                        # Get instrument details
                        instrument_data = self.live_trader.get_option_instrument_data(p['option'])
                        if not instrument_data:
                            continue

                        symbol = p.get('chain_symbol', '')
                        strike = float(instrument_data.get('strike_price', 0))
                        opt_type = instrument_data.get('type', 'call')
                        expiration = instrument_data.get('expiration_date', '')
                        quantity = int(float(p.get('quantity', 0)))
                        entry_price = float(p.get('average_price', 0))

                        # Get current market price
                        market_data = self.live_trader.get_option_market_data(symbol, expiration, strike, opt_type)
                        current_price = entry_price  # Default to entry if no market data

                        if market_data:
                            # Handle nested response [[{data}]] or [{data}]
                            data = None
                            if isinstance(market_data, list) and len(market_data) > 0:
                                if isinstance(market_data[0], list) and len(market_data[0]) > 0:
                                    data = market_data[0][0]
                                elif isinstance(market_data[0], dict):
                                    data = market_data[0]

                            if data and data.get('mark_price'):
                                current_price = float(data.get('mark_price', 0) or entry_price)

                        # Calculate P&L (price per contract * quantity * 100 shares per contract)
                        pnl_dollars = (current_price - entry_price) * quantity * 100
                        pnl_percent = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                        position_value = current_price * quantity * 100

                        total_value += position_value
                        total_pnl += pnl_dollars

                        position_data.append({
                            'symbol': symbol,
                            'strike': strike,
                            'type': opt_type[0].upper(),
                            'expiration': expiration,
                            'quantity': quantity,
                            'entry_price': entry_price,
                            'current_price': current_price,
                            'pnl_dollars': pnl_dollars,
                            'pnl_percent': pnl_percent,
                            'value': position_value
                        })

                    except Exception as e:
                        logger.error(f"Could not process position: {e}")
                        continue

                return {
                    "positions": position_data,
                    "total_value": total_value,
                    "total_pnl": total_pnl
                }

            except Exception as e:
                logger.error(f"Error retrieving positions: {e}", exc_info=True)
                return {"positions": [], "total_value": 0, "total_pnl": 0, "error": str(e)}

        result = await self.loop.run_in_executor(None, get_positions_with_pnl)

        if result.get("error"):
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"❌ Error: {result['error']}"}, "command_response")
            return

        positions = result["positions"]
        if not positions:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "📭 No open option positions."}, "command_response")
            return

        # Build positions text
        pos_lines = []
        for pos in positions[:10]:  # Limit to 10 positions
            pnl_emoji = "🟢" if pos['pnl_dollars'] >= 0 else "🔴"
            pos_lines.append(
                f"{pnl_emoji} **{pos['symbol']}** ${pos['strike']}{pos['type']} {pos['expiration']}\n"
                f"   {pos['quantity']}x @ ${pos['entry_price']:.2f} → ${pos['current_price']:.2f} | "
                f"**{pos['pnl_percent']:+.1f}%** (${pos['pnl_dollars']:+,.2f})"
            )

        # Total P&L color
        color = 0x00ff00 if result["total_pnl"] >= 0 else 0xff0000

        positions_embed = {
            "title": f"📊 Open Positions ({len(positions)})",
            "description": "\n\n".join(pos_lines),
            "color": color,
            "fields": [
                {"name": "💰 Total Value", "value": f"${result['total_value']:,.2f}", "inline": True},
                {"name": "📈 Total P&L", "value": f"${result['total_pnl']:+,.2f}", "inline": True}
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Entry → Current | P&L%"}
        }
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [positions_embed]}, "command_response")

    async def _handle_portfolio_command(self):
        """Handle portfolio command - shows portfolio value and buying power"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "⏳ Fetching account details..."}, "command_response")

        def get_account_sync():
            portfolio_value = self.live_trader.get_portfolio_value()
            buying_power = self.live_trader.get_buying_power()
            return portfolio_value, buying_power

        portfolio_value, buying_power = await self.loop.run_in_executor(None, get_account_sync)

        portfolio_embed = {
            "title": "💰 Account Summary",
            "color": 0x00ff00,
            "fields": [
                {"name": "Portfolio Value", "value": f"${portfolio_value:,.2f}", "inline": True},
                {"name": "Buying Power", "value": f"${buying_power:,.2f}", "inline": True}
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [portfolio_embed]}, "command_response")

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

    async def _handle_pnl_command(self, days: int = 30):
        """Handle P&L summary command"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"⏳ Calculating P&L for last {days} days..."}, "command_response")

        def get_pnl_sync():
            try:
                # Get performance summary
                summary = self.performance_tracker.get_performance_summary(days=days)

                # Get trades for average hold time calculation
                trades = self.performance_tracker.get_recent_trades(limit=1000)

                # Calculate average hold time from closed trades with exit_time
                hold_times = []
                for trade in trades:
                    if trade.get('exit_time') and trade.get('entry_time'):
                        try:
                            entry = datetime.fromisoformat(trade['entry_time'].replace('Z', '+00:00'))
                            exit_t = datetime.fromisoformat(trade['exit_time'].replace('Z', '+00:00'))
                            hold_minutes = (exit_t - entry).total_seconds() / 60
                            if hold_minutes > 0:
                                hold_times.append(hold_minutes)
                        except:
                            pass

                avg_hold_minutes = sum(hold_times) / len(hold_times) if hold_times else 0

                return {
                    'total_pnl': summary.get('total_pnl', 0),
                    'total_trades': summary.get('total_trades', 0),
                    'winning_trades': summary.get('winning_trades', 0),
                    'losing_trades': summary.get('losing_trades', 0),
                    'win_rate': summary.get('win_rate', 0),
                    'best_trade': summary.get('best_trade', 0),
                    'worst_trade': summary.get('worst_trade', 0),
                    'avg_hold_minutes': avg_hold_minutes,
                    'days': days
                }
            except Exception as e:
                logger.error(f"Error calculating P&L: {e}", exc_info=True)
                return None

        result = await self.loop.run_in_executor(None, get_pnl_sync)

        if not result:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": "❌ Error calculating P&L summary"}, "command_response")
            return

        # Calculate average P&L per trade
        avg_pnl = result['total_pnl'] / result['total_trades'] if result['total_trades'] > 0 else 0

        # Format hold time
        if result['avg_hold_minutes'] >= 60:
            hold_str = f"{result['avg_hold_minutes'] / 60:.1f} hours"
        else:
            hold_str = f"{result['avg_hold_minutes']:.0f} mins"

        # Color based on P&L
        color = 0x00ff00 if result['total_pnl'] >= 0 else 0xff0000

        pnl_embed = {
            "title": f"📊 P&L Summary - Last {result['days']} Days",
            "color": color,
            "fields": [
                {"name": "💰 Total P&L", "value": f"${result['total_pnl']:+,.2f}", "inline": True},
                {"name": "📈 Total Trades", "value": str(result['total_trades']), "inline": True},
                {"name": "🎯 Win Rate", "value": f"{result['win_rate']:.1f}%", "inline": True},
                {"name": "✅ Winning", "value": str(result['winning_trades']), "inline": True},
                {"name": "❌ Losing", "value": str(result['losing_trades']), "inline": True},
                {"name": "📊 Avg P&L", "value": f"${avg_pnl:+,.2f}", "inline": True},
                {"name": "🏆 Best Trade", "value": f"{result['best_trade']:+.1f}%", "inline": True},
                {"name": "💔 Worst Trade", "value": f"{result['worst_trade']:+.1f}%", "inline": True},
                {"name": "⏱️ Avg Hold", "value": hold_str, "inline": True}
            ],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [pnl_embed]}, "command_response")

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
            broker_symbol = result.get('broker_symbol', symbol)
            
            # Create embed with tick size information
            embed = {
                "title": f"🎯 Minimum Tick Size: {symbol}",
                "description": f"**Minimum tick size:** ${tick_size:.4f}".rstrip('0').rstrip('.'),
                "color": 3447003,  # Blue
                "fields": []
            }
            
            # Add additional info if available
            if result.get('info'):
                info = result['info']
                embed["fields"].extend([
                    {"name": "Instrument Name", "value": info.get('name', 'N/A'), "inline": True},
                    {"name": "Tradeable", "value": str(info.get('tradeable', 'Unknown')), "inline": True},
                    {"name": "Type", "value": info.get('type', 'Unknown'), "inline": True}
                ])
            
            # Add basic details
            content = f"""**Symbol:** {symbol} (Broker: {broker_symbol})
**Min Tick:** ${tick_size:.4f}
**Decimal Places:** {len(str(tick_size).split('.')[-1])}

**Practical Examples:**
"""
            
            # Add examples of rounding
            if result.get('success'):
                try:
                    trader = self.live_trader if not SIM_MODE else self.sim_trader
                    base_price = tick_size * 10  # Example base price
                    rounded_up = trader.round_to_tick(base_price + tick_size/2, symbol, round_up_for_buy=True)
                    rounded_down = trader.round_to_tick(base_price + tick_size/2, symbol, round_up_for_buy=False)
                    
                    content += f"• ${base_price + tick_size/2:.4f} rounds to ${rounded_up:.4f} (buy)\n"
                    content += f"• ${base_price + tick_size/2:.4f} rounds to ${rounded_down:.4f} (sell)"
                except Exception as e:
                    logger.debug(f"Error creating examples: {e}")
                    content += "Examples not available"
            
            embed["description"] = content
            
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"embeds": [embed]}, "command_response")
    
    async def _handle_clear_command(self, channel_name: str):
        """Handle clear command to close all open positions for a channel"""
        await self.alert_manager.add_alert(COMMANDS_WEBHOOK, 
                                            {"content": f"⏳ Clearing fallback positions for channel: `{channel_name}`..."}, 
                                            "command_response")

        def clear_channel_positions():
            try:
                # Normalize channel name
                channel_name_normalized = channel_name.lower().strip()
                
                # Map channel names to their identifiers in the database
                channel_mapping = {
                    'sean': 'Sean'
                }
                
                if channel_name_normalized not in channel_mapping:
                    return {"error": f"Unknown channel: {channel_name}. Available channels: {', '.join(channel_mapping.keys())}"}
                
                channel_db_name = channel_mapping[channel_name_normalized]
                
                # Get current open positions
                open_trades = self.performance_tracker.get_open_trades_for_channel(channel_db_name)
                
                if not open_trades:
                    return {
                        "success": True,
                        "channel": channel_db_name,
                        "message": "No open positions found to clear",
                        "cleared_count": 0
                    }
                
                # Close all open positions by updating their status to 'cleared'
                cleared_count = self.performance_tracker.close_all_channel_positions(channel_db_name, reason="Manual clear command")
                
                return {
                    "success": True,
                    "channel": channel_db_name,
                    "message": f"Successfully cleared {cleared_count} open positions",
                    "cleared_count": cleared_count,
                    "trades": [{"symbol": t.get("trader_symbol"), "trade_id": t.get("trade_id")} for t in open_trades[:5]]  # Show first 5
                }
                
            except Exception as e:
                logger.error(f"Error clearing positions for channel {channel_name}: {e}", exc_info=True)
                return {"error": f"Error clearing positions: {str(e)}"}

        result = await self.loop.run_in_executor(None, clear_channel_positions)

        if "error" in result:
            await self.alert_manager.add_alert(COMMANDS_WEBHOOK, {"content": f"❌ {result['error']}"}, "command_response")
        else:
            channel = result['channel']
            cleared_count = result['cleared_count']
            message = result['message']
            
            # Create embed with clear results
            embed = {
                "title": f"🧹 Channel Positions Cleared: {channel}",
                "description": message,
                "color": 65280 if cleared_count > 0 else 16776960,  # Green if cleared, yellow if none
                "fields": [
                    {"name": "Channel", "value": channel, "inline": True},
                    {"name": "Positions Cleared", "value": str(cleared_count), "inline": True}
                ]
            }
            
            # Add list of cleared trades if any
            if result.get('trades') and cleared_count > 0:
                trades_list = []
                for trade in result['trades']:
                    trades_list.append(f"• {trade['symbol']} (ID: {trade['trade_id']})")
                
                if len(trades_list) > 0:
                    trades_text = "\n".join(trades_list)
                    if cleared_count > 5:
                        trades_text += f"\n... and {cleared_count - 5} more positions"
                    
                    embed["fields"].append({
                        "name": "Cleared Positions", 
                        "value": trades_text, 
                        "inline": False
                    })
            
            embed["footer"] = {
                "text": "Fallback logic will no longer reference these positions for incomplete trade signals."
            }
            
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

        # Cancel ledger sync task
        if self.ledger_sync_task and not self.ledger_sync_task.done():
            self.ledger_sync_task.cancel()
            try:
                await self.ledger_sync_task
            except asyncio.CancelledError:
                pass

        # Cancel fill monitor task
        if self.fill_monitor_task and not self.fill_monitor_task.done():
            self.fill_monitor_task.cancel()
            try:
                await self.fill_monitor_task
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