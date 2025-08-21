# trader.py - Enhanced with Market Price Default for Trim/Exit
import os
import uuid
import robin_stocks.robinhood as r
from dotenv import load_dotenv
from config import DEFAULT_SELL_PRICE_PADDING  # Changed from SELL_PRICE_PADDING
import time

load_dotenv()
ROBINHOOD_USER = os.getenv("ROBINHOOD_USER")
ROBINHOOD_PASS = os.getenv("ROBINHOOD_PASS")

class RobinhoodTrader:
    def __init__(self):
        self.logged_in = False
        self.login()

    def login(self):
        """Simple login without 2FA requirements"""
        try:
            print("🔐 Attempting Robinhood login...")
            
            # Simple login without 2FA
            login_result = r.login(
                username=ROBINHOOD_USER, 
                password=ROBINHOOD_PASS, 
                expiresIn=31536000,  # 1 year
                store_session=True
            )
            
            if login_result:
                self.logged_in = True
                print("✅ Robinhood login successful.")
                
                # Verify account access
                try:
                    account_info = r.load_account_profile()
                    if account_info:
                        print(f"📊 Account verified: {account_info.get('account_number', 'N/A')}")
                    else:
                        print("⚠️ Login successful but couldn't verify account access")
                except:
                    print("⚠️ Login successful but account verification failed")
                    
            else:
                print("❌ Robinhood login failed - check credentials")
                self.logged_in = False
                
        except Exception as e:
            error_msg = str(e).lower()
            if "challenge" in error_msg or "mfa" in error_msg or "two" in error_msg:
                print("❌ 2FA/Challenge required but not supported in this version")
                print("💡 Please disable 2FA on your Robinhood account or use app passwords")
            else:
                print(f"❌ Robinhood login failed: {e}")
            self.logged_in = False

    def reconnect(self):
        """Force reconnection to Robinhood"""
        print("⚙️ Attempting to reconnect to Robinhood...")
        try:
            # Clear any existing session
            r.logout()
            time.sleep(1)
            
            # Attempt fresh login
            self.login()
            
        except Exception as e:
            print(f"❌ Failed to reconnect to Robinhood: {e}")
            self.logged_in = False

    def check_connection(self):
        """Verify connection is still active"""
        try:
            account = r.load_account_profile()
            return account is not None
        except:
            return False

    def get_portfolio_value(self) -> float:
        """Get current portfolio value with error handling"""
        try:
            if not self.logged_in:
                print("❌ Not logged in to Robinhood")
                return 0.0
                
            if not self.check_connection():
                print("⚠️ Connection lost, attempting reconnect...")
                self.reconnect()
            
            profile = r.load_portfolio_profile()
            if profile and 'equity' in profile:
                equity = float(profile['equity'])
                print(f"💰 Current portfolio value: ${equity:,.2f}")
                return equity
            else:
                print("❌ Could not fetch portfolio value")
                return 0.0
                
        except Exception as e:
            print(f"❌ Error fetching portfolio value: {e}")
            return 0.0

    def get_buying_power(self) -> float:
        """Get available buying power"""
        try:
            if not self.logged_in:
                return 0.0
                
            account = r.load_account_profile()
            if account:
                buying_power = float(account.get('buying_power', 0))
                print(f"💵 Available buying power: ${buying_power:,.2f}")
                return buying_power
            return 0.0
        except Exception as e:
            print(f"❌ Error fetching buying power: {e}")
            return 0.0

    def validate_order_requirements(self, symbol, strike, expiration, opt_type, quantity, price):
        """Validate order before placing"""
        try:
            if not self.logged_in:
                raise Exception("Not logged in to Robinhood")
                
            # Check buying power
            required_capital = price * quantity * 100
            available_power = self.get_buying_power()
            
            if required_capital > available_power:
                raise Exception(f"Insufficient buying power: ${required_capital:,.2f} required, ${available_power:,.2f} available")
            
            # Check market hours (basic check)
            from datetime import datetime, time as dt_time
            now = datetime.now()
            market_open = dt_time(9, 30)  # 9:30 AM
            market_close = dt_time(16, 0)  # 4:00 PM
            current_time = now.time()
            
            if not (market_open <= current_time <= market_close):
                print(f"⚠️ Warning: Placing order outside market hours ({current_time})")
            
            return True
            
        except Exception as e:
            print(f"❌ Order validation failed: {e}")
            return False

    def get_instrument_tick_size(self, symbol: str) -> float | None:
        """Enhanced tick size detection with fallbacks"""
        try:
            if not self.logged_in:
                return None
                
            # Try to get tick size from instrument data
            instruments = r.get_instruments_by_symbols(symbol)
            if instruments and instruments[0] and instruments[0].get('min_tick_size'):
                tick_size = float(instruments[0]['min_tick_size'])
                print(f"📏 Tick size for {symbol}: ${tick_size}")
                return tick_size
                
        except Exception as e:
            print(f"❌ Could not fetch tick size for {symbol}: {e}")
        
        # Enhanced fallbacks based on common patterns
        try:
            # Get current market data to determine appropriate tick size
            sample_data = r.get_quotes(symbol)
            if sample_data and sample_data[0]:
                price = float(sample_data[0].get('last_trade_price', 1.0))
                
                # Use standard options tick size rules
                if price < 3.00:
                    return 0.05  # $0.05 for options under $3
                else:
                    return 0.10  # $0.10 for options $3 and above
                    
        except Exception as e:
            print(f"❌ Could not determine tick size from market data: {e}")
        
        # Final fallback
        print(f"⚠️ Using default tick size for {symbol}: $0.05")
        return 0.05

    def round_to_tick(self, price: float, symbol: str) -> float:
        """Round price to the nearest valid tick size for the symbol"""
        try:
            tick_size = self.get_instrument_tick_size(symbol)
            if tick_size is None or tick_size == 0:
                tick_size = 0.05  # Default fallback
            
            rounded_price = round(round(price / tick_size) * tick_size, 2)
            
            if rounded_price != price:
                print(f"📏 Rounded price from ${price:.2f} to ${rounded_price:.2f} (tick: ${tick_size})")
            
            return rounded_price
            
        except Exception as e:
            print(f"❌ Error rounding price: {e}")
            return round(price, 2)  # Default rounding

    def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
        """Enhanced buy order with validation and tick rounding"""
        try:
            if not self.logged_in:
                return {"error": "Not logged in to Robinhood"}
            
            # Round to proper tick size
            rounded_price = self.round_to_tick(limit_price, symbol)
            
            print(f"🔍 Validating buy order: {symbol} {strike}{opt_type[0].upper()} x{quantity} @ ${rounded_price:.2f}")
            
            # Validate order requirements
            if not self.validate_order_requirements(symbol, strike, expiration, opt_type, quantity, rounded_price):
                return {"error": "Order validation failed"}
            
            # Place the order
            print(f"📤 Placing LIVE buy order...")
            result = r.order_buy_option_limit(
                positionEffect='open', 
                creditOrDebit='debit', 
                price=rounded_price,
                symbol=symbol, 
                quantity=quantity, 
                expirationDate=expiration,
                strike=strike, 
                optionType=opt_type, 
                timeInForce='gfd'
            )
            
            if result and result.get('id'):
                print(f"✅ LIVE buy order placed: {result['id']}")
            else:
                print(f"❌ Buy order failed: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Error placing buy order: {e}")
            return {"error": str(e)}

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        """Enhanced sell order that ALWAYS uses market price with smart fallbacks"""
        try:
            if not self.logged_in:
                return {"error": "Not logged in to Robinhood"}
            
            # Use provided padding or default
            if sell_padding is None:
                sell_padding = DEFAULT_SELL_PRICE_PADDING
            
            # ALWAYS get current market price (ignore any provided limit_price)
            print(f"📊 Fetching current market price for {symbol} {strike}{opt_type[0].upper()}...")
            market_data_list = self.get_option_market_data(symbol, expiration, strike, opt_type)
            
            final_price = None
            price_source = "unknown"
            
            if market_data_list and len(market_data_list) > 0 and isinstance(market_data_list[0], dict):
                rec = market_data_list[0]
                
                # Priority 1: Mark price (most accurate)
                mark_price = rec.get('mark_price')
                if mark_price and float(mark_price) > 0:
                    final_price = float(mark_price)
                    price_source = "mark"
                    print(f"✅ Using mark price: ${final_price:.2f}")
                else:
                    bid_price = float(rec.get('bid_price', 0) or 0)
                    ask_price = float(rec.get('ask_price', 0) or 0)
                    
                    # Priority 2: Bid/Ask midpoint
                    if bid_price > 0 and ask_price > 0:
                        final_price = (bid_price + ask_price) / 2
                        price_source = "midpoint"
                        print(f"✅ Using bid/ask midpoint: ${final_price:.2f} (bid: ${bid_price:.2f}, ask: ${ask_price:.2f})")
                    # Priority 3: Bid only
                    elif bid_price > 0:
                        final_price = bid_price
                        price_source = "bid"
                        print(f"✅ Using bid price: ${final_price:.2f}")
                    # Priority 4: Discounted ask
                    elif ask_price > 0:
                        final_price = ask_price * 0.95  # 5% below ask to ensure fill
                        price_source = "discounted_ask"
                        print(f"✅ Using discounted ask: ${final_price:.2f} (ask: ${ask_price:.2f})")
            
            # Priority 5: Emergency fallback
            if not final_price or final_price <= 0:
                # Try to use any provided price as last resort
                if limit_price and limit_price > 0:
                    final_price = limit_price * 0.8  # 20% discount for emergency exit
                    price_source = "emergency_provided"
                    print(f"⚠️ Using emergency price based on provided: ${final_price:.2f}")
                else:
                    final_price = 0.01  # Absolute minimum to get out
                    price_source = "emergency_minimum"
                    print(f"🚨 No market data available! Using minimum price: ${final_price:.2f}")
            
            # Apply padding for better fill probability
            sell_price = final_price * (1 - sell_padding)
            
            # Round to tick size
            sell_price = self.round_to_tick(sell_price, symbol)
            
            print(f"📤 Placing LIVE sell order: {symbol} {strike}{opt_type[0].upper()} x{quantity} @ ${sell_price:.2f} (source: {price_source}, padding: {sell_padding*100:.1f}%)")
            
            result = r.order_sell_option_limit(
                positionEffect='close', 
                creditOrDebit='credit', 
                price=sell_price,
                symbol=symbol, 
                quantity=quantity, 
                expirationDate=expiration, 
                strike=strike, 
                optionType=opt_type, 
                timeInForce='gtc'  # Good till cancelled for sells
            )
            
            if result and result.get('id'):
                print(f"✅ LIVE sell order placed: {result['id']} @ ${sell_price:.2f}")
            else:
                print(f"❌ Sell order failed: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Error placing sell order: {e}")
            return {"error": str(e)}

    def get_open_option_positions(self):
        try:
            if not self.logged_in:
                return []
            return r.get_open_option_positions()
        except Exception as e:
            print(f"❌ Error fetching open positions: {e}")
            return []

    def get_all_open_option_orders(self):
        try:
            if not self.logged_in:
                return []
            return r.get_all_open_option_orders()
        except Exception as e:
            print(f"❌ Error fetching open orders: {e}")
            return []

    def cancel_option_order(self, order_id):
        try:
            if not self.logged_in:
                return {"error": "Not logged in"}
            return r.cancel_option_order(order_id)
        except Exception as e:
            print(f"❌ Error cancelling order {order_id}: {e}")
            return {"error": str(e)}
        
    def get_option_instrument_data(self, url):
        try:
            if not self.logged_in:
                return None
            return r.request_get(url)
        except Exception as e:
            print(f"❌ Error fetching instrument data: {e}")
            return None

    def get_option_order_info(self, order_id):
        try:
            if not self.logged_in:
                return None
            return r.get_option_order_info(order_id)
        except Exception as e:
            print(f"❌ Error fetching order info: {e}")
            return None

    def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type):
        try:
            for pos in all_positions:
                instrument_data = self.get_option_instrument_data(pos['option'])
                if not instrument_data: continue
                if (pos['chain_symbol'].upper() == str(symbol).upper() and
                        float(instrument_data['strike_price']) == float(strike) and
                        instrument_data['expiration_date'] == str(expiration) and
                        instrument_data['type'].lower() == str(opt_type).lower()):
                    pos.update(instrument_data)
                    return pos
            return None
        except Exception as e:
            print(f"❌ Error searching through positions list: {e}")
            return None
            
    def get_open_orders_for_contract(self, instrument_url):
        try:
            orders = self.get_all_open_option_orders()
            return [o for o in orders if o.get('legs', [{}])[0].get('option') == instrument_url]
        except Exception as e:
            print(f"❌ Error fetching open orders for instrument {instrument_url}: {e}")
            return []

    def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
        """Finds and cancels all open orders for a specific option contract."""
        try:
            if not self.logged_in:
                print("❌ Not logged in, cannot cancel orders")
                return 0
                
            all_positions = self.get_open_option_positions()
            position = self.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
            if not position:
                print(f"No open position found for {symbol} {strike}{opt_type}, so no orders to cancel.")
                return 0
            
            instrument_url = position.get('option')
            open_orders = self.get_open_orders_for_contract(instrument_url)
            
            if not open_orders:
                print(f"No open orders found for {symbol} {strike}{opt_type}.")
                return 0

            cancelled_count = 0
            for order in open_orders:
                order_id = order.get('id')
                if order_id:
                    print(f"Cancelling open order {order_id} for {symbol} {strike}{opt_type}...")
                    result = self.cancel_option_order(order_id)
                    if not result.get('error'):
                        cancelled_count += 1
            
            return cancelled_count
        except Exception as e:
            print(f"❌ Error cancelling open orders for {symbol} {strike}{opt_type}: {e}")
            return 0

    def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
        try:
            if not self.logged_in:
                return {"error": "Not logged in"}
            
            # Round stop price to tick size
            rounded_stop_price = self.round_to_tick(stop_price, symbol)
            
            return r.order_sell_option_stop_limit(
                positionEffect='close', creditOrDebit='credit',
                limitPrice=rounded_stop_price, stopPrice=rounded_stop_price,
                symbol=symbol, quantity=quantity, expirationDate=expiration,
                strike=strike, optionType=opt_type, timeInForce='gtc'
            )
        except Exception as e:
            print(f"❌ Error placing stop loss order: {e}")
            return {"error": str(e)}

    def get_option_market_data(self, symbol, expiration, strike, opt_type):
        try:
            if not self.logged_in:
                return []
            return r.get_option_market_data(symbol, expiration, strike, opt_type)
        except Exception as e:
            print(f"❌ Error fetching market data for {symbol}: {e}")
            return []


# Keep the SimulatedTrader exactly the same for testing
class SimulatedTrader(RobinhoodTrader):
    def __init__(self):
        print("✅ Initialized SimulatedTrader.")
        self.simulated_orders = {}
        self.simulated_positions = {}
        self.logged_in = True  # Always "logged in" for simulation

    def login(self): 
        print("✅ Simulated login successful.")
        self.logged_in = True
        
    def reconnect(self): 
        print("[SIMULATED] Reconnect called.")
        
    def get_portfolio_value(self) -> float: 
        return 100000.0
        
    def get_buying_power(self) -> float: 
        return 50000.0
        
    def get_instrument_tick_size(self, symbol: str) -> float | None: 
        return 0.05  # Standard options tick size for simulation
        
    def round_to_tick(self, price: float, symbol: str) -> float:
        """Simulated tick rounding"""
        tick_size = 0.05
        return round(round(price / tick_size) * tick_size, 2)
        
    def validate_order_requirements(self, *args): 
        return True

    def get_option_order_info(self, order_id):
        if order_id in self.simulated_orders:
            self.simulated_orders[order_id]['state'] = 'filled'
            return self.simulated_orders[order_id]
        return {'state': 'filled'}

    def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type):
        pos_key = f"{str(symbol).upper()}_{str(float(strike))}_{str(expiration)}_{str(opt_type).lower()}"
        return self.simulated_positions.get(pos_key)

    def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
        print(f"[SIMULATED] Cancelling open orders for {symbol} {strike}{opt_type}.")
        return 1

    def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
        # Apply tick rounding even in simulation
        rounded_price = self.round_to_tick(limit_price, symbol)
        order_id = f"sim_{uuid.uuid4()}"
        summary = f"[SIMULATED] BUY {quantity}x {symbol} @ {rounded_price:.2f} (tick-rounded)"
        self.simulated_orders[order_id] = {"id": order_id, "state": "confirmed", "detail": summary}
        pos_key = f"{str(symbol).upper()}_{str(float(strike))}_{str(expiration)}_{str(opt_type).lower()}"
        if pos_key in self.simulated_positions:
            existing_qty = float(self.simulated_positions[pos_key]['quantity'])
            self.simulated_positions[pos_key]['quantity'] = str(existing_qty + float(quantity))
        else:
            self.simulated_positions[pos_key] = {"quantity": str(float(quantity))}
        print(summary)
        return self.simulated_orders[order_id]

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        # Use provided padding or default
        if sell_padding is None:
            sell_padding = DEFAULT_SELL_PRICE_PADDING
            
        # Default to market-based price if not specified
        if not limit_price or limit_price <= 0:
            # Simulate market price
            limit_price = 1.50  # Default simulation price
            print(f"[SIMULATED] Using simulated market price: ${limit_price:.2f}")
        
        # Apply padding
        limit_price = limit_price * (1 - sell_padding)
        
        rounded_price = self.round_to_tick(limit_price, symbol)
        summary = f"[SIMULATED] SELL {quantity}x {symbol} @ {rounded_price:.2f} (market-based, padding: {sell_padding*100:.1f}%)"
        pos_key = f"{str(symbol).upper()}_{str(float(strike))}_{str(expiration)}_{str(opt_type).lower()}"
        if pos_key in self.simulated_positions:
            current_qty = float(self.simulated_positions[pos_key]['quantity'])
            new_qty = current_qty - float(quantity)
            if new_qty < 0.01:
                del self.simulated_positions[pos_key]
            else:
                self.simulated_positions[pos_key]['quantity'] = str(new_qty)
        print(summary)
        return {"detail": summary, "id": f"sim_sell_{uuid.uuid4()}"}

    def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
        rounded_stop = self.round_to_tick(stop_price, symbol)
        summary = f"[SIMULATED] STOP-LOSS for {quantity}x {symbol} @ {rounded_stop:.2f} (tick-rounded)"
        print(summary)
        return {"detail": summary}

    # Use real market data even in simulation (but need to handle login state)
    def get_option_market_data(self, symbol, expiration, strike, opt_type):
        try:
            # For simulation, try to get real market data but fall back if not logged in
            return r.get_option_market_data(symbol, expiration, strike, opt_type)
        except:
            # Fallback to mock data if real API not available
            return [{'bid_price': '1.45', 'ask_price': '1.55', 'mark_price': '1.50'}]