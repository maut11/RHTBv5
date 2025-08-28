# trade_executor.py - Complete OPTIMIZED Trade Execution with Trade-First, Alert-Last
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
                trader_symbol = parsed_message_json.get('ticker', '') if isinstance(parsed_message_json, dict) else ''
                broker_symbol = get_broker_symbol(trader_symbol) if trader_symbol else ''

                with open(self.filename, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        channel_name,
                        original_message,
                        json.dumps(parsed_message_json) if isinstance(parsed_message_json, dict) else str(
                            parsed_message_json),
                        f"{latency:.2f}",
                        datetime.now(timezone.utc).isoformat(),
                        trader_symbol,
                        broker_symbol
                    ])
            except Exception as e:
                print(f"Failed to write to feedback log: {e}")

    def get_recent_parse_for_channel(self, channel_name: str, ticker: str):
        """Get most recent successful parse for ticker within specific channel"""
        try:
            with self.lock:
                if not os.path.exists(self.filename):
                    return None

                symbol_variants = get_all_symbol_variants(ticker)

                with open(self.filename, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader)  # Skip header

                    recent_parses = []
                    for row in reader:
                        if len(row) >= 5:
                            row_channel, message, parsed_json = row[0], row[1], row[2]

                            if row_channel == channel_name:
                                try:
                                    parsed_data = json.loads(parsed_json)
                                    if isinstance(parsed_data, dict):
                                        parsed_ticker = parsed_data.get('ticker', '').upper()

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
                            print(f"Symbol variant match in feedback: {ticker} → {most_recent.get('ticker')}")
                        return most_recent

                    return None

        except Exception as e:
            print(f"Error reading feedback log: {e}")
            return None


class DelayedStopLossManager:
    """Manages delayed stop loss orders with symbol mapping"""

    def __init__(self):
        self.pending_stops = {}

    def schedule_stop_loss(self, trade_id: str, stop_data: dict, delay_seconds: int = 900):
        """Schedule a stop loss to be placed after delay"""

        def place_stop_after_delay():
            time.sleep(delay_seconds)
            print(f"Placing delayed stop loss for trade {trade_id}")

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
                print(f"Delayed stop loss placed for {stop_data['symbol']}: {response}")
            except Exception as e:
                print(f"Failed to place delayed stop loss: {e}")
            finally:
                if trade_id in self.pending_stops:
                    del self.pending_stops[trade_id]

        self.pending_stops[trade_id] = stop_data
        thread = threading.Thread(target=place_stop_after_delay, daemon=True)
        thread.start()
        print(f"Stop loss scheduled for {delay_seconds / 60:.1f} minutes from now")


class FastTradeExecutor:
    """Optimized trade executor implementing TRADE FIRST, ALERT LAST approach"""

    def __init__(self, live_trader, sim_trader, performance_tracker, position_manager, alert_manager):
        self.live_trader = live_trader
        self.sim_trader = sim_trader
        self.performance_tracker = performance_tracker
        self.position_manager = position_manager
        self.alert_manager = alert_manager

        # Enhanced feedback logger with symbol mapping
        self.feedback_logger = ChannelAwareFeedbackLogger()
        self.stop_loss_manager = DelayedStopLossManager()

        print("Fast Trade Executor initialized - TRADE FIRST, ALERT LAST approach")

    async def process_trade_fast(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id=None,
                                 is_edit=False, event_loop=None):
        """
        FAST TRADE EXECUTION - Trade First, Everything Else Last
        This method prioritizes trade execution speed above all else.
        """
        start_time = time.time()

        # Store the event loop reference
        if event_loop:
            self.event_loop = event_loop
        else:
            self.event_loop = asyncio.get_running_loop()

        # Use thread pool for non-blocking execution
        await self.event_loop.run_in_executor(
            None,
            self._execute_trade_fast_blocking,
            handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, start_time
        )

    def _execute_trade_fast_blocking(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id,
                                     is_edit, start_time):
        """
        CRITICAL PATH: This method executes in a thread pool for maximum speed
        Everything here should prioritize trade execution latency
        """

        def fast_log(msg, level="INFO"):
            """Ultra-fast logging - no async operations here"""
            print(f"{msg}")

        try:
            # STEP 1: PARSE MESSAGE (Essential for trade)
            parsed_results, latency_ms = handler.parse_message(message_meta, received_ts, fast_log)

            if not parsed_results:
                fast_log(f"No parsed results from {handler.name}")
                return

            for raw_trade_obj in parsed_results:
                trade_obj = self._normalize_keys(raw_trade_obj)
                action = trade_obj.get("action", "").lower()

                if not action or action == "null":
                    continue

                # STEP 2: GET ESSENTIAL TRADE DATA
                config = CHANNELS_CONFIG.get(handler.name)
                if not config:
                    continue

                trader = self.live_trader if not is_sim_mode else self.sim_trader

                # Get symbol and contract details FAST
                trade_obj['channel'] = handler.name
                trade_obj['channel_id'] = handler.channel_id

                # Quick symbol normalization
                if trade_obj.get('ticker'):
                    original_symbol = trade_obj['ticker']
                    broker_symbol = get_broker_symbol(original_symbol)
                    trade_obj['trader_symbol'] = original_symbol
                    trade_obj['broker_symbol'] = broker_symbol

                # STEP 3: EXECUTE TRADE IMMEDIATELY (CRITICAL PATH)
                if action == "buy":
                    execution_success, result_summary, trade_obj = self._execute_buy_order_fast(
                        trader, trade_obj, config, fast_log
                    )

                    if execution_success:
                        trade_execution_time = time.time() - start_time
                        fast_log(f"Trade executed in {trade_execution_time:.2f}s: {result_summary}")

                        # FIRE AND FORGET: All non-critical tasks run AFTER trade execution
                        self._schedule_post_trade_tasks_async(
                            trade_obj, action, execution_success, result_summary, is_sim_mode
                        )

                elif action in ("trim", "exit", "stop"):
                    # Get active position quickly
                    active_position = self._find_position_fast(trade_obj, handler.name)

                    # Fill missing details from feedback FAST
                    trade_obj = self._fill_missing_details_fast(trade_obj, handler.name, active_position)

                    if self._validate_contract_details(trade_obj):
                        execution_success, result_summary, trade_obj = self._execute_sell_order_fast(
                            trader, trade_obj, config, fast_log, active_position
                        )

                        if execution_success:
                            trade_execution_time = time.time() - start_time
                            fast_log(f"Trade executed in {trade_execution_time:.2f}s: {result_summary}")

                            # FIRE AND FORGET: Post-trade tasks
                            self._schedule_post_trade_tasks_async(
                                trade_obj, action, execution_success, result_summary, is_sim_mode, active_position
                            )

        except Exception as e:
            fast_log(f"CRITICAL TRADE ERROR: {e}")

    def _execute_buy_order_fast(self, trader, trade_obj, config, log_func):
        """
        ULTRA-FAST BUY EXECUTION
        This method does ONLY what's needed to place the order
        """
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            price = float(trade_obj.get('price', 0))
            size = trade_obj.get('size', 'full')

            if price <= 0:
                return False, "Invalid price", trade_obj

            # FAST POSITION SIZING
            portfolio_value = trader.get_portfolio_value()
            allocation = MAX_PCT_PORTFOLIO * POSITION_SIZE_MULTIPLIERS.get(size, 1.0) * config["multiplier"]
            max_amount = min(allocation * portfolio_value, MAX_DOLLAR_AMOUNT)

            # ENHANCED TICK SIZE - Get from Robinhood API FIRST
            tick_size = self._get_tick_size_fast(trader, symbol)
            buy_padding = config.get("buy_padding", DEFAULT_BUY_PRICE_PADDING)
            padded_price = self._round_to_tick(price * (1 + buy_padding), tick_size, round_up=True)

            contracts = max(MIN_TRADE_QUANTITY, int(max_amount / (padded_price * 100)))

            # Store quantities
            trade_obj['quantity'] = contracts
            trade_obj['price'] = padded_price
            trade_obj['tick_size_used'] = tick_size

            log_func(f"FAST BUY: {contracts}x {symbol} {strike}{opt_type} @ ${padded_price:.2f} (tick: ${tick_size})")

            # PLACE ORDER IMMEDIATELY - This is the CRITICAL PATH
            buy_response = trader.place_option_buy_order(symbol, strike, expiration, opt_type, contracts,
                                                         padded_price)

            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                return True, f"Simulated buy: {contracts}x {symbol}", trade_obj

            order_id = buy_response.get('id')
            if order_id:
                trade_obj['order_id'] = order_id
                return True, f"Buy order placed: {contracts}x {symbol} @ ${padded_price:.2f}", trade_obj
            else:
                return False, f"Order failed: {buy_response.get('error', 'Unknown error')}", trade_obj

        except Exception as e:
            return False, str(e), trade_obj

    def _execute_sell_order_fast(self, trader, trade_obj, config, log_func, active_position):
        """
        ULTRA-FAST SELL EXECUTION with minimum tick premium enforcement
        """
        try:
            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']
            action = trade_obj.get('action', 'exit')

            # Get position quantity FAST
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                total_quantity = 10
            else:
                all_positions = trader.get_open_option_positions()
                position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
                if not position:
                    return False, "No position found", trade_obj
                total_quantity = int(float(position.get('quantity', 0)))

            # Determine quantity to sell
            if action == "trim":
                sell_quantity = max(1, total_quantity // 2)
            else:
                sell_quantity = total_quantity

            trade_obj['quantity'] = sell_quantity

            # ENHANCED TICK SIZE with minimum premium enforcement
            tick_size = self._get_tick_size_fast(trader, symbol)

            # Cancel existing orders FAST (fire and forget)
            try:
                trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
            except:
                pass  # Don't let cancellation failures block the trade

            # Get market price and apply minimum tick premium
            sell_price = self._get_optimized_sell_price(
                trader, symbol, strike, expiration, opt_type,
                config, trade_obj, tick_size, active_position
            )

            trade_obj['price'] = sell_price
            trade_obj['tick_size_used'] = tick_size

            log_func(f"FAST {action.upper()}: {sell_quantity}x {symbol} @ ${sell_price:.2f} (tick: ${tick_size})")

            # PLACE SELL ORDER IMMEDIATELY
            sell_response = trader.place_option_sell_order(
                symbol, strike, expiration, opt_type, sell_quantity,
                limit_price=sell_price, sell_padding=config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
            )

            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                return True, f"Simulated {action}: {sell_quantity}x {symbol}", trade_obj

            if sell_response and not sell_response.get('error'):
                trade_obj['order_id'] = sell_response.get('id')
                return True, f"{action.title()}: {sell_quantity}x {symbol} @ ${sell_price:.2f}", trade_obj
            else:
                return False, f"{action.title()} failed: {sell_response.get('error', 'Unknown error')}", trade_obj

        except Exception as e:
            return False, str(e), trade_obj

    def _get_tick_size_fast(self, trader, symbol):
        """
        PRIORITIZED TICK SIZE DETECTION
        1. Try Robinhood API first (most accurate)
        2. Fallback to price-based logic
        3. Default to 0.05
        """
        try:
            # PRIORITY 1: Get from Robinhood API
            broker_symbol = get_broker_symbol(symbol)
            tick_size = trader.get_instrument_tick_size(broker_symbol)

            if tick_size and tick_size > 0:
                print(f"Robinhood tick size for {symbol}/{broker_symbol}: ${tick_size}")
                return tick_size

        except Exception as e:
            print(f"Could not get Robinhood tick size for {symbol}: {e}")

        # FALLBACK: Price-based logic
        try:
            # Access robin_stocks directly if available
            if hasattr(trader, 'r'):
                quotes = trader.r.get_quotes(get_broker_symbol(symbol))
                if quotes and len(quotes) > 0:
                    price = float(quotes[0].get('last_trade_price', 1.0))
                    if price < 3.00:
                        return 0.05
                    else:
                        return 0.10
        except:
            pass

        # ULTIMATE FALLBACK
        print(f"Using default tick size for {symbol}: $0.05")
        return 0.05

    def _get_optimized_sell_price(self, trader, symbol, strike, expiration, opt_type, config, trade_obj, tick_size,
                                  active_position):
        """
        OPTIMIZED SELL PRICING with minimum tick premium enforcement
        Ensures sell orders have same minimum tick premium as buy orders
        """
        try:
            # Check if this is a BE (breakeven) exit
            if trade_obj.get('is_breakeven') or str(trade_obj.get('price', '')).upper() == 'BE':
                entry_price = active_position.get('entry_price') or active_position.get(
                    'purchase_price') if active_position else None
                if entry_price:
                    return float(entry_price)

            # Get market data FAST
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
                    else:
                        bid = float(data.get('bid_price', 0) or 0)
                        ask = float(data.get('ask_price', 0) or 0)
                        if bid > 0 and ask > 0:
                            market_price = (bid + ask) / 2
                        elif bid > 0:
                            market_price = bid

            # Fallback pricing
            if not market_price or market_price <= 0:
                specified_price = trade_obj.get('price', 0)
                if specified_price and specified_price > 0 and not isinstance(specified_price, str):
                    market_price = float(specified_price) * 0.9
                else:
                    # Emergency fallback
                    if active_position:
                        entry_price = active_position.get('entry_price') or active_position.get('purchase_price')
                        if entry_price:
                            market_price = float(entry_price) * 0.5
                        else:
                            market_price = tick_size * 2  # Minimum 2 ticks
                    else:
                        market_price = tick_size * 2

            # Apply sell padding
            sell_padding = config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
            sell_price = market_price * (1 - sell_padding)

            # ENFORCE MINIMUM TICK PREMIUM (same as buy logic)
            min_premium = tick_size * 2  # Minimum 2 ticks premium
            sell_price = max(sell_price, min_premium)

            # Round to proper tick size
            return self._round_to_tick(sell_price, tick_size)

        except Exception as e:
            print(f"Error getting sell price: {e}")
            # Emergency minimum
            return tick_size * 2

    def _schedule_post_trade_tasks_async(self, trade_obj, action, execution_success, result_summary, is_sim_mode,
                                         active_position=None):
        """
        FIRE AND FORGET: All non-critical tasks scheduled AFTER trade execution
        This ensures trade execution latency is minimized
        """
        try:
            # Schedule all background tasks without blocking
            if action == "buy" and execution_success:
                # Generate trade ID for tracking
                trade_id = f"trade_{int(datetime.now().timestamp() * 1000)}"
                trade_obj['trade_id'] = trade_id

                # Schedule async tasks
                asyncio.run_coroutine_threadsafe(
                    self._handle_buy_post_tasks(trade_obj, is_sim_mode),
                    self.event_loop
                )

            elif action in ("trim", "exit", "stop") and execution_success:
                asyncio.run_coroutine_threadsafe(
                    self._handle_sell_post_tasks(trade_obj, action, is_sim_mode, active_position),
                    self.event_loop
                )

        except Exception as e:
            print(f"Error scheduling post-trade tasks: {e}")

    async def _handle_buy_post_tasks(self, trade_obj, is_sim_mode):
        """Handle all buy post-trade tasks asynchronously"""
        try:
            tasks = []

            # Task 1: Send trade alert
            tasks.append(self._send_trade_alert(
                trade_obj, 'buy', trade_obj.get('quantity', 1),
                trade_obj.get('price', 0), is_sim_mode
            ))

            # Task 2: Record in performance tracker (background)
            tasks.append(self._record_performance_entry(trade_obj))

            # Task 3: Add to position manager (background)
            tasks.append(self._add_position(trade_obj))

            # Task 4: Schedule stop loss (background)
            tasks.append(self._schedule_stop_loss(trade_obj))

            # Task 5: Log to feedback (background)
            tasks.append(self._log_feedback(trade_obj))

            # Execute all tasks concurrently without blocking
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            print(f"Error in buy post-tasks: {e}")

    async def _handle_sell_post_tasks(self, trade_obj, action, is_sim_mode, active_position):
        """Handle all sell post-trade tasks asynchronously"""
        try:
            tasks = []

            # Task 1: Send trade alert
            tasks.append(self._send_trade_alert(
                trade_obj, action, trade_obj.get('quantity', 1),
                trade_obj.get('price', 0), is_sim_mode
            ))

            # Task 2: Update performance tracker
            tasks.append(self._update_performance_tracking(trade_obj, action, active_position))

            # Task 3: Update position manager
            tasks.append(self._update_position_manager(trade_obj, action, active_position))

            # Task 4: Handle trailing stops (for trims)
            if action == "trim":
                tasks.append(self._handle_trailing_stop_async(trade_obj, active_position))

            # Execute all tasks concurrently
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            print(f"Error in sell post-tasks: {e}")

    # Async wrapper methods for background tasks
    async def _send_trade_alert(self, trade_data, action, quantity, price, is_simulation, trade_record=None):
        """Send enhanced trade alert"""
        try:
            alert_embed = self._create_trade_alert_embed(trade_data, action, quantity, price, is_simulation,
                                                         trade_record)
            await self.alert_manager.add_alert(PLAYS_WEBHOOK, {"embeds": [alert_embed]}, "trade_alert", priority=1)
            print(f"Trade alert sent: {action} {trade_data.get('ticker', 'Unknown')}")
        except Exception as e:
            print(f"Error sending trade alert: {e}")

    async def _record_performance_entry(self, trade_obj):
        """Record trade entry in performance tracker"""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self.performance_tracker.record_entry, trade_obj
            )
        except Exception as e:
            print(f"Error recording performance entry: {e}")

    async def _add_position(self, trade_obj):
        """Add position to position manager"""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self.position_manager.add_position, trade_obj['channel_id'], trade_obj
            )
        except Exception as e:
            print(f"Error adding position: {e}")

    async def _schedule_stop_loss(self, trade_obj):
        """Schedule delayed stop loss"""
        try:
            price = trade_obj.get('price', 0)
            if price > 0 and not trade_obj.get('is_breakeven'):
                config = CHANNELS_CONFIG.get(trade_obj.get('channel'))
                if config:
                    tick_size = trade_obj.get('tick_size_used', 0.05)
                    stop_price = self._round_to_tick(
                        price * (1 - config.get("initial_stop_loss", 0.50)), tick_size
                    )

                    stop_data = {
                        'trader': self.live_trader,
                        'symbol': trade_obj['ticker'],
                        'strike': trade_obj['strike'],
                        'expiration': trade_obj['expiration'],
                        'opt_type': trade_obj['type'],
                        'quantity': trade_obj.get('quantity', 1),
                        'stop_price': stop_price
                    }

                    await asyncio.get_event_loop().run_in_executor(
                        None, self.stop_loss_manager.schedule_stop_loss,
                        trade_obj['trade_id'], stop_data, STOP_LOSS_DELAY_SECONDS
                    )
        except Exception as e:
            print(f"Error scheduling stop loss: {e}")

    async def _log_feedback(self, trade_obj):
        """Log to feedback system"""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self.feedback_logger.log,
                trade_obj.get('channel'), str(trade_obj), trade_obj, 0
            )
        except Exception as e:
            print(f"Error logging feedback: {e}")

    async def _update_performance_tracking(self, trade_obj, action, active_position):
        """Update performance tracking for sell orders"""
        try:
            trade_id = active_position.get('trade_id') if active_position else None
            if not trade_id and trade_obj.get('ticker'):
                trade_id = await asyncio.get_event_loop().run_in_executor(
                    None, self.performance_tracker.find_open_trade_by_ticker,
                    trade_obj['ticker'], trade_obj.get('channel')
                )

            if trade_id:
                if action == "trim":
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.performance_tracker.record_trim, trade_id, {
                            'quantity': trade_obj.get('quantity', 1),
                            'price': trade_obj.get('price', 0),
                            'ticker': trade_obj.get('ticker'),
                            'channel': trade_obj.get('channel')
                        }
                    )
                else:  # exit or stop
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.performance_tracker.record_exit, trade_id, {
                            'price': trade_obj.get('price', 0),
                            'action': action,
                            'is_stop_loss': action == 'stop',
                            'ticker': trade_obj.get('ticker'),
                            'channel': trade_obj.get('channel')
                        }
                    )
        except Exception as e:
            print(f"Error updating performance tracking: {e}")

    async def _update_position_manager(self, trade_obj, action, active_position):
        """Update position manager for sell orders"""
        try:
            if active_position and active_position.get('trade_id'):
                if action in ("exit", "stop"):
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.position_manager.clear_position,
                        trade_obj['channel_id'], active_position['trade_id']
                    )
                else:  # trim
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.position_manager.update_position_status,
                        trade_obj['channel_id'], active_position['trade_id'], 'partially_trimmed'
                    )
        except Exception as e:
            print(f"Error updating position manager: {e}")

    async def _handle_trailing_stop_async(self, trade_obj, active_position):
        """Handle trailing stop placement asynchronously"""
        try:
            # Implementation for trailing stops if needed
            pass
        except Exception as e:
            print(f"Error handling trailing stop: {e}")

    # Helper methods
    async def _handle_trailing_stop_async(self, trade_obj, active_position):
        """Handle trailing stop placement asynchronously"""
        try:
            if not active_position:
                return

            await asyncio.get_event_loop().run_in_executor(
                None, self._handle_trailing_stop_sync, trade_obj, active_position
            )
        except Exception as e:
            print(f"Error handling trailing stop: {e}")

    # Helper methods for fast execution
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

    def _find_position_fast(self, trade_obj, channel_name):
        """Fast position lookup with minimal blocking"""
        try:
            # Try position manager first
            active_position = self.position_manager.find_position(trade_obj['channel_id'], trade_obj)
            if active_position:
                return active_position

            # Try performance tracker as fallback
            if trade_obj.get('ticker'):
                trade_id = self.performance_tracker.find_open_trade_by_ticker(
                    trade_obj['ticker'], channel_name
                )
                if trade_id:
                    return {'trade_id': trade_id}

            return None
        except Exception as e:
            print(f"Error finding position fast: {e}")
            return None

    def _fill_missing_details_fast(self, trade_obj, channel_name, active_position):
        """Fast contract detail filling using feedback history"""
        try:
            symbol = trade_obj.get("ticker")
            strike = trade_obj.get("strike")
            expiration = trade_obj.get("expiration")
            opt_type = trade_obj.get("type")

            # Get from active position first
            if active_position:
                symbol = symbol or (active_position.get("trader_symbol") or active_position.get("symbol"))
                strike = strike or active_position.get("strike")
                expiration = expiration or active_position.get("expiration")
                opt_type = opt_type or active_position.get("type")

            # Handle BE (Break Even) price
            if trade_obj.get('price') == 'BE' or str(trade_obj.get('price', '')).upper() == 'BE':
                if active_position:
                    entry_price = active_position.get('entry_price') or active_position.get('purchase_price')
                    if entry_price:
                        trade_obj['price'] = entry_price
                        trade_obj['is_breakeven'] = True

            # Fill from feedback if still missing
            if symbol and (not strike or not expiration or not opt_type):
                recent_parse = self.feedback_logger.get_recent_parse_for_channel(channel_name, symbol)
                if recent_parse:
                    strike = strike or recent_parse.get('strike')
                    expiration = expiration or recent_parse.get('expiration')
                    opt_type = opt_type or recent_parse.get('type')

            # Update trade object
            trade_obj.update({
                'ticker': symbol,
                'strike': strike,
                'expiration': expiration,
                'type': opt_type
            })

            return trade_obj

        except Exception as e:
            print(f"Error filling missing details: {e}")
            return trade_obj

    def _validate_contract_details(self, trade_obj):
        """Fast validation of contract details"""
        return all([
            trade_obj.get('ticker'),
            trade_obj.get('strike'),
            trade_obj.get('expiration'),
            trade_obj.get('type')
        ])

    def _handle_trailing_stop_sync(self, trade_obj, active_position):
        """Synchronous trailing stop handling"""
        try:
            if not active_position:
                return

            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']

            # Skip for simulated trader
            trader = self.live_trader
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                print(f"[SIMULATED] Would place trailing stop for remaining position")
                return

            # Get remaining position
            all_positions = trader.get_open_option_positions()
            remaining_position = trader.find_open_option_position(all_positions, symbol, strike, expiration,
                                                                  opt_type)

            if remaining_position:
                remaining_qty = int(float(remaining_position.get('quantity', 0)))
                purchase_price = float(active_position.get("purchase_price", 0.0))

                if remaining_qty > 0 and purchase_price > 0:
                    # Get current market price
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
                    config = CHANNELS_CONFIG.get(trade_obj.get('channel'))
                    trailing_stop_pct = config.get("trailing_stop_loss_pct", 0.20) if config else 0.20
                    trailing_stop_candidate = current_market_price * (1 - trailing_stop_pct)
                    new_stop_price = max(trailing_stop_candidate, purchase_price)

                    tick_size = self._get_tick_size_fast(trader, symbol)
                    new_stop_price_rounded = self._round_to_tick(new_stop_price, tick_size)

                    print(
                        f"Placing trailing stop for remaining {remaining_qty} contracts @ ${new_stop_price_rounded:.2f}")

                    try:
                        new_stop_response = trader.place_option_stop_loss_order(
                            symbol, strike, expiration, opt_type, remaining_qty, new_stop_price_rounded
                        )
                        print(f"Trailing stop placed: {new_stop_response}")
                    except Exception as e:
                        print(f"Failed to place trailing stop: {e}")

        except Exception as e:
            print(f"Trailing stop error: {e}")

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
            "footer": {"text": "RHTB v4 Enhanced - FAST EXECUTION"}
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

        # Execution details with tick size info
        position_value = price * quantity * 100 if isinstance(price, (int, float)) else 0
        tick_size_info = ""
        if trade_data.get('tick_size_used'):
            tick_size_info = f"\n**Tick Size:** ${trade_data['tick_size_used']:.2f}"

        execution_info = f"""
**Quantity:** {quantity} contracts
**Price:** ${price if isinstance(price, str) else f'{price:.2f}'}
**Total Value:** ${position_value:,.2f}{tick_size_info}
        """.strip()

        embed["fields"].append({
            "name": "💰 Execution Details",
            "value": execution_info,
            "inline": True
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

    # Public API method for backwards compatibility
    async def process_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id=None,
                            is_edit=False, event_loop=None):
        """
        Main public API - Routes to fast execution method
        """
        await self.process_trade_fast(handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit,
                                      event_loop)


# Export the class
__all__ = ['FastTradeExecutor']