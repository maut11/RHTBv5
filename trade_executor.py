# trade_executor.py - Enhanced Trade Execution with Symbol Mapping
import asyncio
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import json
import csv
import os
import math

from config import (
    CHANNELS_CONFIG, POSITION_SIZE_MULTIPLIERS, MAX_PCT_PORTFOLIO, 
    MAX_DOLLAR_AMOUNT, MIN_TRADE_QUANTITY, DEFAULT_BUY_PRICE_PADDING,
    DEFAULT_SELL_PRICE_PADDING, STOP_LOSS_DELAY_SECONDS,
    ALL_NOTIFICATION_WEBHOOK, PLAYS_WEBHOOK,
    get_broker_symbol, get_trader_symbol, get_all_symbol_variants,
    SYMBOL_NORMALIZATION_CONFIG
)

class ChannelAwareFeedbackLogger:
    """Enhanced feedback logger with symbol mapping support"""
    
    def __init__(self, filename="parsing_feedback.csv"):
        self.filename = filename
        self.lock = threading.Lock()
        self._initialize_file()

    def _initialize_file(self):
        """Creates the CSV file with headers if it doesn't exist."""
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
                            "Timestamp",
                            "Trader Symbol",
                            "Broker Symbol"
                        ])

    def log(self, channel_name, original_message, parsed_message_json, latency=0):
        """Log parse result with symbol mapping information"""
        with self.lock:
            try:
                # Extract symbol information
                trader_symbol = parsed_message_json.get('ticker', '')
                broker_symbol = get_broker_symbol(trader_symbol) if trader_symbol else ''
                
                with open(self.filename, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        channel_name,
                        original_message,
                        json.dumps(parsed_message_json),
                        f"{latency:.2f}",
                        datetime.now(timezone.utc).isoformat(),
                        trader_symbol,
                        broker_symbol
                    ])
            except Exception as e:
                print(f"❌ Failed to write to feedback log: {e}")
    
    def get_recent_parse_for_channel(self, channel_name: str, ticker: str):
        """Get most recent successful parse for ticker within specific channel, handling symbol variants"""
        try:
            with self.lock:
                if not os.path.exists(self.filename):
                    return None
                
                # Get all symbol variants for the search
                symbol_variants = get_all_symbol_variants(ticker)
                
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
                                    if isinstance(parsed_data, dict):
                                        parsed_ticker = parsed_data.get('ticker', '').upper()
                                        
                                        # Check if the parsed ticker matches any of our symbol variants
                                        if (parsed_ticker in symbol_variants and
                                            parsed_data.get('strike') and 
                                            parsed_data.get('expiration') and 
                                            parsed_data.get('type')):
                                            recent_parses.append(parsed_data)
                                except:
                                    continue
                    
                    if recent_parses:
                        most_recent = recent_parses[-1]
                        if ticker != most_recent.get('ticker'):
                            print(f"🔄 Symbol variant match in feedback: {ticker} → {most_recent.get('ticker')}")
                        return most_recent
                    
                    return None
                    
        except Exception as e:
            print(f"❌ Error reading feedback log: {e}")
            return None

class DelayedStopLossManager:
    """Manages delayed stop loss orders with symbol mapping"""
    
    def __init__(self):
        self.pending_stops = {}
        
    def schedule_stop_loss(self, trade_id: str, stop_data: dict, delay_seconds: int = 900):
        """Schedule a stop loss to be placed after delay"""
        def place_stop_after_delay():
            time.sleep(delay_seconds)
            print(f"⏰ Placing delayed stop loss for trade {trade_id}")
            
            trader = stop_data['trader']
            try:
                # Symbol is already normalized in stop_data
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
    """Channel-aware trade execution with symbol mapping support"""
    
    def __init__(self, live_trader, sim_trader, performance_tracker, position_manager, alert_manager):
        self.live_trader = live_trader
        self.sim_trader = sim_trader
        self.performance_tracker = performance_tracker
        self.position_manager = position_manager
        self.alert_manager = alert_manager
        
        # Enhanced feedback logger with symbol mapping
        self.feedback_logger = ChannelAwareFeedbackLogger()
        self.stop_loss_manager = DelayedStopLossManager()
        
        print("✅ Trade Executor initialized with symbol mapping support")
    
    async def process_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id=None, is_edit=False, event_loop=None):
        """Main trade processing entry point with proper async support"""
        
        # Store the event loop reference
        if event_loop:
            self.event_loop = event_loop
        else:
            self.event_loop = asyncio.get_running_loop()
        
        def enhanced_log(msg, level="INFO"):
            print(f"ℹ️ {msg}")
            
            # Use asyncio.run_coroutine_threadsafe to safely call async functions from sync context
            if level == "ERROR":
                future = asyncio.run_coroutine_threadsafe(
                    self.alert_manager.send_error_alert(msg), 
                    self.event_loop
                )
            else:
                future = asyncio.run_coroutine_threadsafe(
                    self.alert_manager.add_alert(
                        ALL_NOTIFICATION_WEBHOOK, {"content": msg}, 
                        f"{level.lower()}_notification"
                    ), 
                    self.event_loop
                )
            
            # Don't block on the result, just schedule it
            try:
                future.result(timeout=0.1)  # Quick timeout to avoid blocking
            except:
                pass  # Don't block if alert system is slow
        
        # Run trade processing in thread pool to avoid blocking
        await self.event_loop.run_in_executor(
            None, 
            self._blocking_handle_trade,
            handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, enhanced_log
        )
    
    def _blocking_handle_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, log_func):
        """Blocking trade execution logic with symbol mapping"""
        try:
            log_func(f"🔄 Processing message from {handler.name}: {raw_msg[:100]}...")
            
            # Parse the message
            try:
                parsed_results, latency_ms = handler.parse_message(message_meta, received_ts, log_func)
                
                if parsed_results:
                    for parsed_obj in parsed_results:
                        # Log with CHANNEL-SPECIFIC feedback including symbol mapping
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
                    
                    # Enhanced contract resolution with symbol mapping
                    trade_obj['channel'] = handler.name
                    trade_obj['channel_id'] = handler.channel_id
                    
                    # Normalize symbol early for consistent handling
                    if trade_obj.get('ticker'):
                        original_symbol = trade_obj['ticker']
                        broker_symbol = get_broker_symbol(original_symbol)
                        if original_symbol != broker_symbol:
                            log_func(f"🔄 Symbol mapping: {original_symbol} → {broker_symbol}")
                        trade_obj['trader_symbol'] = original_symbol
                        trade_obj['broker_symbol'] = broker_symbol
                    
                    # Try to find active position for trim/exit actions
                    active_position = None
                    if action in ("trim", "exit", "stop"):
                        # FIRST: Try position manager with symbol variants
                        active_position = self.position_manager.find_position(trade_obj['channel_id'], trade_obj) or {}
                        
                        # SECOND: Try performance tracker with symbol variants
                        if not active_position and trade_obj.get('ticker'):
                            # Pass the original ticker, performance tracker should handle variants
                            trade_id = self.performance_tracker.find_open_trade_by_ticker(
                                trade_obj['ticker'], handler.name
                            )
                            if trade_id:
                                log_func(f"🔍 Found open trade by ticker in {handler.name}: {trade_id}")
                                active_position = {'trade_id': trade_id}

                    # Fill in missing contract details with symbol mapping support
                    symbol = trade_obj.get("ticker") or (active_position.get("trader_symbol") or active_position.get("symbol") if active_position else None)
                    strike = trade_obj.get("strike") or (active_position.get("strike") if active_position else None)
                    expiration = trade_obj.get("expiration") or (active_position.get("expiration") if active_position else None)
                    opt_type = trade_obj.get("type") or (active_position.get("type") if active_position else None)
                    
                    # Handle BE (Break Even) price
                    if trade_obj.get('price') == 'BE' or str(trade_obj.get('price', '')).upper() == 'BE':
                        if active_position:
                            entry_price = active_position.get('entry_price') or active_position.get('purchase_price')
                            if entry_price:
                                trade_obj['price'] = entry_price
                                trade_obj['is_breakeven'] = True
                                log_func(f"💹 Using break-even price: ${entry_price:.2f}")
                            else:
                                log_func(f"⚠️ BE requested but no entry price found, using fallback")
                        else:
                            log_func(f"⚠️ BE requested but no position found")
                    
                    # CHANNEL-ISOLATED feedback lookup with symbol mapping
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
                        # ========== TRADE-FIRST WORKFLOW ==========
                        print(f"⚡ EXECUTING TRADE FIRST: {action.upper()} {symbol}")
                        execution_success, result_summary = self._execute_buy_order(
                            trader, trade_obj, config, log_func
                        )
                        
                        if execution_success:
                            trade_id = f"trade_{int(datetime.now().timestamp() * 1000)}"
                            trade_obj['trade_id'] = trade_id
                            
                            # ========== ASYNC NON-BLOCKING UPDATES (AFTER TRADE) ==========
                            # Fire these tasks asynchronously - don't wait for them
                            print(f"📊 TRADE PLACED SUCCESSFULLY - Starting async updates...")
                            
                            # 1. Schedule stop loss (non-blocking)
                            price = trade_obj.get('price', 0)
                            if price > 0 and not trade_obj.get('is_breakeven'):
                                try:
                                    stop_price = trader.round_to_tick(
                                        price * (1 - config.get("initial_stop_loss", 0.50)), 
                                        symbol, round_up_for_buy=False
                                    )
                                    
                                    print(f"⏱️ Scheduling stop loss for {STOP_LOSS_DELAY_SECONDS/60:.0f} min @ ${stop_price:.2f}")
                                    
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
                                except Exception as e:
                                    print(f"⚠️ Stop loss scheduling failed (non-critical): {e}")
                            
                            # 2. Record in tracking systems (async, non-blocking)
                            try:
                                self.performance_tracker.record_entry(trade_obj)
                                self.position_manager.add_position(trade_obj['channel_id'], trade_obj)
                                print(f"✅ Position tracking updated")
                            except Exception as e:
                                print(f"⚠️ Position tracking failed (non-critical): {e}")
                            
                            # 3. Send alerts (async, fire-and-forget)
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    self._send_trade_alert(
                                        trade_obj, 'buy', trade_obj.get('quantity', 1), 
                                        trade_obj.get('price', 0), is_sim_mode
                                    ), 
                                    self.event_loop
                                )
                                print(f"📨 Alert queued (async)")
                            except Exception as e:
                                print(f"⚠️ Alert failed (non-critical): {e}")

                    elif action in ("trim", "exit", "stop"):
                        # ========== TRADE-FIRST WORKFLOW ==========
                        print(f"⚡ EXECUTING TRADE FIRST: {action.upper()} {symbol}")
                        
                        # Get trade ID for tracking
                        trade_id = active_position.get('trade_id') if active_position else None
                        if not trade_id and trade_obj.get('ticker'):
                            trade_id = self.performance_tracker.find_open_trade_by_ticker(
                                trade_obj['ticker'], handler.name
                            )
                        
                        # EXECUTE THE TRADE IMMEDIATELY (highest priority)
                        execution_success, result_summary = self._execute_sell_order(
                            trader, trade_obj, config, log_func, active_position
                        )
                        
                        if execution_success and trade_id:
                            # ========== ASYNC NON-BLOCKING UPDATES (AFTER TRADE) ==========
                            print(f"📊 TRADE PLACED SUCCESSFULLY - Starting async updates...")
                            
                            try:
                                if action == "trim":
                                    # Record trim (non-blocking)
                                    trade_record = self.performance_tracker.record_trim(trade_id, {
                                        'quantity': trade_obj.get('quantity', 1),
                                        'price': trade_obj.get('price', 0),
                                        'ticker': trade_obj.get('ticker'),
                                        'channel': handler.name
                                    })
                                    
                                    # Handle trailing stop (async, non-critical)
                                    try:
                                        self._handle_trailing_stop(
                                            trader, trade_obj, config, active_position, log_func, is_sim_mode
                                        )
                                        print(f"✅ Trailing stop handled")
                                    except Exception as e:
                                        print(f"⚠️ Trailing stop failed (non-critical): {e}")
                                    
                                else:  # exit or stop
                                    # Record exit (non-blocking)
                                    trade_record = self.performance_tracker.record_exit(trade_id, {
                                        'price': trade_obj.get('price', 0),
                                        'action': action,
                                        'is_stop_loss': action == 'stop',
                                        'ticker': trade_obj.get('ticker'),
                                        'channel': handler.name
                                    })
                                    
                                    if trade_record:
                                        self.position_manager.clear_position(trade_obj['channel_id'], trade_id)
                                        print(f"✅ Position cleared")
                                
                                print(f"✅ Performance tracking updated")
                                
                            except Exception as e:
                                print(f"⚠️ Performance tracking failed (non-critical): {e}")
                            
                            # Send alerts (async, fire-and-forget)
                            try:
                                asyncio.run_coroutine_threadsafe(
                                    self._send_trade_alert(
                                        trade_obj, action, trade_obj.get('quantity', 1), 
                                        trade_obj.get('price', 0), is_sim_mode, locals().get('trade_record')
                                    ), 
                                    self.event_loop
                                )
                                print(f"📨 Alert queued (async)")
                            except Exception as e:
                                print(f"⚠️ Alert failed (non-critical): {e}")

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
        """OPTIMIZED: Execute buy order with TRADE-FIRST, ALERT-LAST workflow"""
        try:
            # Symbol normalization is handled by the trader
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            price = float(trade_obj.get('price', 0))
            size = trade_obj.get('size', 'full')
            
            if price <= 0:
                log_func("❌ Invalid price for buy order")
                return False, "Invalid price"
            
            # PRE-CALCULATE everything for speed (no delays during execution)
            portfolio_value = trader.get_portfolio_value()
            size_multiplier = POSITION_SIZE_MULTIPLIERS.get(size, 1.0)
            channel_multiplier = config["multiplier"]
            allocation = MAX_PCT_PORTFOLIO * size_multiplier * channel_multiplier
            max_amount = min(allocation * portfolio_value, MAX_DOLLAR_AMOUNT)
            
            # Apply channel-specific padding with OPTIMIZED tick rounding
            buy_padding = config.get("buy_padding", DEFAULT_BUY_PRICE_PADDING)
            
            # CRITICAL: Use trader's optimized tick rounding with round_up for buys
            padded_price = price * (1 + buy_padding)
            final_price = trader.round_to_tick(padded_price, symbol, round_up_for_buy=True)
            
            contracts = max(MIN_TRADE_QUANTITY, int(max_amount / (final_price * 100)))
            
            # ENHANCED: Show size calculation details
            print(f"💰 SIZE CALCULATION BREAKDOWN:")
            print(f"   Portfolio Value: ${portfolio_value:,.2f}")
            print(f"   Max % Portfolio: {MAX_PCT_PORTFOLIO * 100}%")
            print(f"   Size Multiplier: {size_multiplier} ({size})")
            print(f"   Channel Multiplier: {channel_multiplier}")
            print(f"   Allocation: {allocation * 100:.2f}%")
            print(f"   Max Dollar Amount: ${max_amount:,.2f}")
            print(f"   Contract Price: ${final_price:.2f}")
            print(f"   Calculated Contracts: {int(max_amount / (final_price * 100))}")
            print(f"   Final Contracts: {contracts} (min: {MIN_TRADE_QUANTITY})")
            
            # Store for later use (including size calculation details)
            trade_obj['quantity'] = contracts
            trade_obj['price'] = final_price
            trade_obj['size_calculation'] = {
                'portfolio_value': portfolio_value,
                'max_pct_portfolio': MAX_PCT_PORTFOLIO * 100,
                'size_multiplier': size_multiplier,
                'size_name': size,
                'channel_multiplier': channel_multiplier,
                'allocation_pct': allocation * 100,
                'max_dollar_amount': max_amount,
                'contract_price': final_price,
                'calculated_contracts': int(max_amount / (final_price * 100)),
                'final_contracts': contracts,
                'min_quantity': MIN_TRADE_QUANTITY
            }
            
            # SPEED OPTIMIZATION: Minimal logging during execution
            print(f"⚡ FAST BUY: {contracts}x {symbol} {strike}{opt_type} @ ${final_price:.2f}")
            
            # ========== TRADE FIRST (HIGHEST PRIORITY) ==========
            start_time = time.time()
            buy_response = trader.place_option_buy_order(symbol, strike, expiration, opt_type, contracts, final_price)
            execution_time = time.time() - start_time
            
            # Check result immediately
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                print(f"✅ SIMULATED buy executed in {execution_time:.3f}s")
                return True, f"Simulated buy: {contracts}x {symbol}"
            
            order_id = buy_response.get('id')
            if not order_id:
                print(f"❌ Buy order FAILED: {buy_response}")
                return False, f"Order failed: {buy_response.get('error', 'Unknown error')}"
            
            print(f"✅ Buy order PLACED in {execution_time:.3f}s: {order_id}")
            
            # SPEED DECISION: For critical speed, return success immediately
            # Order monitoring will happen asynchronously
            return True, f"Buy order placed: {contracts}x {symbol} @ ${final_price:.2f} (ID: {order_id})"
                
        except Exception as e:
            print(f"❌ CRITICAL buy execution error: {e}")
            log_func(f"❌ Buy execution error: {e}")
            return False, str(e)

    def _execute_sell_order(self, trader, trade_obj, config, log_func, active_position):
        """OPTIMIZED: Execute sell order with TRADE-FIRST, ALERT-LAST workflow"""
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            action = trade_obj.get('action', 'exit')
            
            # PRE-CALCULATE position quantity
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                total_quantity = 10
            else:
                # SPEED OPTIMIZATION: Get positions once
                all_positions = trader.get_open_option_positions()
                position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
                if not position:
                    print(f"❌ No position found for {symbol}")
                    return False, "No position found"
                total_quantity = int(float(position.get('quantity', 0)))
            
            # Determine quantity
            sell_quantity = max(1, total_quantity // 2) if action == "trim" else total_quantity
            trade_obj['quantity'] = sell_quantity
            
            # PRE-CANCEL existing orders (non-blocking for speed)
            print(f"🚫 Cancelling existing orders for {symbol}...")
            try:
                cancelled = trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
                if cancelled > 0:
                    print(f"✅ Cancelled {cancelled} existing orders")
            except Exception as e:
                print(f"⚠️ Order cancellation failed (proceeding anyway): {e}")
            
            # SPEED-OPTIMIZED price calculation
            sell_padding = config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
            market_price = None
            
            # Check breakeven first (fastest path)
            if trade_obj.get('is_breakeven'):
                market_price = trade_obj.get('price')
                print(f"💹 BE price: ${market_price:.2f}")
            else:
                # FAST market data fetch
                try:
                    market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
                    if market_data and len(market_data) > 0:
                        data = market_data[0] if not isinstance(market_data[0], list) else market_data[0][0]
                        if isinstance(data, dict):
                            # Priority order for speed: mark -> midpoint -> bid
                            mark_price = data.get('mark_price')
                            if mark_price and float(mark_price) > 0:
                                market_price = float(mark_price)
                                print(f"📈 Mark price: ${market_price:.2f}")
                            else:
                                bid = float(data.get('bid_price', 0) or 0)
                                ask = float(data.get('ask_price', 0) or 0)
                                if bid > 0 and ask > 0:
                                    market_price = (bid + ask) / 2
                                    print(f"📈 Midpoint: ${market_price:.2f}")
                                elif bid > 0:
                                    market_price = bid
                                    print(f"📈 Bid: ${market_price:.2f}")
                except Exception as e:
                    print(f"⚠️ Market data error: {e}")
            
            # EMERGENCY pricing (absolute fallback)
            if not market_price or market_price <= 0:
                if active_position and active_position.get('entry_price'):
                    market_price = float(active_position['entry_price']) * 0.5  # Emergency 50%
                    print(f"🚨 Emergency price: ${market_price:.2f}")
                else:
                    market_price = 0.05  # Absolute minimum
                    print(f"🚨 Minimum price: ${market_price:.2f}")
            
            # OPTIMIZED: Apply padding and use trader's enhanced rounding
            padded_price = market_price * (1 - sell_padding)
            final_price = trader.round_to_tick(padded_price, symbol, round_up_for_buy=False)
            trade_obj['price'] = final_price
            
            print(f"⚡ ENHANCED {action.upper()}: {sell_quantity}x {symbol} @ ${final_price:.2f}")
            
            # ========== ENHANCED: TRADE WITH RETRY LOGIC ==========
            start_time = time.time()
            
            # Use enhanced sell order with retry logic
            sell_response = trader.place_option_sell_order_with_retry(
                symbol, strike, expiration, opt_type, sell_quantity, 
                limit_price=final_price, sell_padding=sell_padding, max_retries=3
            )
            execution_time = time.time() - start_time
            
            # Check result immediately
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                print(f"✅ SIMULATED {action} executed in {execution_time:.3f}s")
                return True, f"Simulated {action}: {sell_quantity}x {symbol}"
            
            if sell_response and not sell_response.get('error'):
                order_id = sell_response.get('id')
                print(f"✅ {action.upper()} order PLACED in {execution_time:.3f}s (ID: {order_id})")
                
                # ENHANCED: For trim orders, wait for confirmation before continuing
                if action == "trim" and order_id:
                    print(f"⏳ Waiting for TRIM order confirmation before stop loss...")
                    confirmation_result = trader.wait_for_order_confirmation(order_id, max_wait_seconds=180)
                    
                    if confirmation_result.get('status') == 'filled':
                        print(f"✅ TRIM order CONFIRMED - proceeding with stop loss")
                        # Store confirmation info for later use
                        trade_obj['trim_confirmed'] = True
                        trade_obj['trim_fill_time'] = confirmation_result.get('elapsed_time', 0)
                    else:
                        print(f"⚠️ TRIM order not confirmed: {confirmation_result.get('status')} - skipping stop loss")
                        trade_obj['trim_confirmed'] = False
                        trade_obj['skip_stop_loss'] = True  # Flag to skip stop loss
                
                return True, f"{action.title()}: {sell_quantity}x {symbol} @ ${final_price:.2f}"
            else:
                print(f"❌ {action.upper()} order FAILED: {sell_response}")
                return False, f"{action.title()} failed: {sell_response.get('error', 'Unknown error')}"
                
        except Exception as e:
            print(f"❌ CRITICAL {action} execution error: {e}")
            log_func(f"❌ {action.title()} execution error: {e}")
            return False, str(e)

    def _handle_trailing_stop(self, trader, trade_obj, config, active_position, log_func, is_sim_mode):
        """ENHANCED: Handle trailing stop logic with trim confirmation check"""
        try:
            if not active_position:
                return
                
            # ENHANCED: Check if trim was confirmed before placing stop loss
            if trade_obj.get('skip_stop_loss'):
                print(f"⚠️ Skipping stop loss due to unconfirmed trim order")
                log_func(f"⚠️ Stop loss skipped - trim order not confirmed")
                return
                
            if not trade_obj.get('trim_confirmed', True):  # Default True for non-trim actions
                print(f"⚠️ Trim not confirmed, delaying stop loss...")
                log_func(f"⚠️ Stop loss delayed - waiting for trim confirmation")
                return
                
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            
            if is_sim_mode or hasattr(trader, 'simulated_orders'):
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
            'exit': 0xFF4444,
            'stop': 0xFF0000
        }
        
        # Determine emoji
        emojis = {
            'buy': '🟢',
            'sell': '🔴', 
            'trim': '🟡',
            'exit': '🔴',
            'stop': '🛑'
        }
        
        trader_symbol = trade_data.get('trader_symbol') or trade_data.get('ticker', 'Unknown')
        
        embed = {
            "title": f"{emojis.get(action, '')} {'[SIM]' if is_simulation else '[LIVE]'} {trade_data.get('channel', 'Unknown')} • {action.upper()} • {trader_symbol}",
            "color": colors.get(action, 0x888888),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [],
            "footer": {"text": "RHTB v4 Enhanced"}
        }
        
        # Contract details
        contract_info = f"**{trader_symbol}** ${trade_data.get('strike', 0)}{trade_data.get('type', 'N/A')[0].upper() if trade_data.get('type') else 'N/A'}"
        try:
            exp_date_str = trade_data.get('expiration', '')
            if exp_date_str:
                exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').strftime('%m/%d/%y')
                contract_info += f" {exp_date}"
        except ValueError:
             contract_info += f" {trade_data.get('expiration', 'N/A')}"
        
        embed["fields"].append({
            "name": "📈 Contract Details",
            "value": contract_info,
            "inline": True
        })
        
        # Execution details
        position_value = price * quantity * 100 if isinstance(price, (int, float)) else 0
        execution_info = f"""
**Quantity:** {quantity} contracts
**Price:** ${price if isinstance(price, str) else f'{price:.2f}'}
**Total Value:** ${position_value:,.2f}
        """.strip()
        
        embed["fields"].append({
            "name": "💰 Execution Details", 
            "value": execution_info,
            "inline": True
        })
        
        # ENHANCED: Add size calculation details for buy orders
        if action == 'buy' and 'size_calculation' in trade_data:
            calc = trade_data['size_calculation']
            size_calc_info = f"""
**Portfolio:** ${calc['portfolio_value']:,.2f}
**Max %:** {calc['max_pct_portfolio']:.1f}%
**Size:** {calc['size_name']} ({calc['size_multiplier']:.2f}x)
**Channel Mult:** {calc['channel_multiplier']:.1f}x
**Allocation:** {calc['allocation_pct']:.2f}% = ${calc['max_dollar_amount']:,.2f}
**Calc Contracts:** {calc['calculated_contracts']}
**Final:** {calc['final_contracts']} (min: {calc['min_quantity']})
            """.strip()
            
            embed["fields"].append({
                "name": "🧮 Size Calculation",
                "value": size_calc_info,
                "inline": False  # Full width for better readability
            })
        
        # P&L information if available
        if trade_record and hasattr(trade_record, 'pnl_percent') and trade_record.pnl_percent is not None:
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