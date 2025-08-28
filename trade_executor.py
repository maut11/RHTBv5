# trade_executor.py - OPTIMIZED "Trade First, Alert Last" Implementation
import asyncio
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import logging
import math
import csv
import os
import json

from config import *

# Assuming a SimulatedTrader class exists for type checking, e.g.:
# class SimulatedTrader: pass 

class OptimizedTradeExecutor:
    """
    OPTIMIZED Trade Executor implementing "Trade First, Alert Last" approach
    for maximum speed and minimum latency on time-sensitive trades.
    """
    
    def __init__(self, live_trader, sim_trader, performance_tracker, position_manager, alert_manager):
        self.live_trader = live_trader
        self.sim_trader = sim_trader
        self.performance_tracker = performance_tracker
        self.position_manager = position_manager
        self.alert_manager = alert_manager
        
        # Enhanced feedback logger with channel isolation
        self.feedback_logger = ChannelAwareFeedbackLogger()
        self.stop_loss_manager = DelayedStopLossManager()
        
        # Performance metrics
        self.execution_times = []
        self.background_task_failures = 0
        
        print("✅ OPTIMIZED Trade Executor initialized - 'Trade First, Alert Last'")
    
    async def process_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id=None, is_edit=False, event_loop=None):
        """Main trade processing - OPTIMIZED for speed"""
        
        if event_loop:
            self.event_loop = event_loop
        else:
            self.event_loop = asyncio.get_running_loop()
        
        def enhanced_log(msg, level="INFO"):
            print(f"ℹ️ {msg}")
            # Fire and forget logging - don't block trade execution
            # CORRECTED: Use run_coroutine_threadsafe to schedule the task on the main event loop
            asyncio.run_coroutine_threadsafe(self._async_log(msg, level), self.event_loop)
        
        # Run OPTIMIZED trade processing
        await self.event_loop.run_in_executor(
            None, 
            self._optimized_trade_execution,
            handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, enhanced_log
        )
    
    def _optimized_trade_execution(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, log_func):
        """OPTIMIZED trade execution with 'Trade First, Alert Last'"""
        execution_start = time.time()
        
        try:
            log_func(f"🚀 FAST-TRACK processing: {handler.name}")
            
            # === PHASE 1: CRITICAL PATH - PARSING ONLY ===
            try:
                parsed_results, latency_ms = handler.parse_message(message_meta, received_ts, log_func)
                
                if parsed_results:
                    # Fire and forget - log feedback in background
                    asyncio.run_coroutine_threadsafe(
                        self._async_log_feedback(handler.name, raw_msg, parsed_results, latency_ms),
                        self.event_loop
                    )
                
                if not parsed_results:
                    log_func(f"⚠️ No parsed results from {handler.name}")
                    return
                    
            except Exception as e:
                log_func(f"❌ Parse error in {handler.name}: {e}", "ERROR")
                return

            # === PHASE 2: PROCESS EACH TRADE (TRADE FIRST) ===
            for raw_trade_obj in parsed_results:
                try:
                    trade_start_time = time.time()
                    
                    trade_obj = self._normalize_keys(raw_trade_obj)
                    action_value = trade_obj.get("action")
                    action = action_value.lower() if action_value else ""
                    
                    if not action or action == "null": 
                        continue

                    # Get config and trader
                    config = CHANNELS_CONFIG.get(handler.name)
                    if not config:
                        log_func(f"❌ No config found for {handler.name}", "ERROR")
                        continue

                    trader = self.live_trader if not is_sim_mode else self.sim_trader
                    
                    # === CRITICAL: CONTRACT RESOLUTION (OPTIMIZED) ===
                    trade_obj['channel'] = handler.name
                    trade_obj['channel_id'] = handler.channel_id
                    
                    # Fast contract resolution for trim/exit
                    if action in ("trim", "exit", "stop"):
                        active_position = self._fast_position_lookup(trade_obj, handler)
                        symbol, strike, expiration, opt_type = self._resolve_contract_fast(trade_obj, active_position, handler)
                    else:
                        active_position = None
                        symbol = trade_obj.get("ticker")
                        strike = trade_obj.get("strike")
                        expiration = trade_obj.get("expiration")
                        opt_type = trade_obj.get("type")
                    
                    # Update trade object
                    trade_obj.update({
                        'ticker': symbol, 'strike': strike, 
                        'expiration': expiration, 'type': opt_type
                    })

                    if not all([symbol, strike, expiration, opt_type]):
                        log_func(f"❌ Missing contract info: {trade_obj}", "ERROR")
                        continue

                    # === TRADE FIRST EXECUTION ===
                    if action == "buy":
                        success, result, trade_obj = self._execute_buy_trade_first(
                            trader, trade_obj, config, log_func
                        )
                    elif action in ("trim", "exit", "stop"):
                        success, result, trade_obj = self._execute_sell_trade_first(
                            trader, trade_obj, config, log_func, active_position, action
                        )
                    else:
                        continue
                    
                    trade_execution_time = time.time() - trade_start_time
                    self.execution_times.append(trade_execution_time)
                    
                    log_func(f"⚡ Trade executed in {trade_execution_time:.2f}s: {result}")
                    
                    # === ALERT LAST - FIRE AND FORGET ===
                    if success:
                        # All post-trade tasks run in background
                        asyncio.run_coroutine_threadsafe(
                            self._post_trade_tasks(
                                trade_obj, action, success, result, 
                                active_position, config, is_sim_mode, handler
                            ),
                            self.event_loop
                        )

                except Exception as trade_error:
                    log_func(f"❌ Trade execution failed: {trade_error}", "ERROR")
                    self.background_task_failures += 1

        except Exception as e:
            log_func(f"❌ Critical trade processing error: {e}", "ERROR")
        
        total_time = time.time() - execution_start
        log_func(f"🏁 Total processing time: {total_time:.2f}s")
    
    def _fast_position_lookup(self, trade_obj, handler):
        """ULTRA-FAST position lookup for trim/exit operations"""
        try:
            # Priority 1: Position manager (fastest)
            position = self.position_manager.find_position(trade_obj['channel_id'], trade_obj)
            if position:
                return position
            
            # Priority 2: Performance tracker by ticker (fast)
            ticker = trade_obj.get('ticker')
            if ticker:
                trade_id = self.performance_tracker.find_open_trade_by_ticker(ticker, handler.name)
                if trade_id:
                    return {'trade_id': trade_id}
            
            return {}
        except Exception as e:
            print(f"⚠️ Fast position lookup failed: {e}")
            return {}
    
    def _resolve_contract_fast(self, trade_obj, active_position, handler):
        """OPTIMIZED contract resolution for trim/exit"""
        try:
            # Get from trade_obj first (fastest)
            symbol = trade_obj.get("ticker") or (active_position.get("symbol") if active_position else None)
            strike = trade_obj.get("strike") or (active_position.get("strike") if active_position else None)
            expiration = trade_obj.get("expiration") or (active_position.get("expiration") if active_position else None)
            opt_type = trade_obj.get("type") or (active_position.get("type") if active_position else None)
            
            # FAST feedback lookup if missing data
            if symbol and (not strike or not expiration or not opt_type):
                recent_parse = self.feedback_logger.get_recent_parse_for_channel(handler.name, symbol)
                if recent_parse:
                    strike = strike or recent_parse.get('strike')
                    expiration = expiration or recent_parse.get('expiration') 
                    opt_type = opt_type or recent_parse.get('type')
            
            return symbol, strike, expiration, opt_type
        except Exception as e:
            print(f"⚠️ Fast contract resolution failed: {e}")
            return None, None, None, None
    
    def _execute_buy_trade_first(self, trader, trade_obj, config, log_func):
        """TRADE FIRST: Buy execution with minimal latency"""
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            price = float(trade_obj.get('price', 0))
            size = trade_obj.get('size', 'full')
            
            if price <= 0:
                return False, "Invalid price", trade_obj
            
            # === ULTRA-FAST POSITION SIZING ===
            portfolio_value = trader.get_portfolio_value()
            allocation = MAX_PCT_PORTFOLIO * POSITION_SIZE_MULTIPLIERS.get(size, 1.0) * config["multiplier"]
            max_amount = min(allocation * portfolio_value, MAX_DOLLAR_AMOUNT)
            
            # === OPTIMIZED TICK SIZE & PRICING ===
            tick_size = self._get_tick_size_fast(trader, symbol)
            buy_padding = config.get("buy_padding", DEFAULT_BUY_PRICE_PADDING)
            padded_price = self._round_to_tick_fast(price * (1 + buy_padding), tick_size, round_up=True)
            
            contracts = max(MIN_TRADE_QUANTITY, int(max_amount / (padded_price * 100)))
            
            # Update trade object
            trade_obj['quantity'] = contracts
            trade_obj['price'] = padded_price
            trade_obj['tick_size_used'] = tick_size
            
            # === TRADE FIRST - EXECUTE IMMEDIATELY ===
            log_func(f"🚀 PLACING BUY TRADE: {contracts}x {symbol} {strike}{opt_type} @ ${padded_price:.2f}")
            
            buy_response = trader.place_option_buy_order(symbol, strike, expiration, opt_type, contracts, padded_price)
            
            # Handle response
            if isinstance(trader, SimulatedTrader) or hasattr(trader, 'simulated_orders'):
                return True, f"Simulated buy: {contracts}x {symbol}", trade_obj
            
            order_id = buy_response.get('id')
            if order_id:
                trade_obj['order_id'] = order_id
                return True, f"Buy order placed: {contracts}x {symbol} @ ${padded_price:.2f}", trade_obj
            else:
                return False, f"Order failed: {buy_response.get('error', 'Unknown error')}", trade_obj
                
        except Exception as e:
            return False, str(e), trade_obj
    
    def _execute_sell_trade_first(self, trader, trade_obj, config, log_func, active_position, action):
        """TRADE FIRST: Optimized sell execution for trim/exit"""
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            
            # === ULTRA-FAST QUANTITY DETERMINATION ===
            if isinstance(trader, SimulatedTrader) or hasattr(trader, 'simulated_orders'):
                total_quantity = 10
            else:
                # Try to get from active position first
                if active_position and active_position.get('quantity'):
                    total_quantity = int(active_position['quantity'])
                else:
                    # Fast position lookup
                    all_positions = trader.get_open_option_positions()
                    position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
                    if not position:
                        return False, "No position found", trade_obj
                    total_quantity = int(float(position.get('quantity', 0)))
            
            # Determine sell quantity
            if action == "trim":
                sell_quantity = max(1, total_quantity // 2)
            else:
                sell_quantity = total_quantity
            
            trade_obj['quantity'] = sell_quantity
            
            # === OPTIMIZED MARKET PRICE DISCOVERY ===
            tick_size = self._get_tick_size_fast(trader, symbol)
            sell_padding = config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
            
            # Fast market price with fallback
            market_price = self._get_market_price_fast(trader, trade_obj, symbol, expiration, strike, opt_type, active_position)
            
            # Apply padding with minimum tick premium (same as buy logic)
            sell_price = market_price * (1 - sell_padding)
            final_price = self._round_to_tick_fast(sell_price, tick_size)
            
            # Ensure minimum tick premium cost
            min_premium = max(tick_size, 0.05)  # Same minimum as buy logic
            final_price = max(final_price, min_premium)
            
            trade_obj['price'] = final_price
            trade_obj['tick_size_used'] = tick_size
            trade_obj['market_price_source'] = getattr(self, '_last_price_source', 'unknown')
            
            # === TRADE FIRST - EXECUTE IMMEDIATELY ===
            log_func(f"🚀 PLACING {action.upper()} TRADE: {sell_quantity}x {symbol} @ ${final_price:.2f}")
            
            # Cancel existing orders quickly (non-blocking where possible)
            cancelled = trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
            if cancelled > 0:
                log_func(f"✅ Cancelled {cancelled} existing orders")
            
            sell_response = trader.place_option_sell_order(
                symbol, strike, expiration, opt_type, sell_quantity, 
                limit_price=final_price, sell_padding=sell_padding
            )
            
            # Handle response
            if isinstance(trader, SimulatedTrader) or hasattr(trader, 'simulated_orders'):
                return True, f"Simulated {action}: {sell_quantity}x {symbol}", trade_obj
            
            if sell_response and not sell_response.get('error'):
                order_id = sell_response.get('id')
                if order_id:
                    trade_obj['order_id'] = order_id
                return True, f"{action.title()}: {sell_quantity}x {symbol} @ ${final_price:.2f}", trade_obj
            else:
                return False, f"{action.title()} failed: {sell_response.get('error', 'Unknown error')}", trade_obj
                
        except Exception as e:
            return False, str(e), trade_obj
    
    def _get_tick_size_fast(self, trader, symbol):
        """OPTIMIZED tick size retrieval with aggressive caching"""
        try:
            # Check if we have cached tick size
            cache_key = f"tick_{symbol}"
            if hasattr(self, '_tick_cache') and cache_key in self._tick_cache:
                return self._tick_cache[cache_key]
            
            if not hasattr(self, '_tick_cache'):
                self._tick_cache = {}
            
            # Priority 1: Try Robinhood API (PREFERRED)
            try:
                instruments = trader.get_instruments_by_symbols(symbol) if hasattr(trader, 'get_instruments_by_symbols') else None
                if instruments and len(instruments) > 0 and instruments[0]:
                    if 'min_tick_size' in instruments[0]:
                        tick_size = float(instruments[0]['min_tick_size'])
                        self._tick_cache[cache_key] = tick_size
                        print(f"📏 RH API tick size for {symbol}: ${tick_size}")
                        return tick_size
            except Exception as e:
                print(f"⚠️ RH API tick size failed for {symbol}: {e}")
            
            # Priority 2: Enhanced price-based logic
            try:
                if hasattr(trader, 'get_quotes'):
                    quotes = trader.get_quotes(symbol)
                    if quotes and len(quotes) > 0 and quotes[0]:
                        price = float(quotes[0].get('last_trade_price', 1.0))
                        # Standard options tick size rules
                        if price < 3.00:
                            tick_size = 0.05
                        else:
                            tick_size = 0.10
                        
                        self._tick_cache[cache_key] = tick_size
                        print(f"📏 Price-based tick size for {symbol}: ${tick_size} (price: ${price})")
                        return tick_size
            except:
                pass
            
            # Priority 3: Smart default based on symbol type
            if symbol in ['SPX', 'SPY', 'QQQ', 'IWM']:  # Major indices
                tick_size = 0.05
            else:  # Individual stocks
                tick_size = 0.05  # Conservative default
            
            # Cache even the default
            self._tick_cache[cache_key] = tick_size
            print(f"📏 Default tick size for {symbol}: ${tick_size}")
            return tick_size
            
        except Exception as e:
            # Corrected exception handling
            print(f"❌ Tick size error for {symbol}: {e}")
            return 0.05  # Safe fallback
    
    def _round_to_tick_fast(self, price, tick_size, round_up=False):
        """ULTRA-FAST tick rounding"""
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
    
    def _get_market_price_fast(self, trader, trade_obj, symbol, expiration, strike, opt_type, active_position):
        """OPTIMIZED market price discovery for sells"""
        try:
            # Priority 1: Specified price in trade_obj
            specified_price = trade_obj.get('price')
            if specified_price == 'BE' and active_position:
                market_price = active_position.get('purchase_price', 0.50)
                self._last_price_source = 'breakeven'
                return market_price
            elif specified_price and isinstance(specified_price, (int, float)) and specified_price > 0:
                self._last_price_source = 'specified'
                return float(specified_price)
            
            # Priority 2: Live market data
            market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
            
            if market_data and len(market_data) > 0:
                data = market_data[0]
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                if isinstance(data, dict):
                    mark_price = data.get('mark_price')
                    if mark_price and float(mark_price) > 0:
                        self._last_price_source = 'mark'
                        return float(mark_price)
                    
                    bid = float(data.get('bid_price', 0) or 0)
                    ask = float(data.get('ask_price', 0) or 0)
                    if bid > 0 and ask > 0:
                        self._last_price_source = 'midpoint'
                        return (bid + ask) / 2
                    elif bid > 0:
                        self._last_price_source = 'bid'
                        return bid
            
            # Priority 3: Fallback pricing (This condition was slightly incorrect, should check if specified_price is a number)
            if specified_price and isinstance(specified_price, (int, float)) and specified_price > 0:
                self._last_price_source = 'discounted_specified'
                return float(specified_price) * 0.9
            
            # Priority 4: Emergency minimum
            self._last_price_source = 'emergency_minimum'
            return 0.50  # Reasonable minimum for options
            
        except Exception as e:
            print(f"⚠️ Fast market price failed: {e}")
            self._last_price_source = 'error_fallback'
            return 0.50

    async def _post_trade_tasks(self, trade_obj, action, success, result, active_position, config, is_sim_mode, handler):
        """ALERT LAST: All post-trade tasks run in background"""
        try:
            if not success:
                return
            
            # Create background tasks (fire and forget)
            background_tasks = []
            
            # Task 1: Performance tracking
            if action == "buy":
                background_tasks.append(
                    self._async_record_entry(trade_obj)
                )
                
                # Task 2: Position management
                background_tasks.append(
                    self._async_add_position(trade_obj)
                )
                
                # Task 3: Stop loss scheduling
                if trade_obj.get('price', 0) > 0:
                    background_tasks.append(
                        self._async_schedule_stop_loss(trade_obj, config)
                    )
                    
            elif action in ("trim", "exit", "stop"):
                # Task 1: Performance tracking
                background_tasks.append(
                    self._async_record_trim_exit(trade_obj, action, active_position)
                )
                
                # Task 2: Position management
                background_tasks.append(
                    self._async_update_position(trade_obj, action, active_position)
                )
                
                # Task 3: Trailing stop (for trims)
                if action == "trim":
                    background_tasks.append(
                        self._async_handle_trailing_stop(trade_obj, config, active_position, is_sim_mode)
                    )
            
            # Task 4: Trade alert (always)
            background_tasks.append(
                self._async_send_trade_alert(trade_obj, action, is_sim_mode)
            )
            
            # Task 5: Order monitoring (for live trades)
            if not is_sim_mode and trade_obj.get('order_id'):
                background_tasks.append(
                    self._async_monitor_order(trade_obj, handler)
                )
            
            # Execute all tasks concurrently (fire and forget)
            await asyncio.gather(*background_tasks, return_exceptions=True)
            
        except Exception as e:
            self.background_task_failures += 1
            print(f"❌ Post-trade tasks failed: {e}")

    async def _async_record_entry(self, trade_obj):
        """Background: Record trade entry"""
        try:
            trade_id = f"trade_{int(datetime.now().timestamp() * 1000)}"
            trade_obj['trade_id'] = trade_id
            await asyncio.get_event_loop().run_in_executor(
                None, self.performance_tracker.record_entry, trade_obj
            )
        except Exception as e:
            print(f"❌ Background entry recording failed: {e}")
    
    async def _async_add_position(self, trade_obj):
        """Background: Add to position manager"""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, 
                self.position_manager.add_position, 
                trade_obj['channel_id'], 
                trade_obj
            )
        except Exception as e:
            print(f"❌ Background position add failed: {e}")
    
    async def _async_schedule_stop_loss(self, trade_obj, config):
        """Background: Schedule stop loss"""
        try:
            price = trade_obj.get('price', 0)
            symbol = trade_obj['ticker']
            
            # Calculate stop loss price with same tick logic
            tick_size = trade_obj.get('tick_size_used', 0.05)
            stop_price_raw = price * (1 - config.get("initial_stop_loss", 0.50))
            stop_price = self._round_to_tick_fast(stop_price_raw, tick_size)
            
            trade_id = trade_obj.get('trade_id')
            if trade_id:
                stop_data = {
                    'trader': self.live_trader if not hasattr(trade_obj, 'simulated') else self.sim_trader,
                    'symbol': symbol,
                    'strike': trade_obj['strike'],
                    'expiration': trade_obj['expiration'],
                    'opt_type': trade_obj['type'],
                    'quantity': trade_obj.get('quantity', 1),
                    'stop_price': stop_price
                }
                
                await asyncio.get_event_loop().run_in_executor(
                    None, 
                    self.stop_loss_manager.schedule_stop_loss, 
                    trade_id, stop_data, STOP_LOSS_DELAY_SECONDS
                )
                
                print(f"⏱️ Stop loss scheduled: ${stop_price:.2f} in {STOP_LOSS_DELAY_SECONDS/60:.0f}min")
        except Exception as e:
            print(f"❌ Background stop loss scheduling failed: {e}")
    
    async def _async_record_trim_exit(self, trade_obj, action, active_position):
        """Background: Record trim/exit"""
        try:
            trade_id = active_position.get('trade_id') if active_position else None
            if not trade_id and trade_obj.get('ticker'):
                trade_id = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.performance_tracker.find_open_trade_by_ticker,
                    trade_obj['ticker'],
                    trade_obj['channel']
                )
            
            if trade_id:
                if action == "trim":
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.performance_tracker.record_trim,
                        trade_id,
                        {
                            'quantity': trade_obj.get('quantity', 1),
                            'price': trade_obj.get('price', 0),
                            'ticker': trade_obj.get('ticker'),
                            'channel': trade_obj['channel']
                        }
                    )
                else:  # exit or stop
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        self.performance_tracker.record_exit,
                        trade_id,
                        {
                            'price': trade_obj.get('price', 0),
                            'action': action,
                            'is_stop_loss': action == 'stop',
                            'ticker': trade_obj.get('ticker'),
                            'channel': trade_obj['channel']
                        }
                    )
        except Exception as e:
            print(f"❌ Background trim/exit recording failed: {e}")
    
    async def _async_update_position(self, trade_obj, action, active_position):
        """Background: Update position manager"""
        try:
            trade_id = active_position.get('trade_id') if active_position else None
            if trade_id and action in ("exit", "stop"):
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.position_manager.clear_position,
                    trade_obj['channel_id'],
                    trade_id
                )
        except Exception as e:
            print(f"❌ Background position update failed: {e}")
    
    async def _async_handle_trailing_stop(self, trade_obj, config, active_position, is_sim_mode):
        """Background: Handle trailing stops for trims"""
        try:
            if is_sim_mode or not active_position:
                return
                
            # This would implement trailing stop logic
            # (Implementation similar to existing but runs in background)
            print(f"📊 Processing trailing stop for {trade_obj['ticker']} (background)")
        except Exception as e:
            print(f"❌ Background trailing stop failed: {e}")
    
    async def _async_send_trade_alert(self, trade_obj, action, is_sim_mode):
        """Background: Send trade alert"""
        try:
            alert_embed = self._create_trade_alert_embed(trade_obj, action, is_sim_mode)
            await self.alert_manager.add_alert(
                PLAYS_WEBHOOK, 
                {"embeds": [alert_embed]}, 
                "trade_alert", 
                priority=1
            )
        except Exception as e:
            print(f"❌ Background alert failed: {e}")
    
    async def _async_monitor_order(self, trade_obj, handler):
        """Background: Monitor order fill (non-blocking)"""
        try:
            order_id = trade_obj.get('order_id')
            if not order_id:
                return
                
            # Run order monitoring in background without blocking
            await asyncio.get_event_loop().run_in_executor(
                None,
                self._monitor_order_fill_background,
                order_id,
                trade_obj,
                handler
            )
        except Exception as e:
            print(f"❌ Background order monitoring failed: {e}")
    
    def _monitor_order_fill_background(self, order_id, trade_obj, handler):
        """Background order monitoring (runs in thread pool)"""
        try:
            # Simplified monitoring - just check if filled after reasonable time
            time.sleep(30)  # Wait 30 seconds
            
            trader = self.live_trader
            order_info = trader.get_option_order_info(order_id)
            
            if order_info and order_info.get('state') == 'filled':
                print(f"✅ Background: Order {order_id} filled")
            elif order_info and order_info.get('state') in ['queued', 'unconfirmed', 'confirmed']:
                print(f"⏳ Background: Order {order_id} still pending")
            else:
                print(f"⚠️ Background: Order {order_id} status unknown: {order_info}")
                
        except Exception as e:
            # Corrected exception handling
            print(f"❌ Background order monitoring exception: {e}")
            
    async def _async_log(self, msg, level="INFO"):
        """Background logging"""
        try:
            if level == "ERROR":
                await self.alert_manager.send_error_alert(msg)
            else:
                await self.alert_manager.add_alert(
                    ALL_NOTIFICATION_WEBHOOK, 
                    {"content": msg}, 
                    f"{level.lower()}_notification"
                )
        except:
            pass  # Don't let logging failures block anything
    
    async def _async_log_feedback(self, channel_name, raw_msg, parsed_results, latency_ms):
        """Background feedback logging"""
        try:
            for parsed_obj in parsed_results:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.feedback_logger.log,
                    channel_name, raw_msg, parsed_obj, latency_ms
                )
        except:
            pass  # Don't let feedback logging block anything
    
    def _create_trade_alert_embed(self, trade_obj, action, is_simulation):
        """Create optimized trade alert embed"""
        
        colors = {
            'buy': 0x00C851,
            'sell': 0xFF4444,
            'trim': 0xFF8800,
            'exit': 0xFF4444,
            'stop': 0xFF0000
        }
        
        emojis = {
            'buy': '🟢',
            'sell': '🔴', 
            'trim': '🟡',
            'exit': '🔴',
            'stop': '🛑'
        }
        
        embed = {
            "title": f"{emojis.get(action, '')} {'[SIM]' if is_simulation else '[LIVE]'} {trade_obj.get('channel', 'Unknown')} • {action.upper()} • {trade_obj.get('ticker', 'Unknown')}",
            "color": colors.get(action, 0x888888),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [],
            "footer": {"text": "RHTB v4 - Trade First, Alert Last"}
        }
        
        # Contract details
        ticker = trade_obj.get('ticker', 'N/A')
        strike = trade_obj.get('strike', 0)
        opt_type = trade_obj.get('type', 'N/A')
        expiration = trade_obj.get('expiration', 'N/A')
        
        try:
            exp_date = datetime.fromisoformat(expiration).strftime('%m/%d/%y')
        except:
            exp_date = expiration
        
        type_symbol = opt_type[0].upper() if opt_type else 'N/A'
        contract_info = f"**{ticker}** ${strike}{type_symbol} {exp_date}"
        
        embed["fields"].append({
            "name": "📈 Contract Details",
            "value": contract_info,
            "inline": True
        })
        
        # Execution details with enhanced info
        quantity = trade_obj.get('quantity', 0)
        price = trade_obj.get('price', 0)
        tick_size = trade_obj.get('tick_size_used', 0.05)
        price_source = trade_obj.get('market_price_source', 'unknown')
        
        position_value = price * quantity * 100 if isinstance(price, (int, float)) else 0
        
        execution_info = f"""
**Quantity:** {quantity} contracts
**Price:** ${price if isinstance(price, str) else f'{price:.2f}'}
**Total Value:** ${position_value:,.2f}
**Tick Size:** ${tick_size}
        """.strip()
        
        if action in ("trim", "exit", "stop") and price_source != 'unknown':
            execution_info += f"\n**Price Source:** {price_source}"
        
        embed["fields"].append({
            "name": "💰 Execution Details", 
            "value": execution_info,
            "inline": True
        })
        
        # Performance metrics if available
        order_id = trade_obj.get('order_id')
        if order_id:
            embed["fields"].append({
                "name": "🔍 Order Info",
                "value": f"**Order ID:** {order_id[:8]}...\n**Status:** Submitted",
                "inline": True
            })
        
        if is_simulation:
            embed["author"] = {"name": "🧪 SIMULATION MODE"}
        
        return embed
    
    def _normalize_keys(self, data: dict) -> dict:
        """Normalize dictionary keys (optimized)"""
        if not isinstance(data, dict): 
            return data
        
        cleaned_data = {k.lower().replace(' ', '_'): v for k, v in data.items()}
        
        # Fast key mapping
        key_map = {
            'option_type': 'type',
            'entry_price': 'price'
        }
        
        for old_key, new_key in key_map.items():
            if old_key in cleaned_data:
                cleaned_data[new_key] = cleaned_data.pop(old_key)
        
        # Clean ticker symbol (FIXED)
        if 'ticker' in cleaned_data and isinstance(cleaned_data['ticker'], str):
            cleaned_data['ticker'] = cleaned_data['ticker'].replace('$', '').upper()
        
        return cleaned_data
    
    def get_performance_metrics(self):
        """Get executor performance metrics"""
        if not self.execution_times:
            return {
                'avg_execution_time': 0,
                'min_execution_time': 0,
                'max_execution_time': 0,
                'total_trades': 0,
                'background_failures': self.background_task_failures
            }
        
        return {
            'avg_execution_time': sum(self.execution_times) / len(self.execution_times),
            'min_execution_time': min(self.execution_times),
            'max_execution_time': max(self.execution_times),
            'total_trades': len(self.execution_times),
            'background_failures': self.background_task_failures,
            'last_10_avg': sum(self.execution_times[-10:]) / min(10, len(self.execution_times))
        }


class ChannelAwareFeedbackLogger:
    """Enhanced feedback logger with strict channel isolation (optimized)"""
    
    def __init__(self, filename="parsing_feedback.csv"):
        self.filename = filename
        self.lock = threading.Lock()
        self._cache = {}  # Simple cache for recent lookups
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
                            "Timestamp"
                        ])

    def log(self, channel_name, original_message, parsed_message_json, latency=0):
        """Log parse result with channel isolation (optimized for background)"""
        with self.lock:
            try:
                with open(self.filename, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        channel_name,
                        original_message[:500],  # Limit message length
                        str(parsed_message_json)[:1000],  # Limit JSON length
                        f"{latency:.2f}",
                        datetime.now(timezone.utc).isoformat()
                    ])
                
                # Update cache for fast lookups
                cache_key = f"{channel_name}_{parsed_message_json.get('ticker', 'unknown')}"
                self._cache[cache_key] = parsed_message_json
                
                # Limit cache size
                if len(self._cache) > 100:
                    # Remove oldest 20 entries
                    keys_to_remove = list(self._cache.keys())[:20]
                    for key in keys_to_remove:
                        del self._cache[key]
                        
            except Exception as e:
                print(f"❌ Failed to write to feedback log: {e}")
    
    def get_recent_parse_for_channel(self, channel_name: str, ticker: str):
        """Get most recent successful parse for ticker within specific channel (ULTRA-FAST)"""
        
        # Priority 1: Check cache first (fastest)
        cache_key = f"{channel_name}_{ticker}"
        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if (cached_data.get('ticker') == ticker and 
                cached_data.get('strike') and 
                cached_data.get('expiration') and 
                cached_data.get('type')):
                return cached_data
        
        # Priority 2: File lookup (slower, but still fast)
        try:
            with self.lock:
                if not os.path.exists(self.filename):
                    return None
                    
                # Read only the last N lines for speed
                with open(self.filename, 'r', newline='', encoding='utf-8') as f:
                    lines = f.readlines()
                
                # Process in reverse order (most recent first)
                for line in reversed(lines[-50:]):  # Only check last 50 entries
                    try:
                        parts = line.strip().split(',', 4)  # Split into max 5 parts
                        if len(parts) >= 3:
                            row_channel = parts[0].strip('"')
                            parsed_json_str = parts[2].strip('"')
                            
                            if row_channel == channel_name:
                                try:
                                    # Handle escaped JSON
                                    if parsed_json_str.startswith('{'):
                                        # Use eval as a fallback for dict-like strings, but json.loads is safer
                                        try:
                                            parsed_data = json.loads(parsed_json_str.replace("'", '"'))
                                        except json.JSONDecodeError:
                                            parsed_data = eval(parsed_json_str)
                                    else:
                                        parsed_data = eval(parsed_json_str)
                                        
                                    if (isinstance(parsed_data, dict) and 
                                        parsed_data.get('ticker') == ticker and
                                        parsed_data.get('strike') and 
                                        parsed_data.get('expiration') and 
                                        parsed_data.get('type')):
                                        
                                        # Update cache
                                        self._cache[cache_key] = parsed_data
                                        return parsed_data
                                except:
                                    continue
                    except:
                        continue
                        
        except Exception as e:
            print(f"❌ Error reading feedback log: {e}")
        
        return None


class DelayedStopLossManager:
    """Manages delayed stop loss orders (optimized)"""
    
    def __init__(self):
        self.pending_stops = {}
        self.completed_stops = set()
        
    def schedule_stop_loss(self, trade_id: str, stop_data: dict, delay_seconds: int = 900):
        """Schedule a stop loss to be placed after delay (optimized)"""
        def place_stop_after_delay():
            try:
                time.sleep(delay_seconds)
                
                if trade_id in self.completed_stops:
                    print(f"⚠️ Stop loss for {trade_id} already completed, skipping")
                    return
                
                print(f"⏰ Placing delayed stop loss for trade {trade_id}")
                
                trader = stop_data['trader']
                response = trader.place_option_stop_loss_order(
                    stop_data['symbol'],
                    stop_data['strike'],
                    stop_data['expiration'],
                    stop_data['opt_type'],
                    stop_data['quantity'],
                    stop_data['stop_price']
                )
                
                if response and not response.get('error'):
                    print(f"✅ Delayed stop loss placed for {stop_data['symbol']}: ${stop_data['stop_price']:.2f}")
                else:
                    print(f"❌ Failed to place delayed stop loss: {response}")
                    
            except Exception as e:
                print(f"❌ Failed to place delayed stop loss: {e}")
            finally:
                # Clean up
                if trade_id in self.pending_stops:
                    del self.pending_stops[trade_id]
                self.completed_stops.add(trade_id)
                
                # Limit completed_stops size
                if len(self.completed_stops) > 1000:
                    # Remove oldest 100
                    oldest_stops = list(self.completed_stops)[:100]
                    for stop_id in oldest_stops:
                        self.completed_stops.remove(stop_id)
        
        # Store pending stop
        self.pending_stops[trade_id] = stop_data
        
        # Start thread for delayed placement
        thread = threading.Thread(target=place_stop_after_delay, daemon=True)
        thread.start()
        print(f"⏱️ Stop loss scheduled for {delay_seconds/60:.1f} minutes @ ${stop_data['stop_price']:.2f}")
    
    def cancel_pending_stop(self, trade_id: str):
        """Cancel a pending stop loss"""
        if trade_id in self.pending_stops:
            del self.pending_stops[trade_id]
            self.completed_stops.add(trade_id)
            print(f"🚫 Cancelled pending stop loss for {trade_id}")
            return True
        return False
    
    def get_pending_stops(self):
        """Get list of pending stop losses"""
        return list(self.pending_stops.keys())


# Backwards compatibility
TradeExecutor = OptimizedTradeExecutor

# Export classes
__all__ = ['OptimizedTradeExecutor', 'TradeExecutor', 'ChannelAwareFeedbackLogger', 'DelayedStopLossManager']