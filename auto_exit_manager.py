# auto_exit_manager.py — Automated tiered profit-taking + stop-loss for Ryan 0DTE SPX
#
# After a buy fill, places Tier 1 (+25%) and Tier 2 (+50%) limit sells.
# Monitors price every 3s: if bid drops below -25% stop, cancels limits and dumps.
# If Tier 1 fills, moves stop to break-even (entry price).

import asyncio
import logging
import time
from datetime import datetime, timezone

from config import AUTO_EXIT_CONFIG, ALL_NOTIFICATION_WEBHOOK, LIVE_FEED_WEBHOOK

logger = logging.getLogger('auto_exit_manager')


class AutoExitManager:
    """Manages automated tiered exit strategies for 0DTE SPX positions."""

    def __init__(self, trader, position_ledger, alert_manager=None, event_loop=None):
        self.trader = trader
        self.ledger = position_ledger
        self.alert_manager = alert_manager
        self.event_loop = event_loop

    # ------------------------------------------------------------------
    # SETUP: called immediately after buy fill (from trade_executor)
    # ------------------------------------------------------------------

    def setup_strategy(self, ccid, entry_price, quantity, symbol, strike, expiration, opt_type):
        """
        Calculate targets, place limit sell orders, save strategy to DB.

        Returns True on success, False on failure.
        """
        try:
            tier1_pct = AUTO_EXIT_CONFIG['tier1_profit_pct']
            tier2_pct = AUTO_EXIT_CONFIG['tier2_profit_pct']
            stop_pct = AUTO_EXIT_CONFIG['stop_loss_pct']

            # Calculate tick-compliant targets
            tier1_target = self.trader.round_to_tick(
                entry_price * (1 + tier1_pct), symbol,
                round_up_for_buy=False, expiration=expiration
            )
            tier2_target = self.trader.round_to_tick(
                entry_price * (1 + tier2_pct), symbol,
                round_up_for_buy=False, expiration=expiration
            )
            stop_price = self.trader.round_to_tick(
                entry_price * (1 - stop_pct), symbol,
                round_up_for_buy=False, expiration=expiration
            )

            # Split quantity
            if quantity <= 1:
                # Single contract: one sell at +25%
                single_pct = AUTO_EXIT_CONFIG.get('single_contract_target_pct', tier1_pct)
                tier1_target = self.trader.round_to_tick(
                    entry_price * (1 + single_pct), symbol,
                    round_up_for_buy=False, expiration=expiration
                )
                tier1_qty = 1
                tier2_qty = 0
            else:
                tier1_qty = quantity // 2
                tier2_qty = quantity - tier1_qty

            logger.info(
                f"Setting up auto-exit for {ccid}: entry=${entry_price:.2f} "
                f"T1=${tier1_target:.2f}x{tier1_qty} T2=${tier2_target:.2f}x{tier2_qty} "
                f"Stop=${stop_price:.2f}"
            )
            print(
                f"🎯 Auto-exit setup: {symbol} entry=${entry_price:.2f} | "
                f"T1=+{tier1_pct*100:.0f}%=${tier1_target:.2f}x{tier1_qty} | "
                f"T2=+{tier2_pct*100:.0f}%=${tier2_target:.2f}x{tier2_qty} | "
                f"Stop=-{stop_pct*100:.0f}%=${stop_price:.2f}"
            )

            # Place limit sell orders (exact_price bypasses market data fetch)
            tier1_order_id = None
            tier2_order_id = None

            if tier1_qty > 0:
                res = self.trader.place_option_sell_order(
                    symbol, strike, expiration, opt_type,
                    tier1_qty, tier1_target, exact_price=True
                )
                if res and res.get('id') and not res.get('error'):
                    tier1_order_id = res['id']
                    print(f"✅ Tier 1 sell placed: {tier1_order_id} @ ${tier1_target:.2f} x{tier1_qty}")
                else:
                    error = res.get('error', res) if res else 'No response'
                    logger.error(f"Tier 1 sell failed: {error}")
                    print(f"❌ Tier 1 sell failed: {error}")

            if tier2_qty > 0:
                res = self.trader.place_option_sell_order(
                    symbol, strike, expiration, opt_type,
                    tier2_qty, tier2_target, exact_price=True
                )
                if res and res.get('id') and not res.get('error'):
                    tier2_order_id = res['id']
                    print(f"✅ Tier 2 sell placed: {tier2_order_id} @ ${tier2_target:.2f} x{tier2_qty}")
                else:
                    error = res.get('error', res) if res else 'No response'
                    logger.error(f"Tier 2 sell failed: {error}")
                    print(f"❌ Tier 2 sell failed: {error}")

            # Need at least one order placed
            if not tier1_order_id and not tier2_order_id:
                logger.error(f"Auto-exit setup failed: no orders placed for {ccid}")
                print(f"❌ Auto-exit setup FAILED: no orders placed")
                return False

            # Save to DB
            self.ledger.save_auto_exit_strategy({
                'ccid': ccid,
                'entry_price': entry_price,
                'tier1_target': tier1_target,
                'tier2_target': tier2_target,
                'stop_price': stop_price,
                'tier1_qty': tier1_qty,
                'tier2_qty': tier2_qty,
                'tier1_order_id': tier1_order_id,
                'tier2_order_id': tier2_order_id,
            })

            print(f"🛡️ Auto-exit ACTIVE for {ccid}")
            return True

        except Exception as e:
            logger.error(f"Auto-exit setup error for {ccid}: {e}", exc_info=True)
            print(f"❌ Auto-exit setup exception: {e}")
            return False

    # ------------------------------------------------------------------
    # MONITOR: called every 3s from main.py async loop (via run_in_executor)
    # ------------------------------------------------------------------

    def check_strategies(self):
        """
        Check all active strategies for stop triggers and tier fills.
        This is a BLOCKING call (sync) — run in executor from async context.
        """
        try:
            strategies = self.ledger.get_active_auto_exit_strategies()
            if not strategies:
                return

            for strat in strategies:
                try:
                    self._check_single_strategy(strat)
                except Exception as e:
                    logger.error(f"Error checking strategy {strat['ccid']}: {e}")

        except Exception as e:
            logger.error(f"check_strategies error: {e}")

    def _check_single_strategy(self, strat):
        """Check one strategy: stop condition, tier fills."""
        ccid = strat['ccid']
        symbol = strat['ticker']
        expiration = strat['expiration']
        strike = strat['strike']
        opt_type = strat['option_type']

        # 1. Fetch current market data (1 API call)
        market_data = self.trader.get_option_market_data(symbol, expiration, strike, opt_type)
        bid_price = self._extract_bid(market_data)

        if bid_price <= 0:
            return  # No valid data, skip this cycle

        # 2. Stop-loss check (highest priority, subject to grace period)
        if bid_price < strat['stop_price']:
            # Grace period: don't trigger stop until delay has elapsed
            stop_delay = AUTO_EXIT_CONFIG.get('stop_loss_delay_seconds', 300)
            try:
                created = datetime.fromisoformat(strat['created_at'])
                elapsed = (datetime.now() - created).total_seconds()
            except (ValueError, KeyError):
                elapsed = stop_delay + 1  # If can't parse, assume grace is over

            if elapsed < stop_delay:
                remaining = int(stop_delay - elapsed)
                logger.debug(f"Stop triggered but in grace period for {ccid} ({remaining}s left)")
                # Don't exit yet — still in grace period
            else:
                logger.warning(
                    f"🚨 STOP TRIGGERED {ccid}: bid=${bid_price:.2f} < stop=${strat['stop_price']:.2f}"
                )
                print(f"🚨 STOP LOSS TRIGGERED: {symbol} bid=${bid_price:.2f} < stop=${strat['stop_price']:.2f}")
                self.execute_stop_loss(strat, bid_price)
                return

        # 3. Check Tier 1 fill
        if strat['status'] == 'active' and strat.get('tier1_order_id'):
            t1_info = self.trader.get_option_order_info(strat['tier1_order_id'])
            if t1_info and t1_info.get('state', '').lower() == 'filled':
                logger.info(f"✅ Tier 1 FILLED for {ccid} — moving stop to break-even")
                print(f"✅ Tier 1 HIT for {symbol}! Stop → break-even (${strat['entry_price']:.2f})")

                # Move stop to entry price (break-even)
                new_stop = strat['entry_price']
                self.ledger.update_auto_exit_status(ccid, 'tier1_filled', stop_price=new_stop)

                # Record the tier 1 sell in ledger
                try:
                    self.ledger.record_sell(ccid, strat['tier1_qty'], strat['tier1_target'])
                except Exception as e:
                    logger.error(f"Ledger record_sell for T1 failed: {e}")

                # Update strat dict for subsequent checks this cycle
                strat['status'] = 'tier1_filled'
                strat['stop_price'] = new_stop

        # 4. Check Tier 2 fill
        if strat.get('tier2_order_id') and strat['tier2_qty'] > 0:
            t2_info = self.trader.get_option_order_info(strat['tier2_order_id'])
            if t2_info and t2_info.get('state', '').lower() == 'filled':
                # Check if tier 1 is also done (filled or qty=0)
                t1_done = (strat['status'] == 'tier1_filled' or strat['tier1_qty'] == 0)
                if t1_done:
                    logger.info(f"✅ All targets HIT for {ccid} — strategy complete")
                    print(f"✅ All targets HIT for {symbol}! Position fully closed.")
                    self.ledger.update_auto_exit_status(ccid, 'completed')

                    # Record the tier 2 sell in ledger
                    try:
                        self.ledger.record_sell(ccid, strat['tier2_qty'], strat['tier2_target'])
                    except Exception as e:
                        logger.error(f"Ledger record_sell for T2 failed: {e}")

        # 5. Handle single-contract case: tier1 only, no tier2
        if strat['tier2_qty'] == 0 and strat.get('tier1_order_id'):
            t1_info = self.trader.get_option_order_info(strat['tier1_order_id'])
            if t1_info and t1_info.get('state', '').lower() == 'filled':
                if strat['status'] != 'completed':
                    logger.info(f"✅ Single-contract target HIT for {ccid}")
                    print(f"✅ Target HIT for {symbol}! Single contract closed.")
                    self.ledger.update_auto_exit_status(ccid, 'completed')
                    try:
                        self.ledger.record_sell(ccid, strat['tier1_qty'], strat['tier1_target'])
                    except Exception as e:
                        logger.error(f"Ledger record_sell for single T1 failed: {e}")

    # ------------------------------------------------------------------
    # STOP LOSS: cancel limits and dump remaining position
    # ------------------------------------------------------------------

    def execute_stop_loss(self, strat, current_bid):
        """Cancel all limit orders and aggressively exit remaining position."""
        ccid = strat['ccid']
        symbol = strat['ticker']
        strike = strat['strike']
        expiration = strat['expiration']
        opt_type = strat['option_type']

        logger.info(f"Executing stop loss for {ccid}")

        # 1. Cancel outstanding limit orders
        for order_key in ('tier1_order_id', 'tier2_order_id'):
            order_id = strat.get(order_key)
            if order_id:
                try:
                    info = self.trader.get_option_order_info(order_id)
                    if info and info.get('state', '').lower() not in ('filled', 'cancelled', 'rejected', 'failed'):
                        self.trader.cancel_option_order(order_id)
                        print(f"🗑️ Cancelled {order_key}: {order_id}")
                except Exception as e:
                    logger.error(f"Cancel {order_key} failed: {e}")

        # Small delay for Robinhood to process cancellations
        time.sleep(1)

        # 2. Get actual remaining quantity from Robinhood (handles race conditions)
        remaining_qty = 0
        try:
            all_pos = self.trader.get_open_option_positions()
            rh_pos = self.trader.find_open_option_position(
                all_pos, symbol, strike, expiration, opt_type
            )
            if rh_pos:
                remaining_qty = int(float(rh_pos.get('quantity', 0)))
        except Exception as e:
            logger.error(f"Failed to get remaining qty: {e}")
            # Fallback: estimate from strategy
            remaining_qty = strat['tier1_qty'] + strat['tier2_qty']

        if remaining_qty <= 0:
            logger.info(f"No remaining position for {ccid} — already closed by tier fills")
            print(f"ℹ️ No remaining position for {symbol} — tier fills closed it")
            self.ledger.update_auto_exit_status(ccid, 'stopped_out')
            return

        # 3. Aggressive exit at bid x 0.90
        discount = AUTO_EXIT_CONFIG.get('aggressive_exit_discount', 0.10)
        aggressive_price = self.trader.round_to_tick(
            current_bid * (1 - discount), symbol,
            round_up_for_buy=False, expiration=expiration
        )
        # Floor at minimum tick
        if aggressive_price <= 0:
            aggressive_price = 0.05

        print(f"🚨 STOP EXIT: {symbol} x{remaining_qty} @ ${aggressive_price:.2f} (bid=${current_bid:.2f})")

        res = self.trader.place_option_sell_order(
            symbol, strike, expiration, opt_type,
            remaining_qty, aggressive_price, exact_price=True
        )

        if res and res.get('id') and not res.get('error'):
            print(f"✅ Stop exit order placed: {res['id']}")
            logger.info(f"Stop exit placed for {ccid}: {res['id']} @ ${aggressive_price:.2f}")

            # 4. Send stop-loss alert to live feed
            self._send_stop_loss_alert(
                symbol=symbol,
                entry_price=strat['entry_price'],
                stop_price=strat['stop_price'],
                current_bid=current_bid,
                quantity=remaining_qty,
                exit_price=aggressive_price
            )
        else:
            error = res.get('error', res) if res else 'No response'
            logger.error(f"Stop exit order failed: {error}")
            print(f"❌ Stop exit FAILED: {error}")

        # 5. Update DB
        self.ledger.update_auto_exit_status(ccid, 'stopped_out')

        # 6. Record sell in ledger
        try:
            self.ledger.record_sell(ccid, remaining_qty, aggressive_price)
        except Exception as e:
            logger.error(f"Ledger record_sell for stop failed: {e}")

    # ------------------------------------------------------------------
    # CANCEL: called on manual EXIT override from Ryan
    # ------------------------------------------------------------------

    def cancel_strategy(self, ccid):
        """Cancel all limit orders for a strategy (manual EXIT override)."""
        strat = self.ledger.get_auto_exit_strategy(ccid)
        if not strat or strat['status'] not in ('active', 'tier1_filled'):
            return

        logger.info(f"Cancelling auto-exit for {ccid} — manual override")
        print(f"🔄 Cancelling auto-exit for {ccid}")

        for order_key in ('tier1_order_id', 'tier2_order_id'):
            order_id = strat.get(order_key)
            if order_id:
                try:
                    info = self.trader.get_option_order_info(order_id)
                    if info and info.get('state', '').lower() not in ('filled', 'cancelled', 'rejected', 'failed'):
                        self.trader.cancel_option_order(order_id)
                        print(f"🗑️ Cancelled {order_key}: {order_id}")
                except Exception as e:
                    logger.error(f"Cancel {order_key} during override failed: {e}")

        self.ledger.update_auto_exit_status(ccid, 'cancelled')

    # ------------------------------------------------------------------
    # QUERY
    # ------------------------------------------------------------------

    def has_active_strategy(self, ccid):
        """Check if a position has an active auto-exit strategy."""
        return self.ledger.has_active_auto_exit(ccid)

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _send_stop_loss_alert(self, symbol, entry_price, stop_price, current_bid, quantity, exit_price):
        """Send stop-loss triggered alert to live feed (thread-safe for blocking context)."""
        try:
            if not self.alert_manager or not self.event_loop:
                logger.warning("Cannot send stop-loss alert: alert_manager or event_loop not set")
                return

            loss_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            loss_amount = (exit_price - entry_price) * quantity * 100  # Options are 100 shares

            stop_embed = {
                "title": "🚨 STOP LOSS TRIGGERED",
                "description": f"Ryan 0DTE position automatically closed due to stop loss.",
                "color": 0xFF0000,  # Red
                "fields": [
                    {
                        "name": "📈 Symbol",
                        "value": symbol,
                        "inline": True
                    },
                    {
                        "name": "📊 Quantity",
                        "value": f"{quantity} contracts",
                        "inline": True
                    },
                    {
                        "name": "💵 Entry Price",
                        "value": f"${entry_price:.2f}",
                        "inline": True
                    },
                    {
                        "name": "🛑 Stop Price",
                        "value": f"${stop_price:.2f}",
                        "inline": True
                    },
                    {
                        "name": "📉 Current Bid",
                        "value": f"${current_bid:.2f}",
                        "inline": True
                    },
                    {
                        "name": "💸 Exit Price",
                        "value": f"${exit_price:.2f}",
                        "inline": True
                    },
                    {
                        "name": "📊 Loss",
                        "value": f"{loss_pct:.1f}% (${loss_amount:.2f})",
                        "inline": False
                    }
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Auto-Exit Manager • Ryan 0DTE SPX"}
            }

            asyncio.run_coroutine_threadsafe(
                self.alert_manager.add_alert(
                    LIVE_FEED_WEBHOOK,
                    {"embeds": [stop_embed]},
                    "stop_loss_alert",
                    priority=2  # High priority
                ),
                self.event_loop
            )

            logger.info(f"Stop-loss alert sent for {symbol}")

        except Exception as e:
            logger.error(f"Failed to send stop-loss alert: {e}")

    def _extract_bid(self, market_data):
        """Extract bid price from market data (handles nested arrays)."""
        try:
            if not market_data or len(market_data) == 0:
                return 0.0

            data = market_data[0]
            if isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    data = data[0]
                else:
                    return 0.0

            if isinstance(data, dict):
                bid = float(data.get('bid_price', 0) or 0)
                return bid

            return 0.0
        except (IndexError, TypeError, ValueError):
            return 0.0
