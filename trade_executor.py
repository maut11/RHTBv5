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
    MAX_DOLLAR_AMOUNT, MIN_CONTRACTS, MAX_CONTRACTS, DEFAULT_BUY_PRICE_PADDING,
    DEFAULT_SELL_PRICE_PADDING, STOP_LOSS_DELAY_SECONDS, TRIM_PERCENTAGE,
    TRIM_CASCADE_STEPS, EXIT_CASCADE_STEPS,
    ALL_NOTIFICATION_WEBHOOK, PLAYS_WEBHOOK, LIVE_FEED_WEBHOOK,
    get_broker_symbol, get_trader_symbol, get_all_symbol_variants,
    SYMBOL_NORMALIZATION_CONFIG
)
# Removed portfolio_update_filter - filtering now handled at channel level

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
                            "Broker Symbol",
                            "API Mark Price",
                            "API Bid Price",
                            "API Ask Price",
                            "API Last Price"
                        ])

    def log(self, channel_name, original_message, parsed_message_json, latency=0, trader=None):
        """Log parse result with symbol mapping and API price information"""
        with self.lock:
            try:
                # Extract symbol information
                trader_symbol = parsed_message_json.get('ticker', '')
                broker_symbol = get_broker_symbol(trader_symbol) if trader_symbol else ''
                
                # Get API price data if we have complete contract info and trader
                mark_price = bid_price = ask_price = last_price = ""
                
                if (trader and trader_symbol and 
                    parsed_message_json.get('strike') and 
                    parsed_message_json.get('type') and 
                    parsed_message_json.get('expiration')):
                    
                    try:
                        market_data = trader.get_option_market_data(
                            trader_symbol,
                            parsed_message_json.get('expiration'),
                            parsed_message_json.get('strike'),
                            parsed_message_json.get('type')
                        )
                        
                        if market_data:
                            # Handle different market_data formats
                            data_dict = None
                            if isinstance(market_data, dict):
                                data_dict = market_data
                            elif isinstance(market_data, list) and len(market_data) > 0:
                                if isinstance(market_data[0], dict):
                                    data_dict = market_data[0]
                                elif isinstance(market_data[0], list) and len(market_data[0]) > 0 and isinstance(market_data[0][0], dict):
                                    data_dict = market_data[0][0]
                            
                            if data_dict:
                                mark_price = f"{data_dict.get('mark_price', '')}"
                                bid_price = f"{data_dict.get('bid_price', '')}"
                                ask_price = f"{data_dict.get('ask_price', '')}"
                                last_price = f"{data_dict.get('last_trade_price', '')}"
                            else:
                                mark_price = bid_price = ask_price = last_price = ""
                    except Exception as price_error:
                        print(f"⚠️ Could not fetch API price for {trader_symbol}: {price_error}")
                
                with open(self.filename, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        channel_name,
                        original_message,
                        json.dumps(parsed_message_json),
                        f"{latency:.2f}",
                        datetime.now(timezone.utc).isoformat(),
                        trader_symbol,
                        broker_symbol,
                        mark_price,
                        bid_price,
                        ask_price,
                        last_price
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

    def __init__(self, live_trader, sim_trader, performance_tracker, position_manager,
                 alert_manager, position_ledger=None, auto_exit_manager=None):
        self.live_trader = live_trader
        self.sim_trader = sim_trader
        self.performance_tracker = performance_tracker
        self.position_manager = position_manager
        self.alert_manager = alert_manager
        self.position_ledger = position_ledger
        self.auto_exit_manager = auto_exit_manager

        # Enhanced feedback logger with symbol mapping
        self.feedback_logger = ChannelAwareFeedbackLogger()
        self.stop_loss_manager = DelayedStopLossManager()

        print("✅ Trade Executor initialized with symbol mapping support")
        if position_ledger:
            print("✅ Position ledger integration enabled")
        if auto_exit_manager:
            print("✅ Auto-exit manager integration enabled")
    
    def _schedule_delayed_stop(self, trader, trade_id, trade_obj, config,
                               symbol, strike, expiration, opt_type, price):
        """Schedule a delayed stop-loss order (non-Ryan channels)."""
        try:
            stop_price = trader.round_to_tick(
                price * (1 - config.get("initial_stop_loss", 0.50)),
                symbol, round_up_for_buy=False, expiration=expiration
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

    def _normalize_market_data(self, market_data) -> dict:
        """Normalize market data response to handle [[data]] vs [data] inconsistency"""
        try:
            if not market_data or len(market_data) == 0:
                return None
            
            # Handle [[data]] format (nested array)
            if isinstance(market_data[0], list):
                if len(market_data[0]) > 0 and isinstance(market_data[0][0], dict):
                    return market_data[0][0]
                else:
                    return None
            
            # Handle [data] format (single array)
            elif isinstance(market_data[0], dict):
                return market_data[0]
            
            return None
            
        except (IndexError, TypeError):
            return None

    def _send_cascade_alert(self, message, is_fill=False, is_error=False):
        """Send cascade status alert to Discord (thread-safe for blocking context).

        Sends to both ALL_NOTIFICATION_WEBHOOK (text) and LIVE_FEED_WEBHOOK (embed).
        """
        try:
            if hasattr(self, 'event_loop') and self.event_loop and self.alert_manager:
                # Send text to all notification webhook
                asyncio.run_coroutine_threadsafe(
                    self.alert_manager.add_alert(
                        ALL_NOTIFICATION_WEBHOOK,
                        {"content": message},
                        "cascade_notification"
                    ),
                    self.event_loop
                )

                # Send embed to live feed webhook
                # Determine color based on status
                if is_fill:
                    color = 0x00FF00  # Green for fills
                elif is_error:
                    color = 0xFF0000  # Red for errors
                else:
                    color = 0xFFAA00  # Orange for in-progress

                cascade_embed = {
                    "title": "📉 Sell Cascade Update",
                    "description": message,
                    "color": color,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "footer": {"text": "Cascade Sell System"}
                }

                asyncio.run_coroutine_threadsafe(
                    self.alert_manager.add_alert(
                        LIVE_FEED_WEBHOOK,
                        {"embeds": [cascade_embed]},
                        "cascade_live_feed"
                    ),
                    self.event_loop
                )
        except Exception as e:
            print(f"   ⚠️ Cascade alert failed: {e}")

    def _verify_order_cancelled(self, trader, order_id, log_func, max_wait=10):
        """
        Verify an order is cancelled or catch race-condition fills.
        Polls order state every 1s for up to max_wait seconds.

        Returns:
            tuple: (verified: bool, filled_during_cancel: bool, fill_price: float or None)
        """
        verify_start = time.time()
        last_state = "unknown"
        while time.time() - verify_start < max_wait:
            try:
                info = trader.get_option_order_info(order_id)
                if not info:
                    time.sleep(1)
                    continue
                last_state = (info.get('state') or 'unknown').lower()

                if last_state == 'filled':
                    fill_price = float(info.get('average_price', 0) or 0)
                    return True, True, fill_price

                if last_state in ('cancelled', 'rejected', 'failed'):
                    return True, False, None

            except Exception as e:
                log_func(f"   ⚠️ Verify error: {e}")
            time.sleep(1)

        log_func(f"   ⚠️ Cancel verification timeout (last state: {last_state})")
        return False, False, None

    def _cascade_sell(self, trader, symbol, strike, expiration, opt_type, quantity, cascade_steps, config, log_func):
        """
        Execute cascade sell with stepped-down pricing, order verification, and Discord alerts.

        Cascade flow:
        1. Start with highest price (e.g., ask for trims)
        2. Wait for fill or timeout
        3. If not filled, cancel and VERIFY cancelled (catch race-condition fills)
        4. Step down to next price level
        5. Continue until filled or all steps exhausted

        Returns:
            tuple: (success: bool, order_id: str or None, fill_price: float or None, step_used: int)
        """
        try:
            contract_label = f"{quantity}x {symbol} ${strike}{opt_type[0].upper()}"
            print(f"🔄 CASCADE SELL: {contract_label}")
            print(f"   Steps: {len(cascade_steps)}")

            self._send_cascade_alert(
                f"🔄 **Cascade Sell Started**\n"
                f"{contract_label}\n"
                f"Steps: {len(cascade_steps)}"
            )

            for step_num, step in enumerate(cascade_steps, 1):
                price_type = step.get('price_type', 'bid')
                multiplier = step.get('multiplier', 1.0)
                wait_seconds = step.get('wait_seconds', 30)

                # Get fresh market data
                market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
                data = self._normalize_market_data(market_data)

                # Build market data snapshot for alerts
                md_snapshot = "No data"
                if data:
                    bid = float(data.get('bid_price', 0) or 0)
                    ask = float(data.get('ask_price', 0) or 0)
                    mark = float(data.get('mark_price', 0) or 0)
                    md_snapshot = f"B: ${bid:.2f} | A: ${ask:.2f} | M: ${mark:.2f}"
                else:
                    log_func(f"⚠️ No market data for step {step_num}")
                    self._send_cascade_alert(f"⚠️ Step {step_num}/{len(cascade_steps)} — No market data, skipping")
                    continue

                # Determine price based on price_type
                if price_type == 'ask':
                    base_price = float(data.get('ask_price', 0) or 0)
                elif price_type == 'mark':
                    base_price = float(data.get('mark_price', 0) or 0)
                elif price_type == 'midpoint':
                    base_price = (bid + ask) / 2 if bid > 0 and ask > 0 else bid
                elif price_type == 'bid':
                    base_price = float(data.get('bid_price', 0) or 0)
                else:
                    base_price = float(data.get('mark_price', 0) or 0)

                if base_price <= 0:
                    log_func(f"⚠️ Invalid base price for step {step_num}: ${base_price}")
                    self._send_cascade_alert(f"⚠️ Step {step_num}/{len(cascade_steps)} — Invalid {price_type} price, skipping")
                    continue

                # Apply multiplier and round
                limit_price = trader.round_to_tick(
                    base_price * multiplier,
                    symbol,
                    round_up_for_buy=False,
                    expiration=expiration
                )

                print(f"   Step {step_num}/{len(cascade_steps)}: {price_type} × {multiplier} = ${limit_price:.2f} (wait: {wait_seconds}s)")

                self._send_cascade_alert(
                    f"📉 **Step {step_num}/{len(cascade_steps)}** — {contract_label}\n"
                    f"Price: **${limit_price:.2f}** ({price_type} × {multiplier})\n"
                    f"Market: {md_snapshot}\n"
                    f"Wait: {wait_seconds}s"
                )

                # Cancel any existing orders first
                try:
                    trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
                except Exception as e:
                    print(f"   ⚠️ Cancel error (proceeding): {e}")

                # Place order at this price level
                try:
                    sell_response = trader.place_option_sell_order(
                        symbol, strike, expiration, opt_type, quantity, limit_price
                    )

                    if not sell_response or sell_response.get('error'):
                        err = sell_response.get('error', sell_response) if sell_response else 'No response'
                        log_func(f"   ❌ Step {step_num} order failed: {err}")
                        self._send_cascade_alert(f"❌ Step {step_num} order failed: {err}", is_error=True)
                        continue

                    order_id = sell_response.get('id')
                    print(f"   📝 Order placed: {order_id}")

                    # Wait for fill or timeout
                    if wait_seconds > 0:
                        confirmation = trader.wait_for_order_confirmation(
                            order_id,
                            max_wait_seconds=wait_seconds
                        )

                        status = confirmation.get('status')

                        if status == 'filled':
                            fill_price = float(confirmation.get('average_price', limit_price))
                            print(f"   ✅ FILLED at step {step_num}: ${fill_price:.2f}")
                            self._send_cascade_alert(
                                f"✅ **FILLED** at step {step_num}/{len(cascade_steps)}\n"
                                f"{contract_label} @ **${fill_price:.2f}**",
                                is_fill=True
                            )
                            return True, order_id, fill_price, step_num

                        elif status in ('cancelled', 'rejected', 'failed'):
                            log_func(f"   ❌ Order {status} at step {step_num}")
                            self._send_cascade_alert(f"❌ Step {step_num} — Order {status}", is_error=True)
                            continue

                        # Not filled — cancel specific order and verify before stepping down
                        print(f"   ⏰ Timeout at step {step_num} — cancelling & verifying...")
                        try:
                            trader.cancel_option_order(order_id)
                        except Exception as e:
                            print(f"   ⚠️ Cancel error: {e}")

                        # Verify cancellation (catch race-condition fills)
                        verified, filled_during_cancel, race_fill_price = self._verify_order_cancelled(
                            trader, order_id, log_func
                        )

                        if filled_during_cancel:
                            print(f"   ✅ FILLED during cancel at step {step_num}: ${race_fill_price:.2f}")
                            self._send_cascade_alert(
                                f"✅ **FILLED** (during cancel) at step {step_num}/{len(cascade_steps)}\n"
                                f"{contract_label} @ **${race_fill_price:.2f}**",
                                is_fill=True
                            )
                            return True, order_id, race_fill_price, step_num

                        if verified:
                            self._send_cascade_alert(f"⏰ Step {step_num} timed out — stepping down")
                        else:
                            self._send_cascade_alert(f"⚠️ Step {step_num} cancel unverified — stepping down")

                    else:
                        # Last step (wait_seconds=0) — place and let it fill
                        print(f"   🏁 Final step {step_num} — order placed at ${limit_price:.2f}")
                        self._send_cascade_alert(
                            f"🏁 **Final step {step_num}/{len(cascade_steps)}** — {contract_label}\n"
                            f"Limit: **${limit_price:.2f}** (letting it fill)"
                        )
                        return True, order_id, limit_price, step_num

                except Exception as e:
                    log_func(f"   ❌ Step {step_num} error: {e}")
                    self._send_cascade_alert(f"❌ Step {step_num} error: {e}")
                    continue

            # All steps exhausted without fill
            log_func(f"❌ CASCADE FAILED: All {len(cascade_steps)} steps exhausted")
            self._send_cascade_alert(f"❌ **Cascade Failed** — All {len(cascade_steps)} steps exhausted\n{contract_label}")
            return False, None, None, 0

        except Exception as e:
            log_func(f"❌ CASCADE ERROR: {e}")
            self._send_cascade_alert(f"❌ **Cascade Error**: {e}")
            return False, None, None, 0

    def _cascade_buy(self, trader, symbol, strike, expiration, opt_type, quantity,
                     cascade_steps, config, log_func, max_price_cap):
        """
        Execute cascade buy with stepped pricing, hard cap, and BP retry.

        Steps up through price levels (midpoint → ask discount → ask → cap),
        with each price strictly capped at max_price_cap. Reuses _verify_order_cancelled
        to catch race-condition fills between steps. Includes buying power retry
        to handle Robinhood's ledger lag after order cancellation.

        Args:
            max_price_cap: Hard price cap (parsed_price × 1.025). NEVER exceeded.

        Returns:
            tuple: (success, order_id, fill_price, step_used)
        """
        try:
            contract_label = f"{quantity}x {symbol} ${strike}{opt_type[0].upper()}"
            resting_timeout = config.get('resting_order_timeout', 300)
            print(f"🔄 CASCADE BUY: {contract_label}")
            print(f"   Steps: {len(cascade_steps)} | Cap: ${max_price_cap:.2f} | Rest timeout: {resting_timeout}s")

            self._send_cascade_alert(
                f"🔄 **Cascade Buy Started**\n"
                f"{contract_label}\n"
                f"Cap: **${max_price_cap:.2f}** | Steps: {len(cascade_steps)} | Rest: {resting_timeout}s"
            )

            last_order_id = None

            for step_num, step in enumerate(cascade_steps, 1):
                price_type = step.get('price_type', 'ask')
                multiplier = step.get('multiplier', 1.0)
                wait_seconds = step.get('wait_seconds', 30)

                # --- Cancel previous order ---
                if last_order_id:
                    try:
                        trader.cancel_option_order(last_order_id)
                    except Exception as e:
                        print(f"   ⚠️ Cancel error: {e}")

                    verified, filled_during_cancel, race_fill_price = self._verify_order_cancelled(
                        trader, last_order_id, log_func
                    )

                    if filled_during_cancel:
                        print(f"   ✅ FILLED during cancel at step {step_num}: ${race_fill_price:.2f}")
                        self._send_cascade_alert(
                            f"✅ **FILLED** (during cancel) at step {step_num}/{len(cascade_steps)}\n"
                            f"{contract_label} @ **${race_fill_price:.2f}**"
                        )
                        return True, last_order_id, race_fill_price, step_num

                    last_order_id = None

                # --- Get fresh market data ---
                market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
                data = self._normalize_market_data(market_data)

                md_snapshot = "No data"
                if data:
                    bid = float(data.get('bid_price', 0) or 0)
                    ask = float(data.get('ask_price', 0) or 0)
                    mark = float(data.get('mark_price', 0) or 0)
                    md_snapshot = f"B: ${bid:.2f} | A: ${ask:.2f} | M: ${mark:.2f}"
                else:
                    log_func(f"⚠️ No market data for step {step_num}")
                    self._send_cascade_alert(f"⚠️ Step {step_num}/{len(cascade_steps)} — No market data, skipping")
                    continue

                # --- Calculate target price based on price_type ---
                if price_type == 'cap':
                    target_price = max_price_cap
                elif price_type == 'midpoint':
                    target_price = ((bid + ask) / 2 if bid > 0 and ask > 0 else ask) * multiplier
                elif price_type == 'ask':
                    target_price = (float(data.get('ask_price', 0) or 0)) * multiplier
                elif price_type == 'mark':
                    target_price = (float(data.get('mark_price', 0) or 0)) * multiplier
                elif price_type == 'bid':
                    target_price = (float(data.get('bid_price', 0) or 0)) * multiplier
                else:
                    target_price = (float(data.get('ask_price', 0) or 0)) * multiplier

                if target_price <= 0:
                    log_func(f"⚠️ Invalid target price for step {step_num}: ${target_price}")
                    self._send_cascade_alert(f"⚠️ Step {step_num} — Invalid {price_type} price, skipping")
                    continue

                # --- HARD CAP: never exceed max_price_cap ---
                capped_price = min(target_price, max_price_cap)

                # Round to tick — round UP for buys normally
                limit_price = trader.round_to_tick(capped_price, symbol, round_up_for_buy=True, expiration=expiration)

                # If rounding pushed above cap, round DOWN instead
                if limit_price > max_price_cap:
                    limit_price = trader.round_to_tick(capped_price, symbol, round_up_for_buy=False, expiration=expiration)

                # Final safety check
                if limit_price > max_price_cap:
                    log_func(f"⚠️ Step {step_num}: rounded price ${limit_price:.2f} exceeds cap ${max_price_cap:.2f}, using cap")
                    limit_price = max_price_cap

                print(f"   Step {step_num}/{len(cascade_steps)}: {price_type}×{multiplier} → ${target_price:.2f} → capped ${limit_price:.2f} (wait: {wait_seconds}s)")

                self._send_cascade_alert(
                    f"📈 **Step {step_num}/{len(cascade_steps)}** — {contract_label}\n"
                    f"Limit: **${limit_price:.2f}** ({price_type}×{multiplier}, cap ${max_price_cap:.2f})\n"
                    f"Market: {md_snapshot}\n"
                    f"Wait: {wait_seconds}s"
                )

                # --- Place order with BP retry loop ---
                buy_response = None
                order_id = None
                for bp_attempt in range(3):
                    try:
                        buy_response = trader.place_option_buy_order(
                            symbol, strike, expiration, opt_type, quantity, limit_price,
                            exact_price=True
                        )

                        if buy_response and buy_response.get('id') and not buy_response.get('error'):
                            order_id = buy_response.get('id')
                            break

                        # Check for buying power error
                        error_str = str(buy_response.get('error', '') if buy_response else '')
                        if 'insufficient' in error_str.lower() or 'buying power' in error_str.lower():
                            log_func(f"   ⚠️ BP not released yet, retry {bp_attempt+1}/3...")
                            time.sleep(1)
                            continue
                        else:
                            # Non-BP error, don't retry
                            break

                    except Exception as e:
                        log_func(f"   ❌ Order placement error attempt {bp_attempt+1}: {e}")
                        time.sleep(1)

                if not order_id:
                    err = buy_response.get('error', buy_response) if buy_response else 'No response'
                    log_func(f"   ❌ Step {step_num} order failed after retries: {err}")
                    self._send_cascade_alert(f"❌ Step {step_num} order failed: {err}")
                    continue

                last_order_id = order_id
                print(f"   📝 Order placed: {order_id}")

                # --- Wait for fill ---
                if wait_seconds > 0:
                    # Poll every 1s for tight fill detection
                    poll_start = time.time()
                    filled = False
                    while time.time() - poll_start < wait_seconds:
                        time.sleep(1)
                        try:
                            info = trader.get_option_order_info(order_id)
                            if not info:
                                continue
                            state = (info.get('state') or '').lower()

                            if state == 'filled':
                                fill_price = float(info.get('average_price', 0) or limit_price)
                                print(f"   ✅ FILLED at step {step_num}: ${fill_price:.2f}")
                                self._send_cascade_alert(
                                    f"✅ **FILLED** at step {step_num}/{len(cascade_steps)}\n"
                                    f"{contract_label} @ **${fill_price:.2f}**"
                                )
                                return True, order_id, fill_price, step_num

                            elif state in ('cancelled', 'rejected', 'failed'):
                                log_func(f"   ❌ Order {state} at step {step_num}")
                                self._send_cascade_alert(f"❌ Step {step_num} — Order {state}")
                                last_order_id = None
                                filled = True  # Break outer, but not a fill
                                break

                        except Exception as e:
                            log_func(f"   ⚠️ Poll error: {e}")

                    if filled:
                        continue  # Order was cancelled/rejected, try next step

                    # Not filled — step timed out, continue to next step
                    print(f"   ⏰ Timeout at step {step_num} — stepping up")
                    self._send_cascade_alert(f"⏰ Step {step_num} timed out — stepping up")

                else:
                    # Last step (wait_seconds=0) — resting order at cap
                    print(f"   🏁 Resting order at ${limit_price:.2f} — timeout {resting_timeout}s")
                    self._send_cascade_alert(
                        f"🏁 **Resting order** — {contract_label}\n"
                        f"Limit: **${limit_price:.2f}** | Timeout: {resting_timeout}s"
                    )

                    # Poll during resting timeout
                    rest_start = time.time()
                    while time.time() - rest_start < resting_timeout:
                        time.sleep(10)  # Poll every 10s during rest
                        try:
                            info = trader.get_option_order_info(order_id)
                            if not info:
                                continue
                            state = (info.get('state') or '').lower()

                            if state == 'filled':
                                fill_price = float(info.get('average_price', 0) or limit_price)
                                elapsed = time.time() - rest_start
                                print(f"   ✅ FILLED during rest after {elapsed:.0f}s: ${fill_price:.2f}")
                                self._send_cascade_alert(
                                    f"✅ **FILLED** during resting period ({elapsed:.0f}s)\n"
                                    f"{contract_label} @ **${fill_price:.2f}**"
                                )
                                return True, order_id, fill_price, step_num

                            elif state in ('cancelled', 'rejected', 'failed'):
                                log_func(f"   ❌ Resting order {state}")
                                self._send_cascade_alert(f"❌ Resting order {state}")
                                return False, None, None, 0

                        except Exception as e:
                            log_func(f"   ⚠️ Rest poll error: {e}")

                    # Resting order timed out — cancel it
                    print(f"   ⏰ Resting order timed out after {resting_timeout}s")
                    try:
                        trader.cancel_option_order(order_id)
                        verified, filled_on_cancel, race_price = self._verify_order_cancelled(
                            trader, order_id, log_func
                        )
                        if filled_on_cancel:
                            print(f"   ✅ FILLED during final cancel: ${race_price:.2f}")
                            self._send_cascade_alert(
                                f"✅ **FILLED** (during cancel)\n"
                                f"{contract_label} @ **${race_price:.2f}**"
                            )
                            return True, order_id, race_price, step_num
                    except Exception as e:
                        log_func(f"   ⚠️ Final cancel error: {e}")

                    self._send_cascade_alert(
                        f"⏰ **Missed Trade** — Resting order expired\n"
                        f"{contract_label} | Cap: ${max_price_cap:.2f}"
                    )
                    return False, None, None, 0

            # All steps exhausted (shouldn't reach here with last step wait_seconds=0)
            log_func(f"❌ CASCADE BUY FAILED: All {len(cascade_steps)} steps exhausted")
            self._send_cascade_alert(f"❌ **Cascade Buy Failed** — All steps exhausted\n{contract_label}")
            return False, None, None, 0

        except Exception as e:
            log_func(f"❌ CASCADE BUY ERROR: {e}")
            self._send_cascade_alert(f"❌ **Cascade Buy Error**: {e}")
            return False, None, None, 0

    async def process_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id=None, is_edit=False, event_loop=None, message_history=None):
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
            handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, enhanced_log, message_history
        )
    
    def _blocking_handle_trade(self, handler, message_meta, raw_msg, is_sim_mode, received_ts, message_id, is_edit, log_func, message_history=None):
        """Blocking trade execution logic with symbol mapping"""
        try:
            log_func(f"🔄 Processing message from {handler.name}: {raw_msg[:100]}...")

            # Parse the message with optional history context
            try:
                parsed_results, latency_ms = handler.parse_message(message_meta, received_ts, log_func, message_history)
                
                # Portfolio filtering now handled at channel level (pre-OpenAI)
                # No additional filtering needed here
                
                if parsed_results:
                    for parsed_obj in parsed_results:
                        # Log with CHANNEL-SPECIFIC feedback including symbol mapping and API prices
                        # Use live_trader for API price data regardless of sim mode for tracking purposes
                        self.feedback_logger.log(handler.name, raw_msg, parsed_obj, latency_ms, self.live_trader)
                
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
                    ledger_position = None  # Track position from ledger for later use
                    if action in ("trim", "exit", "stop"):
                        # FIRST: Try position ledger with weighted matching
                        if self.position_ledger and trade_obj.get('ticker'):
                            hints = {
                                'strike': trade_obj.get('strike'),
                                'expiry': trade_obj.get('expiration'),
                                'type': trade_obj.get('type'),
                            }
                            ledger_position = self.position_ledger.resolve_position(
                                trade_obj['ticker'], hints
                            )
                            if ledger_position:
                                log_func(f"📒 Ledger found position: {ledger_position.ccid}")
                                # Fill in missing contract details from ledger
                                if not trade_obj.get('strike'):
                                    trade_obj['strike'] = ledger_position.strike
                                if not trade_obj.get('expiration'):
                                    trade_obj['expiration'] = ledger_position.expiration
                                if not trade_obj.get('type'):
                                    trade_obj['type'] = ledger_position.option_type
                                # Store CCID for later ledger update
                                trade_obj['ledger_ccid'] = ledger_position.ccid

                        # SECOND: Try position manager with symbol variants
                        active_position = self.position_manager.find_position(trade_obj['channel_id'], trade_obj) or {}

                        # If we found a position, UPDATE trade_obj with the original trade_id
                        # This ensures proper position tracking and linking
                        if active_position and active_position.get('trade_id'):
                            trade_obj['trade_id'] = active_position['trade_id']
                            log_func(f"✅ Linked to original position: {active_position['trade_id']}")

                        # THIRD: Try performance tracker with symbol variants (fallback)
                        elif not active_position and trade_obj.get('ticker'):
                            # Pass the original ticker, performance tracker should handle variants
                            trade_id = self.performance_tracker.find_open_trade_by_ticker(
                                trade_obj['ticker'], handler.name
                            )
                            if trade_id:
                                log_func(f"🔍 Found open trade by ticker in {handler.name}: {trade_id}")
                                active_position = {'trade_id': trade_id}
                                trade_obj['trade_id'] = trade_id

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
                        
                        # If CSV fallback still didn't provide complete info, try Robinhood API fallback
                        if not all([strike, expiration, opt_type]) and action in ["trim", "stop"]:
                            log_func(f"🔍 CSV fallback incomplete, trying Robinhood API fallback for {symbol}...")
                            try:
                                from robinhood_positions import get_contract_info_for_ticker
                                rh_contract = get_contract_info_for_ticker(symbol, trader, handler.name)
                                if rh_contract:
                                    strike = strike or rh_contract.get('strike')
                                    expiration = expiration or rh_contract.get('expiration')
                                    opt_type = opt_type or rh_contract.get('type')
                                    log_func(f"✅ Robinhood API fallback found: {symbol} ${strike}{opt_type} {expiration}")
                                else:
                                    log_func(f"⚠️ No matching position found in Robinhood for {symbol}")
                            except Exception as e:
                                log_func(f"❌ Robinhood API fallback failed: {str(e)}", "ERROR")
                    
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
                        
                        # Generate trade ID for both successful trades and tracking-only
                        trade_id = f"trade_{int(datetime.now().timestamp() * 1000)}"
                        trade_obj['trade_id'] = trade_id
                        
                        if execution_success:
                            # ========== ASYNC NON-BLOCKING UPDATES (AFTER SUCCESSFUL TRADE) ==========
                            # Fire these tasks asynchronously - don't wait for them
                            print(f"📊 TRADE PLACED SUCCESSFULLY - Starting async updates...")
                            
                            # 1. Stop loss / auto-exit setup (non-blocking)
                            price = trade_obj.get('price', 0)
                            if price > 0 and not trade_obj.get('is_breakeven'):
                                # Ryan: use auto-exit (tiered profit + stop) instead of delayed stop
                                ccid = trade_obj.get('ledger_ccid')
                                if self.auto_exit_manager and handler.name == 'Ryan' and ccid:
                                    try:
                                        ae_success = self.auto_exit_manager.setup_strategy(
                                            ccid, price, trade_obj.get('quantity', 1),
                                            symbol, strike, expiration, opt_type
                                        )
                                        if ae_success:
                                            trade_obj['auto_exit_active'] = True
                                            print(f"🎯 Auto-exit active — skipping delayed stop")
                                        else:
                                            # Fallback to delayed stop if auto-exit setup fails
                                            print(f"⚠️ Auto-exit failed, falling back to delayed stop")
                                            self._schedule_delayed_stop(
                                                trader, trade_id, trade_obj, config,
                                                symbol, strike, expiration, opt_type, price
                                            )
                                    except Exception as e:
                                        print(f"⚠️ Auto-exit exception, falling back to delayed stop: {e}")
                                        self._schedule_delayed_stop(
                                            trader, trade_id, trade_obj, config,
                                            symbol, strike, expiration, opt_type, price
                                        )
                                else:
                                    # Non-Ryan channels: existing delayed stop
                                    self._schedule_delayed_stop(
                                        trader, trade_id, trade_obj, config,
                                        symbol, strike, expiration, opt_type, price
                                    )
                        
                        # 2. Record in tracking systems (ONLY if successful OR tracking-only)
                        # BUG FIX: Failed cascade buys should NOT be recorded as entries
                        if execution_success or trade_obj.get('is_tracking_only'):
                            try:
                                # Mark as tracking-only if applicable
                                if trade_obj.get('is_tracking_only'):
                                    trade_obj['status'] = 'tracking_only'
                                    print(f"📊 Recording tracking-only entry: {symbol} @ ${trade_obj.get('price', 0):.2f}")
                                else:
                                    trade_obj['status'] = 'active'
                                    print(f"✅ Recording active trade entry")

                                self.performance_tracker.record_entry(trade_obj)
                                if not trade_obj.get('is_tracking_only'):
                                    self.position_manager.add_position(trade_obj['channel_id'], trade_obj)

                                # Position already created in 'opening' status by _execute_buy_order()
                                # Fill monitoring task will transition to 'open' when filled
                                if trade_obj.get('ledger_ccid'):
                                    print(f"📒 Position in ledger (opening): {trade_obj['ledger_ccid']}")

                                print(f"✅ Performance tracking updated")
                            except Exception as e:
                                print(f"⚠️ Performance tracking failed (non-critical): {e}")
                        
                        # 3. Send alerts (async, fire-and-forget) - for all trades
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
                        # ========== AUTO-EXIT OVERRIDE CHECK (Ryan) ==========
                        if self.auto_exit_manager and handler.name == 'Ryan':
                            ae_ccid = trade_obj.get('ledger_ccid')
                            if ae_ccid and self.auto_exit_manager.has_active_strategy(ae_ccid):
                                if action == "trim":
                                    # Ignore trims — auto-exit is managing this position
                                    print(f"⏭️ Ignoring Ryan TRIM — auto-exit managing {symbol}")
                                    log_func(f"⏭️ Ignoring Ryan TRIM — auto-exit active for {symbol}")
                                    result_summary = "Trim skipped (auto-exit active)"
                                    # Send notification only, no trade execution
                                    try:
                                        asyncio.run_coroutine_threadsafe(
                                            self._send_trade_alert(
                                                trade_obj, 'trim_skipped', 0, 0, is_sim_mode
                                            ),
                                            self.event_loop
                                        )
                                    except Exception:
                                        pass
                                    log_func(f"📊 Trade Summary: {result_summary}")
                                    continue
                                elif action in ("exit", "stop"):
                                    # Cancel auto-exit, then proceed with normal cascade sell
                                    print(f"🔄 Cancelling auto-exit for {symbol} — manual EXIT")
                                    log_func(f"🔄 Cancelling auto-exit for {symbol} — manual EXIT override")
                                    self.auto_exit_manager.cancel_strategy(ae_ccid)

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
                        
                        # Log the calculated market price (after _execute_sell_order updates trade_obj['price'])
                        calculated_price = trade_obj.get('price', 0)
                        log_func(f"💰 Calculated {action} price: ${calculated_price:.2f} (with market data + padding)")
                        
                        # Handle tracking and performance updates for both real trades and tracking-only
                        if (execution_success and trade_id) or trade_obj.get('is_tracking_only'):
                            # ========== ASYNC NON-BLOCKING UPDATES (AFTER TRADE OR TRACKING) ==========
                            if execution_success:
                                print(f"📊 TRADE PLACED SUCCESSFULLY - Starting async updates...")
                            else:
                                print(f"📊 TRACKING-ONLY PROCESSING - Recording performance data...")
                            
                            try:
                                if action == "trim":
                                    # Record trim (non-blocking) - for both real and tracking-only
                                    trim_data = {
                                        'quantity': trade_obj.get('quantity', 1),
                                        'price': trade_obj.get('price', 0),
                                        'ticker': trade_obj.get('ticker'),
                                        'channel': handler.name,
                                        'is_tracking_only': trade_obj.get('is_tracking_only', False),
                                        'market_price_at_alert': trade_obj.get('market_price_at_alert')
                                    }
                                    
                                    if trade_obj.get('is_tracking_only'):
                                        print(f"📊 Recording tracking-only trim: {symbol} @ ${trade_obj.get('price', 0):.2f}")
                                        # Create a virtual trade record for tracking
                                        trade_record = {'status': 'tracking_only', 'action': action}
                                    else:
                                        trade_record = self.performance_tracker.record_trim(trade_id, trim_data)
                                    
                                    # Handle trailing stop (async, non-critical) - only for real trades
                                    if not trade_obj.get('is_tracking_only'):
                                        try:
                                            self._handle_trailing_stop(
                                                trader, trade_obj, config, active_position, log_func, is_sim_mode
                                            )
                                            print(f"✅ Trailing stop handled")
                                        except Exception as e:
                                            print(f"⚠️ Trailing stop failed (non-critical): {e}")
                                    
                                else:  # exit or stop
                                    # Record exit (non-blocking) - for both real and tracking-only
                                    exit_data = {
                                        'price': trade_obj.get('price', 0),
                                        'action': action,
                                        'is_stop_loss': action == 'stop',
                                        'ticker': trade_obj.get('ticker'),
                                        'channel': handler.name,
                                        'is_tracking_only': trade_obj.get('is_tracking_only', False),
                                        'market_price_at_alert': trade_obj.get('market_price_at_alert')
                                    }
                                    
                                    if trade_obj.get('is_tracking_only'):
                                        print(f"📊 Recording tracking-only exit: {symbol} @ ${trade_obj.get('price', 0):.2f}")
                                        # Create a virtual trade record for tracking
                                        trade_record = {'status': 'tracking_only', 'action': action}
                                    else:
                                        trade_record = self.performance_tracker.record_exit(trade_id, exit_data)

                                        if trade_record:
                                            self.position_manager.clear_position(trade_obj['channel_id'], trade_id)
                                            print(f"✅ Position cleared")

                                # Update position ledger for trim/exit
                                if self.position_ledger and trade_obj.get('ledger_ccid') and not trade_obj.get('is_tracking_only'):
                                    try:
                                        sell_qty = trade_obj.get('quantity', 1)
                                        sell_price = trade_obj.get('price', 0)
                                        self.position_ledger.record_sell(
                                            trade_obj['ledger_ccid'], sell_qty, sell_price
                                        )
                                        print(f"📒 Ledger updated: sold {sell_qty} @ ${sell_price:.2f}")
                                    except Exception as le:
                                        print(f"⚠️ Ledger sell update failed (non-critical): {le}")

                                print(f"✅ Performance tracking updated")
                                
                            except Exception as e:
                                print(f"⚠️ Performance tracking failed (non-critical): {e}")
                            
                            # Send alerts (async, fire-and-forget) - for all trades including tracking-only
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

        # Handle "market" price (e.g., "Stopped out" without a price)
        if str(cleaned_data.get('price', '')).lower() == 'market':
            cleaned_data['price'] = 0
            cleaned_data['is_market_exit'] = True

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
        """
        Execute buy order with position state machine integration.

        Flow:
        1. Calculate position size with MIN_CONTRACTS/MAX_CONTRACTS enforcement
        2. Create position in 'opening' status BEFORE placing order
        3. Place buy order with Robinhood
        4. Store order_id for fill monitoring task to track
        5. Fill monitoring task will transition to 'open' when filled
        """
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
            resting_timeout = config.get('resting_order_timeout', 300)

            # TIERED LOGIC: Long-dated contracts (>= 30 days) get wider padding & longer timeout
            if expiration:
                try:
                    from datetime import datetime, timezone
                    exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
                    today = datetime.now(timezone.utc).date()
                    days_to_expiry = (exp_date - today).days

                    if days_to_expiry >= 30:
                        buy_padding = 0.05  # 5% padding for monthly+ contracts
                        resting_timeout = 600  # 10 minute timeout
                        log_func(f"📅 Long-dated contract ({days_to_expiry}d): 5% padding, 10m timeout")
                except Exception as e:
                    print(f"⚠️ Expiration parse error: {e}")

            # CRITICAL: Use trader's optimized tick rounding with round_up for buys
            padded_price = price * (1 + buy_padding)
            final_price = trader.round_to_tick(padded_price, symbol, round_up_for_buy=True, expiration=expiration)

            # Calculate contracts with per-channel minimum and MAX_CONTRACTS enforcement
            min_channel_contracts = config.get("min_trade_contracts", MIN_CONTRACTS)
            calculated_contracts = int(max_amount / (final_price * 100))
            contracts = max(min_channel_contracts, min(calculated_contracts, MAX_CONTRACTS))

            # LOTTO OVERRIDE: Force 1 contract for lotto-size trades
            if size == 'lotto':
                contracts = 1
                log_func(f"🎰 Lotto size detected: Forcing 1 contract (overrides channel minimum)")

            # Check minimum trade contracts threshold for channel (0 = tracking only)
            if min_channel_contracts == 0:
                log_func(f"📊 Channel {trade_obj.get('channel', 'Unknown')} tracking only: Trading disabled")
                trade_obj['quantity'] = 0
                trade_obj['price'] = final_price
                trade_obj['is_tracking_only'] = True

                # Get current market price for tracking purposes
                try:
                    market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
                    current_price = final_price
                    if market_data:
                        if isinstance(market_data, dict):
                            current_price = market_data.get('mark_price') or market_data.get('last_trade_price') or final_price
                        elif isinstance(market_data, list) and len(market_data) > 0:
                            data = market_data[0]
                            if isinstance(data, dict):
                                current_price = data.get('mark_price') or data.get('last_trade_price') or final_price
                    trade_obj['market_price_at_alert'] = float(current_price)
                    log_func(f"📊 Market price captured for tracking: ${float(current_price):.2f}")
                except Exception as e:
                    log_func(f"⚠️ Could not capture market price: {e}")
                    trade_obj['market_price_at_alert'] = final_price

                return False, f"Channel tracking only: Trading disabled (Market: ${float(trade_obj.get('market_price_at_alert', final_price)):.2f})"

            # Enforce channel minimum if higher than global minimum
            if contracts < min_channel_contracts:
                log_func(f"📈 Channel {trade_obj.get('channel', 'Unknown')}: Enforcing minimum {min_channel_contracts} contracts (calculated: {contracts})")
                contracts = min_channel_contracts

            # ENHANCED: Show size calculation details
            print(f"💰 SIZE CALCULATION BREAKDOWN:")
            print(f"   Portfolio Value: ${portfolio_value:,.2f}")
            print(f"   Max % Portfolio: {MAX_PCT_PORTFOLIO * 100}%")
            print(f"   Size Multiplier: {size_multiplier} ({size})")
            print(f"   Channel Multiplier: {channel_multiplier}")
            print(f"   Allocation: {allocation * 100:.2f}%")
            print(f"   Max Dollar Amount: ${max_amount:,.2f}")
            print(f"   Contract Price: ${final_price:.2f}")
            print(f"   Calculated Contracts: {calculated_contracts}")
            print(f"   Final Contracts: {contracts} (min: {MIN_CONTRACTS}, max: {MAX_CONTRACTS})")

            # Store for later use
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
                'calculated_contracts': calculated_contracts,
                'final_contracts': contracts,
                'min_contracts': MIN_CONTRACTS,
                'max_contracts': MAX_CONTRACTS
            }

            # ========== PRE-EXECUTION VALIDATION (CRITICAL SAFETY) ==========
            # max_price_cap = padded price. This is the HARD CAP — cascade never exceeds this.
            max_price_cap = final_price
            print(f"🔍 VALIDATING: {contracts}x {symbol} {strike}{opt_type} @ cap ${max_price_cap:.2f}")
            if not trader.validate_order_requirements(symbol, strike, expiration, opt_type, contracts, max_price_cap):
                log_func(f"❌ Order validation failed for {symbol} {strike}{opt_type}")
                return False, "Order validation failed"

            # ========== SIMULATED MODE (no cascade) ==========
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                start_time = time.time()
                buy_response = trader.place_option_buy_order(symbol, strike, expiration, opt_type, contracts, max_price_cap)
                execution_time = time.time() - start_time
                print(f"✅ SIMULATED buy executed in {execution_time:.3f}s")
                trade_obj['order_id'] = f"sim_{int(time.time() * 1000)}"
                trade_obj['position_status'] = 'open'
                return True, f"Simulated buy: {contracts}x {symbol}"

            # ========== LIVE: CASCADE BUY ==========
            print(f"⚡ CASCADE BUY: {contracts}x {symbol} {strike}{opt_type} | Cap: ${max_price_cap:.2f}")

            from config import BUY_CASCADE_STEPS
            # Create runtime config with potentially modified timeout for long-dated contracts
            run_config = config.copy()
            run_config['resting_order_timeout'] = resting_timeout

            cascade_success, order_id, fill_price, step_used = self._cascade_buy(
                trader, symbol, strike, expiration, opt_type, contracts,
                BUY_CASCADE_STEPS, run_config, log_func, max_price_cap
            )

            if not cascade_success:
                log_func(f"❌ Cascade buy failed for {symbol} {strike}{opt_type}")
                return False, f"Cascade buy failed: no fill within cap ${max_price_cap:.2f}"

            # Update trade_obj with ACTUAL fill price (not padded alert price)
            trade_obj['price'] = fill_price if fill_price else max_price_cap
            trade_obj['order_id'] = order_id
            trade_obj['position_status'] = 'opening'
            trade_obj['cascade_step'] = step_used

            # Create position in 'opening' status in the ledger with correct price
            if self.position_ledger:
                try:
                    ccid = self.position_ledger.create_opening_position(trade_obj, order_id)
                    trade_obj['ledger_ccid'] = ccid
                    print(f"📒 Position created in 'opening' status: {ccid}")
                except Exception as le:
                    print(f"⚠️ Ledger opening position creation failed (non-critical): {le}")

            return True, f"Cascade buy filled: {contracts}x {symbol} @ ${trade_obj['price']:.2f} (step {step_used}, cap ${max_price_cap:.2f})"

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
            
            # Check minimum trade contracts threshold for channel (for tracking mode)
            min_contracts = config.get("min_trade_contracts", 1)
            if min_contracts == 0:
                log_func(f"📊 Channel {trade_obj.get('channel', 'Unknown')} tracking only: Processing {action} for monitoring")
                # Still get market data for tracking purposes but don't execute
                trade_obj['is_tracking_only'] = True
                try:
                    # Initialize with fallback price to ensure key always exists
                    trade_obj['market_price_at_alert'] = 0.05
                    
                    # Debug: Log the parameters being used for market data fetch
                    log_func(f"🔍 Fetching market data: {symbol} ${strike} {opt_type} {expiration}")
                    
                    market_data = trader.get_option_market_data(symbol, expiration, strike, opt_type)
                    log_func(f"🔍 Market data response: {market_data}")
                    
                    if market_data and len(market_data) > 0:
                        data = self._normalize_market_data(market_data)
                        if isinstance(data, dict):
                            mark_price = data.get('mark_price')
                            if mark_price and float(mark_price) > 0:
                                trade_obj['market_price_at_alert'] = float(mark_price)
                            else:
                                bid = float(data.get('bid_price', 0) or 0)
                                ask = float(data.get('ask_price', 0) or 0)
                                if bid > 0 and ask > 0:
                                    trade_obj['market_price_at_alert'] = (bid + ask) / 2
                                elif bid > 0:
                                    trade_obj['market_price_at_alert'] = bid
                                # else: keep fallback 0.05
                    
                    log_func(f"📊 Market price captured for {action} tracking: ${float(trade_obj.get('market_price_at_alert', 0)):.2f}")
                except Exception as e:
                    log_func(f"⚠️ Could not capture market price for {action}: {e}")
                    trade_obj['market_price_at_alert'] = 0.05
                
                # Apply padding for realistic tracking price
                sell_padding = config.get("sell_padding", DEFAULT_SELL_PRICE_PADDING)
                padded_price = trade_obj['market_price_at_alert'] * (1 - sell_padding)
                trade_obj['price'] = trader.round_to_tick(padded_price, symbol, round_up_for_buy=False, expiration=expiration)
                
                return False, f"Channel tracking only: {action} at ${trade_obj['price']:.2f} (Market: ${float(trade_obj.get('market_price_at_alert', 0)):.2f})"
            
            # PRE-CANCEL existing orders FIRST (handles "abort buy" scenario)
            # Must happen BEFORE position check - if buy hasn't filled, cancel it
            print(f"🚫 Cancelling existing orders for {symbol}...")
            cancelled_count = 0
            try:
                cancelled_count = trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
                if cancelled_count > 0:
                    print(f"✅ Cancelled {cancelled_count} existing orders")
            except Exception as e:
                print(f"⚠️ Order cancellation failed (proceeding anyway): {e}")

            # PRE-CALCULATE position quantity (for real trading mode)
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                total_quantity = 10
            else:
                # SPEED OPTIMIZATION: Get positions once
                all_positions = trader.get_open_option_positions()
                position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
                if not position:
                    # If we cancelled pending orders, that's a success (aborted buy)
                    if cancelled_count > 0:
                        log_func(f"✅ Cancelled {cancelled_count} pending buy orders (no position to {action})")
                        return True, f"Cancelled {cancelled_count} pending orders"
                    print(f"❌ No position found for {symbol}")
                    return False, "No position found"
                total_quantity = int(float(position.get('quantity', 0)))

            # Determine quantity - use TRIM_PERCENTAGE for trims (25% by default)
            if action == "trim":
                sell_quantity = max(1, int(total_quantity * TRIM_PERCENTAGE))
            else:
                sell_quantity = total_quantity
            trade_obj['quantity'] = sell_quantity
            
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
                        data = self._normalize_market_data(market_data)
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
            
            # OPTIMIZED: Apply padding and use trader's enhanced rounding (include expiration for SPX 0DTE detection)
            padded_price = market_price * (1 - sell_padding)
            final_price = trader.round_to_tick(padded_price, symbol, round_up_for_buy=False, expiration=expiration)
            trade_obj['price'] = final_price
            
            # ========== PRE-EXECUTION VALIDATION (SAFETY CHECK) ==========
            if final_price <= 0:
                log_func(f"❌ Invalid price for {action}: ${final_price:.2f}")
                return False, f"Invalid {action} price: ${final_price:.2f}"
            
            if sell_quantity <= 0:
                log_func(f"❌ Invalid quantity for {action}: {sell_quantity}")
                return False, f"Invalid {action} quantity: {sell_quantity}"
            
            print(f"⚡ ENHANCED {action.upper()}: {sell_quantity}x {symbol} @ ${final_price:.2f}")

            # ========== CASCADE SELL MECHANISM ==========
            start_time = time.time()

            # Check for simulated mode first
            if hasattr(trader, 'simulated_orders') or trader.__class__.__name__ == 'EnhancedSimulatedTrader':
                print(f"✅ SIMULATED {action} executed")
                trade_obj['trim_confirmed'] = True
                return True, f"Simulated {action}: {sell_quantity}x {symbol}"

            # Select cascade steps based on action type
            # Trims are patient (60s waits), exits are urgent (30s waits)
            cascade_steps = TRIM_CASCADE_STEPS if action == "trim" else EXIT_CASCADE_STEPS

            print(f"🔄 Using {'TRIM' if action == 'trim' else 'EXIT'} cascade ({len(cascade_steps)} steps)")

            # Execute cascade sell
            success, order_id, fill_price, step_used = self._cascade_sell(
                trader, symbol, strike, expiration, opt_type,
                sell_quantity, cascade_steps, config, log_func
            )

            execution_time = time.time() - start_time

            if success:
                print(f"✅ {action.upper()} CASCADE SUCCESS in {execution_time:.1f}s (step {step_used}, ${fill_price:.2f})")

                # Update trade_obj with actual fill price
                if fill_price:
                    trade_obj['price'] = fill_price
                    trade_obj['fill_price'] = fill_price

                # For trims, mark as confirmed for break-even stop
                if action == "trim":
                    trade_obj['trim_confirmed'] = True
                    trade_obj['trim_fill_time'] = execution_time

                return True, f"{action.title()}: {sell_quantity}x {symbol} @ ${fill_price:.2f} (step {step_used})"
            else:
                print(f"❌ {action.upper()} CASCADE FAILED after {execution_time:.1f}s")
                trade_obj['trim_confirmed'] = False
                trade_obj['skip_stop_loss'] = True
                return False, f"{action.title()} failed: Cascade exhausted"
                
        except Exception as e:
            print(f"❌ CRITICAL {action} execution error: {e}")
            log_func(f"❌ {action.title()} execution error: {e}")
            return False, str(e)

    def _handle_trailing_stop(self, trader, trade_obj, config, active_position, log_func, is_sim_mode):
        """
        ENHANCED: Handle stop loss logic after trim/exit.

        After TRIM: Place break-even stop at entry price to protect remaining contracts.
        After EXIT: No stop needed (position closed).

        Break-even stop after trim:
        - Locks in the win from the trim
        - Remaining contracts are protected from loss
        - Entry price becomes the floor for the position
        """
        try:
            if not active_position:
                return

            action = trade_obj.get('action', 'trim')

            # Only place stops after trim (exit = full position closed)
            if action != 'trim':
                return

            # Check if trim was confirmed before placing stop loss
            if trade_obj.get('skip_stop_loss'):
                print(f"⚠️ Skipping stop loss due to unconfirmed trim order")
                log_func(f"⚠️ Stop loss skipped - trim order not confirmed")
                return

            if not trade_obj.get('trim_confirmed', True):
                print(f"⚠️ Trim not confirmed, delaying stop loss...")
                log_func(f"⚠️ Stop loss delayed - waiting for trim confirmation")
                return

            symbol = trade_obj['ticker']
            strike = trade_obj['strike']
            expiration = trade_obj['expiration']
            opt_type = trade_obj['type']

            if is_sim_mode or hasattr(trader, 'simulated_orders'):
                log_func(f"📊 [SIMULATED] Would place break-even stop for remaining position")
                return

            all_positions = trader.get_open_option_positions()
            remaining_position = trader.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)

            if remaining_position:
                remaining_qty = int(float(remaining_position.get('quantity', 0)))
                entry_price = float(active_position.get("purchase_price", 0.0) or active_position.get("entry_price", 0.0))

                if entry_price <= 0:
                    log_func(f"⚠️ Cannot set break-even stop: no entry price found")
                    return

                # BREAK-EVEN STOP: Set stop at entry price after successful trim
                # This protects remaining contracts from any loss
                stop_price = trader.round_to_tick(entry_price, symbol, round_up_for_buy=False, expiration=expiration)

                print(f"🛡️ BREAK-EVEN STOP: Setting stop @ ${stop_price:.2f} (entry price) for {remaining_qty} remaining contracts")
                log_func(f"🛡️ Break-even stop: {remaining_qty}x @ ${stop_price:.2f}")

                try:
                    # Cancel any existing stop orders first
                    try:
                        trader.cancel_open_option_orders(symbol, strike, expiration, opt_type)
                        print(f"   ✅ Cancelled existing orders")
                    except Exception:
                        pass

                    # Place break-even stop order
                    stop_response = trader.place_option_stop_loss_order(
                        symbol, strike, expiration, opt_type, remaining_qty, stop_price
                    )

                    if stop_response and not stop_response.get('error'):
                        order_id = stop_response.get('id', 'unknown')
                        print(f"   ✅ Break-even stop placed: {order_id}")
                        log_func(f"✅ Break-even stop placed @ ${stop_price:.2f}")

                        # Update position status to 'trimmed' in ledger
                        if self.position_ledger:
                            try:
                                ccid = active_position.get('ledger_ccid') or active_position.get('ccid')
                                if ccid:
                                    self.position_ledger.transition_to_trimmed(ccid)
                                    print(f"   📒 Position status updated to 'trimmed'")
                            except Exception as le:
                                print(f"   ⚠️ Ledger update failed: {le}")
                    else:
                        log_func(f"❌ Failed to place break-even stop: {stop_response}")

                except Exception as e:
                    log_func(f"❌ Break-even stop error: {e}")

        except Exception as e:
            log_func(f"❌ Stop loss error: {e}")

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
**Final:** {calc['final_contracts']} (min: {calc['min_contracts']})
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