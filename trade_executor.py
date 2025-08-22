# trade_executor.py - Channel-Aware Trade Execution Logic
import asyncio
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from config import *

class ChannelAwareFeedbackLogger:
    """Enhanced feedback logger with strict channel isolation"""
    
    def __init__(self, filename="parsing_feedback.csv"):
        self.filename = filename
        self.lock = threading.Lock()
        self._initialize_file()

    def _initialize_file(self):
        """Creates the CSV file with headers if it doesn't exist."""
        import csv
        import os
        
        if not os.path.exists(self.filename):
            with self.lock:
                if not os.path.exists(self.filename):
                    with open(self.filename, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            "Channel Name",
                            "Original Message", 
                            "Parsed Message",
                            "Latency (ms)",
                            "Timestamp"
                        ])

    def log(self, channel_name, original_message, parsed_message_json, latency=0):
        """Log parse result with channel isolation"""
        import csv
        import json
        
        with self.lock:
            try:
                with open(self.filename, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        channel_name,
                        original_message,
                        json.dumps(parsed_message_json),
                        f"{latency:.2f}",
                        datetime.now(timezone.utc).isoformat()
                    ])
            except Exception as e:
                print(f"❌ Failed to write to feedback log: {e}")
    
    def get_recent_parse_for_channel(self, channel_name: str, ticker: str):
        """Get most recent successful parse for ticker within specific channel"""
        import csv
        import json
        
        try:
            with self.lock:
                if not os.path.exists(self.filename):
                    return None
                    
                with open(self.filename, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader)  # Skip header
                    
                    recent_parses = []
                    for row in reader:
                        if len(row) >= 5:
                            row_channel, message, parsed_json = row[0], row[1], row[2]
                            
                            # STRICT channel matching
                            if row_channel == channel_name:
                                try:
                                    parsed_data = json.loads(parsed_json)
                                    if (isinstance(parsed_data, dict) and 
                                        parsed_data.get('ticker') == ticker and
                                        parsed_data.get('strike') and 
                                        parsed_data.get('expiration') and 
                                        parsed_data.get('type')):
                                        recent_parses.append(parsed_data)
                                except:
                                    continue
                    
                    return recent_parses[-1] if recent_parses else None
                    
        except Exception as e:
            print(f"❌ Error reading feedback log: {e}")
            return None

class DelayedStopLossManager:
    """Manages delayed stop loss orders"""
    
    def __init__(self):
        self.pending_stops = {}
        
    def schedule_stop_loss(self, trade_id: str, stop_data: dict, delay_seconds: int = 900):
        """Schedule a stop loss to be placed after delay"""
        def place_stop_after_delay():
            time.sleep(delay_seconds)
            print(f"⏰ Placing delayed stop loss for trade {trade_id}")
            
            trader = stop_data['trader']
            try:
                response = trader.place_option_stop_loss_order(
                    stop_data['symbol'],
                    stop_data['strike'],
                    stop_data['expiration'],
                    stop_data['opt_type'],
                    stop_data['quantity'],
                    stop_data['stop_price']
                )
                print(f"✅ Delayed stop loss placed for {stop_data['symbol']}: {response}")
            except Exception as e:
                print(f"❌ Failed to place delayed stop loss: {e}")
            finally:
                if trade_id in self.pending_stops:
                    del self.pending_stops[trade_id]
        
        self.pending_stops[trade_id] = stop_data
        thread = threading.Thread(target=place_stop_after_delay, daemon=True)
        thread.start()
        print(f"⏱️ Stop loss scheduled for {delay_seconds/60:.1f} minutes from now")

class TradeExecutor:
    """Channel-aware trade execution with enhanced error handling"""
    
    def __init__(self, live_trader, sim_trader, performance_tracker, position_manager, alert_manager):
        self.live_trader = live_trader
        self.sim_trader = sim_trader
        self.performance_tracker = performance_tracker
        self.position_manager = position_manager
        self.alert_manager = alert_manager
        
        # Enhanced feedback logger with channel isolation
        self.feedback_logger = ChannelAwareFeedbackLogger()
        self.stop_loss_manager = DelayedStopLossManager()
        
        print("✅ Trade Executor initialized with channel isolation")
    
    async def process_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id=None, is_edit=False):
        """Main trade processing entry point"""
        def enhanced_log(msg, level="INFO"):
            if level == "ERROR":
                print(f"❌ {msg}")
                asyncio.create_task(self.alert_manager.send_error_alert(msg))
            else:
                print(f"ℹ️ {msg}")
                asyncio.create_task(self.alert_manager.add_alert(
                    ALL_NOTIFICATION_WEBHOOK, {"content": msg}, 
                    f"{level.lower()}_notification"
                ))
        
        # Run trade processing in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, 
            self._blocking_handle_trade,
            handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, enhanced_log
        )
    
    def _blocking_handle_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, log_func):
        """Blocking trade execution logic with channel isolation"""
        try:
            log_func(f"🔄 Processing message from {handler.name}: {raw_msg[:100]}...")
            
            # Parse the message
            try:
                parsed_results, latency_ms = handler.parse_message(message_meta, received_ts, log_func)
                
                if parsed_results:
                    for parsed_obj in parsed_results:
                        # Log with CHANNEL-SPECIFIC feedback
                        self.feedback_logger.log(handler.name, raw_msg, parsed_obj, latency_ms)
                
                if not parsed_results:
                    log_func(f"⚠️ No parsed results from {handler.name}")
                    return
                    
            except Exception as e:
                log_func(f"❌ Parse error in {handler.name}: {e}", "ERROR")
                return

            for raw_trade_obj in parsed_results:
                try:
                    trade_obj = self._normalize_keys(raw_trade_obj)
                    action_value = trade_obj.get("action")
                    action = action_value.lower() if action_value else ""
                    
                    if not action or action == "null": 
                        log_func(f"⏭️ Skipping null action from {handler.name}")
                        continue

                    log_func(f"🎯 Processing {action} trade: {trade_obj}")

                    # Get config and trader
                    config = CHANNELS_CONFIG.get(handler.name)
                    if not config:
                        log_func(f"❌ No config found for {handler.name}", "ERROR")
                        continue

                    trader = self.live_trader if not is_sim_mode else self.sim_trader
                    
                    # Enhanced contract resolution with STRICT channel isolation
                    trade_obj['channel'] = handler.name
                    trade_obj['channel_id'] = handler.channel_id
                    
                    # Try to find active position for trim/exit actions
                    active_position = None
                    if action in ("trim", "exit", "stop"):
                        # FIRST: Try position manager (channel-specific)
                        active_position = self.position_manager.find_position(trade_obj['channel_id'], trade_obj) or {}
                        
                        # SECOND: Try performance tracker (channel-specific)
                        if not active_position and trade_obj.get('ticker'):
                            trade_id = self.performance_tracker.find_open_trade_by_ticker(
                                trade_obj['ticker'], handler.name  # Pass channel name for isolation
                            )
                            if trade_id:
                                log_func(f"🔍 Found open trade by ticker in {handler.name}: {trade_id}")
                                active_position = {'trade_id': trade_id}

                    # Fill in missing contract details with CHANNEL-SPECIFIC fallback
                    symbol = trade_obj.get("ticker") or active_position.get("symbol")
                    strike = trade_obj.get("strike") or active_position.get("strike")
                    expiration = trade_obj.get("expiration") or active_position.get("expiration")
                    opt_type = trade_obj.get("type") or active_position.get("type")
                    
                    # CHANNEL-ISOLATED feedback lookup
                    if symbol and (not strike or not expiration or not opt_type):
                        log_func(f"🔍 Incomplete contract info for {symbol} in {handler.name}, checking feedback history...")
                        recent_parse = self.feedback_logger.get_recent_parse_for_channel(handler.name, symbol)
                        if recent_parse:
                            strike = strike or recent_parse.get('strike')
                            expiration = expiration or recent_parse.get('expiration') 
                            opt_type = opt_type or recent_parse.get('type')
                            log_func(f"✅ Found previous parse in {handler.name}: {symbol} ${strike}{opt_type} {expiration}")
                    
                    trade_obj.update({
                        'ticker': symbol, 
                        'strike': strike, 
                        'expiration': expiration, 
                        'type': opt_type
                    })

                    if not all([symbol, strike, expiration, opt_type]):
                        log_func(f"❌ Missing contract info for {handler.name}: {trade_obj}", "ERROR")
                        continue

                    # Execute the trade based on action
                    execution_success = False
                    result_summary = ""

                    if action == "buy":
                        execution_success, result_summary = self._execute_buy_order(
                            trader, trade_obj, config, log_func
                        )
                        
                        if execution_success:
                            trade_id = f"trade_{int(datetime.now().timestamp() * 1000)}"
                            trade_obj['trade_id'] = trade_id
                            
                            # Calculate and schedule stop loss
                            price = trade_obj.get('price', 0)
                            if price > 0:
                                stop_price = self._round_to_tick(
                                    price * (1 - config.get("initial_stop_loss", 0.50)), 
                                    trader.get_instrument_tick_size(symbol) or 0.05
                                )
                                
                                log_func(f"⏱️ Scheduling stop loss for {STOP_LOSS_DELAY_SECONDS/60:.0f} minutes @ ${stop_price:.2f}")
                                
                                stop_data = {
                                    'trader': trader,
                                    'symbol': symbol,
                                    'strike': strike,
                                    'expiration': expiration,
                                    'opt_type': opt_type,
                                    'quantity': trade_obj.get('quantity', 1),
                                    'stop_price': stop_price
                                }
                                
                                self.stop_loss_manager.schedule_stop_loss(trade_id, stop_data, STOP_LOSS_DELAY_SECONDS)
                                trade_obj['stop_loss_price'] = stop_price
                                trade_obj['stop_loss_scheduled'] = True
                            
                            # Record entry with channel information
                            self.performance_tracker.record_entry(trade_obj)
                            self.position_manager.add_position(trade_obj['channel_id'], trade_obj)
                            
                            # Send alert
                            asyncio.create_task(self._send_trade_alert(
                                trade_obj, 'buy', trade_obj.get('quantity', 1), 
                                trade_obj.get('price', 0), is_sim_mode
                            ))

                    elif action in ("trim", "exit", "stop"):
                        trade_id = active_position.get('trade_id') if active_position else None
                        if not trade_id and trade_obj.get('ticker'):
                            trade_id = self.performance_tracker.find_open_trade_by_ticker(
                                trade_obj['ticker'], handler.name  # Channel-specific lookup
                            )
                        
                        execution_success, result_summary = self._execute_sell_order(
                            trader, trade_obj, config, log_func, active_position
                        )
                        
                        if execution_success and trade_id:
                            if action == "trim":
                                trade_record = self.performance_tracker.record_trim(trade_id, {
                                    'quantity': trade_obj.get('quantity', 1),
                                    'price': trade_obj.get('price', 0),
                                    'ticker': trade_obj.get('ticker')
                                })
                                
                                # Enhanced trailing stop logic
                                self._handle_trailing_stop(
                                    trader, trade_obj, config, active_position, log_func, is_sim_mode
                                )
                                
                            else:  # exit or stop
                                trade_record = self.performance_tracker.record_exit(trade_id, {
                                    'price': trade_obj.get('price', 0),
                                    'action': action,
                                    'is_stop_loss': action == 'stop',
                                    'ticker': trade_obj.get('ticker')
                                })
                                
                                if trade_record:
                                    self.position_manager.clear_position(trade_obj['channel_id'], trade_id)
                            
                            # Send alert with P&L data
                            if 'trade_record' in locals():
                                asyncio.create_task(self._send_trade_alert(
                                    trade_obj, action, trade_obj.get('quantity', 1), 
                                    trade_obj.get('price', 0), is_sim_mode, locals().get('trade_record')
                                ))

                    log_func(f"📊 Trade Summary: {result_summary}")

                except Exception as trade_error:
                    log_func(f"❌ Trade execution failed: {trade_error}", "ERROR")

        except Exception as e:
            log_func(f"❌ Critical trade processing error: {e}", "ERROR")
    
    def _normalize_keys(self, data: dict) -> dict:
        """Normalize dictionary keys"""
        if not isinstance(data, dict): 
            return data
        
        cleaned_data = {k.lower().replace(' ', '_'): v for k, v in data.items()}
        
        if 'option_type' in cleaned_data: 
            cleaned_data['type'] = cleaned_data.pop('option_type')
        if 'entry_price' in cleaned_data: 
            cleaned_data['price'] = cleaned_data.pop('entry_price')
        
        if 'ticker' in cleaned_data and isinstance(cleaned_data['ticker'], str):
            cleaned_data['ticker'] = cleaned_data['ticker'].replace('$', '').upper()    
        return cleaned_data
    
    def _round_to_tick(self, price: float, tick_size: float, round_up: bool = False) -> float:
        """Round to tick size with optional round up"""
        if tick_size is None or tick_size == 0:
            tick_size = 0.05
        
        if round_up:
            import math
            ticks = math.ceil(price / tick_size)
        else:
            ticks = round(price / tick_size)
        
        rounded = ticks * tick_size
        if rounded < tick_size:
            rounded = tick_size
        
        return round(rounded, 2)
    
    def _monitor_order_fill(self, trader, order_id, max_wait_time=600):
        """Monitor order fill with exponential backoff"""
        start_time = time.time()
        check_intervals = [5, 10, 15, 20, 30, 30, 60, 60, 60, 60, 70, 80, 100]
        total_elapsed = 0
        
        for interval in check_intervals:
            if total_elapsed >= max_wait_time:
                break
                
            time.sleep(interval)
            total_elapsed += interval
            
            try:
                order_info = trader.get_option_order_info(order_id)
                
                if order_info and order_info.get('state') == 'filled':
                    elapsed_time = time.time() - start_time
                    print(f"✅ Order {order_id} filled after {elapsed_time:.1f} seconds")
                    return True, elapsed_time
                    
                elif order_info and order_info.get('state') in ['cancelled', 'rejected', 'failed']:
                    elapsed_time = time.time() - start_time
                    print(f"❌ Order {order_id} {order_info.get('state')} after {elapsed_time:.1f} seconds")
                    return False, elapsed_time
                    
                elapsed_time = time.time() - start_time
                print(f"⏳ Order {order_id} still pending after {elapsed_time:.1f} seconds...")
                
            except Exception as e:
                print(f"❌ Order monitoring error: {e}")
                continue
        
        # Cancel order if timeout
        try:
            trader.cancel_option_order(order_id)
            print(f"⏰ Order {order_id} cancelled due to timeout")
        except:
            pass
        
        elapsed_time = time.time() - start_time
        print(f"⏰ Order {order_id} monitoring timeout after {elapsed_time:.1f} seconds")
        return False, elapsed_time

    def _execute_buy_order(self, trader, trade_obj, config, log_func):
        """Execute buy order with enhanced error handling"""
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            price = float(trade_obj.get('price', 0))
            size = trade_obj.get('size', 'full')
            
            if price <= 0:
                log_func("❌ Invalid price for buy order")
                return False, "Invalid price"
            
            # Calculate position sizing
            portfolio_value = trader.get_portfolio_value()
            allocation = MAX_PCT_PORTFOLIO * POSITION_SIZE_MULTIPLIERS.get(size, 1.0) * config["multiplier"]
            max_amount = min(allocation * portfolio_value, MAX_DOLLAR_AMOUNT)
            
            # Apply channel-specific padding
            buy_padding = config.get("buy_padding", DEFAULT_BUY_PRICE_PADDING)
            tick_size = trader.get_instrument_tick_size(symbol) or 0.05
            padded_price = self._round_to_tick(price * (1 + buy_padding), tick_size, round_up=True)
            
            contracts = max(MIN_TRADE_QUANTITY, int(max_amount / (padded_price * 100)))
            
            # Store quantity in trade_obj
            trade_obj['quantity'] = contracts
            trade_obj['price'] = padded_price
            
            log_func(f"📤 Placing buy: {contracts}x {symbol} {strike}{opt_type} @ ${padded_price:.2f}")
            
            # Place order
            buy_response = trader.place_option_buy_order(symbol, strike, expiration, opt_type, contracts, padded_price)
            
            if isinstance(trader.__class__.__name__, 'SimulatedTrader') or hasattr(trader, 'simulated_orders'):
                return True, f"Simulated buy: {contracts}x {symbol}"
            
            order_id = buy_response.get('id')
            if order_id:
                log_func(f"⏳ Monitoring order {order_id}...")
                filled, fill_time = self._monitor_order_fill(trader, order_id, max_wait_time=600)
                
                if filled:
                    log_func(f"✅ Buy order filled in {fill_time:.1f}s")
                    return True, f"Buy filled: {contracts}x {symbol} @ ${padded_price:.2f}"
                else:
                    log_func("❌ Buy order timed out")
                    return False, "Order timeout"
            else:
                log_func(f"❌ Buy order failed: {buy_response}")
                return False, f"Order failed: {buy_response.get('error', 'Unknown error')}"
                
        except Exception as e:
            log_func(f"❌ Buy execution error: {e}")
            return False, str(e)

    def _execute_sell_order(self, trader, trade_obj, config, log_func, active_position):
        """Execute sell order with enhanced error handling"""
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            action = trade_obj.get('action', 'exit')
            
            # Get position quantity
            if isinstance(trader.__class__.__name__, 'SimulatedTrader') or hasattr(trader, 'simulated_orders'):
                total_quantity = 10
            else:
                all_positions = trader.get_open_option_positions()
                position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
                if not position:
                    log_func(f"❌ No position found for {symbol}")
                    return False, "No position found"
                total_quantity = int(float(position.get('quantity', 0)))
            
            # Determine quantity to sell
            if action == "trim":
                sell_quantity = max(1, total_quantity // 2)
            else:
                sell_quantity = total_quantity
            
            trade_obj['quantity'] = sell_quantity
            
            # Cancel existing orders first
            log_func(f"🚫 Cancelling existing orders for {symbol}...")
            cancelled = trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
            if cancelled > 0:
                log_func(f"✅ Cancelled {cancelled} existing orders")
            
            # Get market price and apply padding
            sell_padding = config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
            
            log_func(f"📊 Getting market price for {symbol} {strike}{opt_type}...")
            market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
            
            market_price = None
            if market_data and len(market_data) > 0:
                data = market_data[0]
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                if isinstance(data, dict):
                    mark_price = data.get('mark_price')
                    if mark_price and float(mark_price) > 0:
                        market_price = float(mark_price)
                        log_func(f"📈 Using mark price: ${market_price:.2f}")
                    else:
                        bid = float(data.get('bid_price', 0) or 0)
                        ask = float(data.get('ask_price', 0) or 0)
                        if bid > 0 and ask > 0:
                            market_price = (bid + ask) / 2
                            log_func(f"📈 Using bid/ask midpoint: ${market_price:.2f}")
                        elif bid > 0:
                            market_price = bid
                            log_func(f"📈 Using bid price: ${market_price:.2f}")
            
            # Fallback price
            if not market_price or market_price <= 0:
                specified_price = trade_obj.get('price', 0)
                if specified_price and specified_price > 0:
                    market_price = specified_price * 0.9
                    log_func(f"⚠️ Using discounted specified price: ${market_price:.2f}")
                else:
                    market_price = 0.05
                    log_func(f"🚨 Using emergency minimum price: ${market_price:.2f}")
            
            # Apply padding and round to tick
            final_price = market_price * (1 - sell_padding)
            tick_size = trader.get_instrument_tick_size(symbol) or 0.05
            final_price = self._round_to_tick(final_price, tick_size)
            
            trade_obj['price'] = final_price
            
            log_func(f"📤 Placing {action}: {sell_quantity}x {symbol} @ ${final_price:.2f}")
            
            # Place sell order
            sell_response = trader.place_option_sell_order(
                symbol, strike, expiration, opt_type, sell_quantity, 
                limit_price=final_price, sell_padding=sell_padding
            )
            
            if isinstance(trader.__class__.__name__, 'SimulatedTrader') or hasattr(trader, 'simulated_orders'):
                return True, f"Simulated {action}: {sell_quantity}x {symbol}"
            
            if sell_response and not sell_response.get('error'):
                log_func(f"✅ {action.title()} order placed successfully")
                return True, f"{action.title()}: {sell_quantity}x {symbol} @ ${final_price:.2f}"
            else:
                log_func(f"❌ {action.title()} order failed: {sell_response}")
                return False, f"{action.title()} failed: {sell_response.get('error', 'Unknown error')}"
                
        except Exception as e:
            log_func(f"❌ {action.title()} execution error: {e}")
            return False, str(e)

    def _handle_trailing_stop(self, trader, trade_obj, config, active_position, log_func, is_sim_mode):
        """Handle trailing stop logic for remaining position"""
        try:
            if not active_position:
                return
                
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            
            if is_sim_mode:
                log_func(f"📊 [SIMULATED] Would place trailing stop for remaining position")
                return
            
            all_positions = trader.get_open_option_positions()
            remaining_position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
            
            if remaining_position:
                remaining_qty = int(float(remaining_position.get('quantity', 0)))
                purchase_price = float(active_position.get("purchase_price", 0.0))
                
                # Get current market price for trailing stop calculation
                market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
                current_market_price = purchase_price
                
                if market_data and len(market_data) > 0 and isinstance(market_data[0], dict):
                    rec = market_data[0]
                    mark_price = rec.get('mark_price')
                    if mark_price:
                        current_market_price = float(mark_price)
                    else:
                        bid = float(rec.get('bid_price', 0) or 0)
                        ask = float(rec.get('ask_price', 0) or 0)
                        if bid and ask:
                            current_market_price = (bid + ask) / 2
                
                # Calculate trailing stop
                trailing_stop_pct = config.get("trailing_stop_loss_pct", 0.20)
                trailing_stop_candidate = current_market_price * (1 - trailing_stop_pct)
                new_stop_price = max(trailing_stop_candidate, purchase_price)
                
                tick_size = trader.get_instrument_tick_size(symbol) or 0.05
                new_stop_price_rounded = self._round_to_tick(new_stop_price, tick_size)
                
                log_func(f"📊 Placing trailing stop for remaining {remaining_qty} contracts @ ${new_stop_price_rounded:.2f}")
                
                try:
                    new_stop_response = trader.place_option_stop_loss_order(
                        symbol, strike, expiration, opt_type, remaining_qty, new_stop_price_rounded
                    )
                    log_func(f"✅ Trailing stop placed: {new_stop_response}")
                except Exception as e:
                    log_func(f"❌ Failed to place trailing stop: {e}")
                    
        except Exception as e:
            log_func(f"❌ Trailing stop error: {e}")

    async def _send_trade_alert(self, trade_data, action, quantity, price, is_simulation, trade_record=None):
        """Send enhanced trade alert"""
        try:
            # Create enhanced alert embed
            alert_embed = self._create_trade_alert_embed(trade_data, action, quantity, price, is_simulation, trade_record)
            
            # Send to appropriate webhook
            await self.alert_manager.add_alert(
                PLAYS_WEBHOOK, 
                {"embeds": [alert_embed]}, 
                "trade_alert", 
                priority=1
            )
            
            print(f"📨 Trade alert queued: {action} {trade_data.get('ticker', 'Unknown')}")
            
        except Exception as e:
            print(f"❌ Error sending trade alert: {e}")

    def _create_trade_alert_embed(self, trade_data, action, quantity, price, is_simulation, trade_record=None):
        """Create comprehensive trade alert embed"""
        
        # Determine color based on action
        colors = {
            'buy': 0x00C851,
            'sell': 0xFF4444,
            'trim': 0xFF8800,
            'exit': 0xFF4444
        }
        
        # Determine emoji
        emojis = {
            'buy': '🟢',
            'sell': '🔴', 
            'trim': '🟡',
            'exit': '🔴'
        }
        
        embed = {
            "title": f"{emojis.get(action, '')} {'[SIM]' if is_simulation else '[LIVE]'} {trade_data.get('channel', 'Unknown')} • {action.upper()} • {trade_data.get('ticker', 'Unknown')}",
            "color": colors.get(action, 0x888888),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [],
            "footer": {"text": "RHTB v4 Enhanced"}
        }
        
        # Contract details
        contract_info = f"**{trade_data.get('ticker', 'N/A')}** ${trade_data.get('strike', 0)}{trade_data.get('type', 'N/A')[0].upper() if trade_data.get('type') else 'N/A'}"
        try:
            exp_date = datetime.fromisoformat(trade_data.get('expiration', '')).strftime('%m/%d/%y')
            contract_info += f" {exp_date}"
        except:
            contract_info += f" {trade_data.get('expiration', 'N/A')}"
        
        embed["fields"].append({
            "name": "📈 Contract Details",
            "value": contract_info,
            "inline": True
        })
        
        # Execution details
        position_value = price * quantity * 100
        execution_info = f"""
**Quantity:** {quantity} contracts
**Price:** ${price:.2f}
**Total Value:** ${position_value:,.2f}
        """.strip()
        
        embed["fields"].append({
            "name": "💰 Execution Details", 
            "value": execution_info,
            "inline": True
        })
        
        # P&L information if available
        if trade_record and hasattr(trade_record, 'pnl_percent'):
            pnl_emoji = "🟢" if trade_record.pnl_percent > 0 else "🔴"
            pnl_info = f"""
{pnl_emoji} **P&L:** {trade_record.pnl_percent:+.2f}%
**Dollar P&L:** ${trade_record.pnl_dollars:+,.2f}
            """.strip()
            
            embed["fields"].append({
                "name": "📊 Performance",
                "value": pnl_info,
                "inline": True
            })
        
        if is_simulation:
            embed["author"] = {"name": "🧪 SIMULATION MODE"}
        
        return embed