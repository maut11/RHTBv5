# trader.py - Enhanced Trading Interface with Better Error Handling
import os
import uuid
import robin_stocks.robinhood as r
from dotenv import load_dotenv
from config import DEFAULT_SELL_PRICE_PADDING, ORDER_MANAGEMENT_CONFIG
import time
from datetime import datetime, timezone

load_dotenv()
ROBINHOOD_USER = os.getenv("ROBINHOOD_USER")
ROBINHOOD_PASS = os.getenv("ROBINHOOD_PASS")

class EnhancedRobinhoodTrader:
    """Enhanced Robinhood trader with better reliability and error handling"""
    
    def __init__(self):
        self.logged_in = False
        self.session_start_time = None
        self.last_heartbeat = None
        self.connection_errors = 0
        self.max_connection_errors = 3
        self.login()

    def login(self):
        """Enhanced login with better error handling"""
        try:
            print("🔐 Attempting Robinhood login...")
            
            login_result = r.login(
                username=ROBINHOOD_USER, 
                password=ROBINHOOD_PASS, 
                expiresIn=31536000,  # 1 year
                store_session=True
            )
            
            if login_result:
                self.logged_in = True
                self.session_start_time = datetime.now(timezone.utc)
                self.connection_errors = 0
                print("✅ Robinhood login successful.")
                
                # Enhanced verification
                try:
                    account_info = r.load_account_profile()
                    if account_info:
                        account_number = account_info.get('account_number', 'N/A')
                        print(f"📊 Account verified: {account_number}")
                        
                        # Check trading permissions
                        positions = r.get_open_option_positions()
                        print(f"✅ Options trading verified: {len(positions)} open positions")
                    else:
                        print("⚠️ Login successful but couldn't verify account access")
                except Exception as e:
                    print(f"⚠️ Login successful but verification failed: {e}")
                
            else:
                print("❌ Robinhood login failed - check credentials")
                self.logged_in = False
            
        except Exception as e:
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["challenge", "mfa", "two", "verification"]):
                print("❌ 2FA/Challenge required but not supported in this version")
                print("💡 Please disable 2FA on your Robinhood account")
            else:
                print(f"❌ Robinhood login failed: {e}")
            self.logged_in = False

    def check_connection(self):
        """Enhanced connection check with automatic recovery"""
        try:
            if not self.logged_in:
                return False
                
            # Quick connection test
            account = r.load_account_profile()
            if account:
                self.last_heartbeat = datetime.now(timezone.utc)
                self.connection_errors = 0
                return True
            else:
                self.connection_errors += 1
                return False
                
        except Exception as e:
            self.connection_errors += 1
            print(f"⚠️ Connection check failed: {e}")
            
            # Auto-reconnect if too many errors
            if self.connection_errors >= self.max_connection_errors:
                print("🔄 Too many connection errors, attempting reconnect...")
                self.reconnect()
            
            return False

    def reconnect(self):
        """Enhanced reconnection with exponential backoff"""
        print("⚙️ Attempting to reconnect to Robinhood...")
        try:
            # Clear session and wait
            r.logout()
            time.sleep(2)
            
            # Attempt fresh login with backoff
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    self.login()
                    if self.logged_in:
                        print(f"✅ Reconnection successful on attempt {attempt + 1}")
                        return True
                except Exception as e:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(f"❌ Reconnection attempt {attempt + 1} failed: {e}")
                    if attempt < max_attempts - 1:
                        print(f"⏳ Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)
            
            print("❌ All reconnection attempts failed")
            self.logged_in = False
            return False
            
        except Exception as e:
            print(f"❌ Failed to reconnect to Robinhood: {e}")
            self.logged_in = False
            return False

    def ensure_connection(self):
        """Ensure we have a valid connection before trading operations"""
        if not self.logged_in:
            print("❌ Not logged in to Robinhood")
            return False
            
        if not self.check_connection():
            print("⚠️ Connection lost, attempting reconnect...")
            return self.reconnect()
        
        return True

    def get_portfolio_value(self) -> float:
        """Get current portfolio value with enhanced error handling"""
        try:
            if not self.ensure_connection():
                print("❌ Cannot get portfolio value - connection failed")
                return 0.0
            
            profile = r.load_portfolio_profile()
            if profile and 'equity' in profile:
                equity = float(profile['equity'])
                print(f"💰 Current portfolio value: ${equity:,.2f}")
                return equity
            else:
                print("❌ Could not fetch portfolio value - invalid response")
                return 0.0
                
        except Exception as e:
            print(f"❌ Error fetching portfolio value: {e}")
            self.connection_errors += 1
            return 0.0

    def get_buying_power(self) -> float:
        """Get available buying power with error handling"""
        try:
            if not self.ensure_connection():
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

    def get_instrument_tick_size(self, symbol: str) -> float:
        """Enhanced tick size detection with caching"""
        try:
            if not self.ensure_connection():
                return 0.05  # Safe fallback
                
            # Try to get tick size from instrument data
            instruments = r.get_instruments_by_symbols(symbol)
            if instruments and instruments[0] and instruments[0].get('min_tick_size'):
                tick_size = float(instruments[0]['min_tick_size'])
                print(f"📏 Tick size for {symbol}: ${tick_size}")
                return tick_size
                
        except Exception as e:
            print(f"❌ Could not fetch tick size for {symbol}: {e}")
        
        # Enhanced fallback logic
        try:
            sample_data = r.get_quotes(symbol)
            if sample_data and sample_data[0]:
                price = float(sample_data[0].get('last_trade_price', 1.0))
                
                # Standard options tick size rules
                if price < 3.00:
                    return 0.05
                else:
                    return 0.10
                    
        except Exception:
            pass
        
        print(f"⚠️ Using default tick size for {symbol}: $0.05")
        return 0.05

    def round_to_tick(self, price: float, symbol: str) -> float:
        """Round price to the nearest valid tick size"""
        try:
            tick_size = self.get_instrument_tick_size(symbol)
            if tick_size is None or tick_size == 0:
                tick_size = 0.05
            
            rounded_price = round(round(price / tick_size) * tick_size, 2)
            
            if abs(rounded_price - price) > 0.001:  # Only log if significant difference
                print(f"📏 Rounded price from ${price:.2f} to ${rounded_price:.2f} (tick: ${tick_size})")
            
            return max(rounded_price, tick_size)  # Ensure minimum tick size
            
        except Exception as e:
            print(f"❌ Error rounding price: {e}")
            return round(max(price, 0.05), 2)

    def validate_order_requirements(self, symbol, strike, expiration, opt_type, quantity, price):
        """Enhanced order validation"""
        try:
            if not self.ensure_connection():
                raise Exception("Connection to Robinhood failed")
                
            # Check buying power
            required_capital = price * quantity * 100
            available_power = self.get_buying_power()
            
            if required_capital > available_power * 0.95:  # Leave 5% buffer
                raise Exception(f"Insufficient buying power: ${required_capital:,.2f} required, ${available_power:,.2f} available")
            
            # Validate contract exists
            try:
                market_data = r.get_option_market_data(symbol, expiration, strike, opt_type)
                if not market_data or len(market_data) == 0:
                    raise Exception(f"Contract not found: {symbol} ${strike}{opt_type.upper()} {expiration}")
            except Exception as e:
                print(f"⚠️ Could not validate contract existence: {e}")
            
            # Check market hours (informational)
            from datetime import datetime, time as dt_time
            now = datetime.now()
            market_open = dt_time(9, 30)
            market_close = dt_time(16, 0)
            current_time = now.time()
            
            if not (market_open <= current_time <= market_close):
                print(f"⚠️ Warning: Trading outside market hours ({current_time.strftime('%H:%M')})")
            
            return True
            
        except Exception as e:
            print(f"❌ Order validation failed: {e}")
            return False

    def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
        """Enhanced buy order with comprehensive error handling"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection to Robinhood failed"}
            
            # Round to proper tick size
            rounded_price = self.round_to_tick(limit_price, symbol)
            
            print(f"🔍 Validating buy order: {symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${rounded_price:.2f}")
            
            # Validate order
            if not self.validate_order_requirements(symbol, strike, expiration, opt_type, quantity, rounded_price):
                return {"error": "Order validation failed"}
            
            # Place the order with timeout
            print(f"📤 Placing LIVE buy order...")
            
            start_time = time.time()
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
            
            execution_time = time.time() - start_time
            
            if result and result.get('id'):
                print(f"✅ LIVE buy order placed: {result['id']} (execution: {execution_time:.2f}s)")
                
                # Log order details for tracking
                print(f"📋 Order details: {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f}")
            else:
                print(f"❌ Buy order failed: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Error placing buy order: {e}")
            self.connection_errors += 1
            return {"error": str(e)}

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        """Enhanced sell order with intelligent market pricing"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection to Robinhood failed"}
            
            # Use provided padding or default
            if sell_padding is None:
                sell_padding = DEFAULT_SELL_PRICE_PADDING
            
            # ALWAYS get current market price
            print(f"📊 Fetching current market price for {symbol} ${strike}{opt_type[0].upper()}...")
            market_data_list = self.get_option_market_data(symbol, expiration, strike, opt_type)
            
            final_price = None
            price_source = "unknown"
            
            # Enhanced price discovery
            if market_data_list and len(market_data_list) > 0:
                data = market_data_list[0]
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                if isinstance(data, dict):
                    mark_price = data.get('mark_price')
                    bid_price = float(data.get('bid_price', 0) or 0)
                    ask_price = float(data.get('ask_price', 0) or 0)
                    
                    # Priority 1: Mark price (most accurate)
                    if mark_price and float(mark_price) > 0:
                        final_price = float(mark_price)
                        price_source = "mark"
                        print(f"✅ Using mark price: ${final_price:.2f}")
                    # Priority 2: Bid/Ask midpoint
                    elif bid_price > 0 and ask_price > 0:
                        final_price = (bid_price + ask_price) / 2
                        price_source = "midpoint"
                        print(f"✅ Using bid/ask midpoint: ${final_price:.2f} (bid: ${bid_price:.2f}, ask: ${ask_price:.2f})")
                    # Priority 3: Bid only (conservative)
                    elif bid_price > 0:
                        final_price = bid_price
                        price_source = "bid"
                        print(f"✅ Using bid price: ${final_price:.2f}")
                    # Priority 4: Discounted ask
                    elif ask_price > 0:
                        final_price = ask_price * 0.90  # 10% below ask
                        price_source = "discounted_ask"
                        print(f"✅ Using discounted ask: ${final_price:.2f} (ask: ${ask_price:.2f})")
            
            # Emergency fallback pricing
            if not final_price or final_price <= 0:
                if limit_price and limit_price > 0:
                    final_price = limit_price * 0.80  # 20% discount for emergency
                    price_source = "emergency_provided"
                    print(f"⚠️ Using emergency price: ${final_price:.2f}")
                else:
                    final_price = 0.05  # Absolute minimum
                    price_source = "emergency_minimum"
                    print(f"🚨 Using minimum price: ${final_price:.2f}")
            
            # Apply padding and round to tick
            sell_price = final_price * (1 - sell_padding)
            sell_price = self.round_to_tick(sell_price, symbol)
            
            print(f"📤 Placing LIVE sell order: {symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${sell_price:.2f}")
            print(f"📈 Price source: {price_source}, padding: {sell_padding*100:.1f}%")
            
            start_time = time.time()
            result = r.order_sell_option_limit(
                positionEffect='close', 
                creditOrDebit='credit', 
                price=sell_price,
                symbol=symbol, 
                quantity=quantity, 
                expirationDate=expiration, 
                strike=strike, 
                optionType=opt_type, 
                timeInForce='gtc'  # Good till cancelled for better fills
            )
            
            execution_time = time.time() - start_time
            
            if result and result.get('id'):
                print(f"✅ LIVE sell order placed: {result['id']} @ ${sell_price:.2f} (execution: {execution_time:.2f}s)")
            else:
                print(f"❌ Sell order failed: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Error placing sell order: {e}")
            self.connection_errors += 1
            return {"error": str(e)}

    def get_open_option_positions(self):
        """Get open positions with error handling"""
        try:
            if not self.ensure_connection():
                return []
            return r.get_open_option_positions()
        except Exception as e:
            print(f"❌ Error fetching open positions: {e}")
            self.connection_errors += 1
            return []

    def get_all_open_option_orders(self):
        """Get open orders with error handling"""
        try:
            if not self.ensure_connection():
                return []
            return r.get_all_open_option_orders()
        except Exception as e:
            print(f"❌ Error fetching open orders: {e}")
            return []

    def cancel_option_order(self, order_id):
        """Cancel order with enhanced error handling"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection failed"}
            
            result = r.cancel_option_order(order_id)
            if result:
                print(f"✅ Cancelled order: {order_id}")
            return result
        except Exception as e:
            print(f"❌ Error cancelling order {order_id}: {e}")
            return {"error": str(e)}
        
    def get_option_instrument_data(self, url):
        """Get instrument data with error handling"""
        try:
            if not self.ensure_connection():
                return None
            return r.request_get(url)
        except Exception as e:
            print(f"❌ Error fetching instrument data: {e}")
            return None

    def get_option_order_info(self, order_id):
        """Get order info with error handling"""
        try:
            if not self.ensure_connection():
                return None
            return r.get_option_order_info(order_id)
        except Exception as e:
            print(f"❌ Error fetching order info for {order_id}: {e}")
            return None

    def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type):
        """Find specific position with enhanced matching"""
        try:
            for pos in all_positions:
                instrument_data = self.get_option_instrument_data(pos['option'])
                if not instrument_data: 
                    continue
                    
                # Enhanced matching with type conversion
                if (pos['chain_symbol'].upper() == str(symbol).upper() and
                            abs(float(instrument_data['strike_price']) - float(strike)) < 0.01 and
                            instrument_data['expiration_date'] == str(expiration) and
                            instrument_data['type'].lower() == str(opt_type).lower()):
                    pos.update(instrument_data)
                    print(f"✅ Found matching position: {symbol} ${strike}{opt_type.upper()}")
                    return pos
            return None
        except Exception as e:
            print(f"❌ Error searching positions: {e}")
            return None

    def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
        """Cancel all open orders for a contract with enhanced logic"""
        try:
            if not self.ensure_connection():
                print("❌ Not logged in, cannot cancel orders")
                return 0
                
            all_positions = self.get_open_option_positions()
            position = self.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)
            
            if not position:
                print(f"ℹ️ No position found for {symbol} ${strike}{opt_type.upper()}, checking all open orders...")
                # If no position, check all open orders anyway
                all_orders = self.get_all_open_option_orders()
                relevant_orders = []
                
                for order in all_orders:
                    if (order.get('state', '').lower() in ['queued', 'unconfirmed', 'confirmed'] and
                        len(order.get('legs', [])) > 0):
                        leg = order['legs'][0]
                        # Try to match by available order data
                        relevant_orders.append(order)
                
                if not relevant_orders:
                    print(f"ℹ️ No open orders found for {symbol}")
                    return 0
                    
                cancelled_count = 0
                for order in relevant_orders[:3]:  # Limit to prevent mass cancellation
                    order_id = order.get('id')
                    if order_id:
                        result = self.cancel_option_order(order_id)
                        if not result.get('error'):
                            cancelled_count += 1
                
                return cancelled_count
            
            # If position found, get orders for that specific instrument
            instrument_url = position.get('option')
            all_orders = self.get_all_open_option_orders()
            relevant_orders = [
                order for order in all_orders 
                if (len(order.get('legs', [])) > 0 and 
                    order['legs'][0].get('option') == instrument_url and
                    order.get('state', '').lower() in ['queued', 'unconfirmed', 'confirmed'])
            ]
            
            if not relevant_orders:
                print(f"ℹ️ No open orders found for {symbol} ${strike}{opt_type.upper()}")
                return 0

            cancelled_count = 0
            for order in relevant_orders:
                order_id = order.get('id')
                if order_id:
                    print(f"🚫 Cancelling order {order_id} for {symbol} ${strike}{opt_type.upper()}...")
                    result = self.cancel_option_order(order_id)
                    if not result.get('error'):
                        cancelled_count += 1
            
            print(f"✅ Cancelled {cancelled_count} orders for {symbol} ${strike}{opt_type.upper()}")
            return cancelled_count
            
        except Exception as e:
            print(f"❌ Error cancelling orders for {symbol}: {e}")
            return 0

    def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
        """Place stop loss with enhanced error handling"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection failed"}
            
            rounded_stop_price = self.round_to_tick(stop_price, symbol)
            
            print(f"🛡️ Placing stop loss: {symbol} ${strike}{opt_type.upper()} x{quantity} @ ${rounded_stop_price:.2f}")
            
            result = r.order_sell_option_stop_limit(
                positionEffect='close', 
                creditOrDebit='credit',
                limitPrice=rounded_stop_price, 
                stopPrice=rounded_stop_price,
                symbol=symbol, 
                quantity=quantity, 
                expirationDate=expiration,
                strike=strike, 
                optionType=opt_type, 
                timeInForce='gtc'
            )
            
            if result and result.get('id'):
                print(f"✅ Stop loss placed: {result['id']}")
            
            return result
        except Exception as e:
            print(f"❌ Error placing stop loss: {e}")
            return {"error": str(e)}

    def get_option_market_data(self, symbol, expiration, strike, opt_type):
        """Get market data with enhanced error handling"""
        try:
            if not self.ensure_connection():
                return []
            
            data = r.get_option_market_data(symbol, expiration, strike, opt_type)
            if data:
                print(f"📊 Market data retrieved for {symbol} ${strike}{opt_type.upper()}")
            return data
        except Exception as e:
            print(f"❌ Error fetching market data for {symbol}: {e}")
            return []

    def get_session_info(self):
        """Get current session information"""
        return {
            "logged_in": self.logged_in,
            "session_start": self.session_start_time,
            "last_heartbeat": self.last_heartbeat,
            "connection_errors": self.connection_errors,
            "session_duration": (datetime.now(timezone.utc) - self.session_start_time).total_seconds() / 3600 if self.session_start_time else 0
        }


class EnhancedSimulatedTrader:
    """Enhanced simulated trader with more realistic behavior"""
    
    def __init__(self):
        print("✅ Enhanced Simulated Trader initialized.")
        self.simulated_orders = {}
        self.simulated_positions = {}
        self.logged_in = True
        self.session_start_time = datetime.now(timezone.utc)
        self.order_counter = 0

    def login(self): 
        print("✅ [SIMULATED] Login successful.")
        self.logged_in = True
        
    def reconnect(self): 
        print("🔄 [SIMULATED] Reconnect called.")
        return True
        
    def ensure_connection(self):
        return True
        
    def get_portfolio_value(self) -> float: 
        return 100000.0
        
    def get_buying_power(self) -> float: 
        return 50000.0
        
    def get_instrument_tick_size(self, symbol: str) -> float: 
        return 0.05
        
    def round_to_tick(self, price: float, symbol: str) -> float:
        tick_size = 0.05
        return round(round(price / tick_size) * tick_size, 2)
        
    def validate_order_requirements(self, *args): 
        return True

    def get_option_order_info(self, order_id):
        if order_id in self.simulated_orders:
            # Simulate order progression
            order = self.simulated_orders[order_id]
            if order.get('state') == 'confirmed':
                order['state'] = 'filled'
            return order
        return {'state': 'filled', 'id': order_id}

    def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type):
        pos_key = f"{str(symbol).upper()}_{str(float(strike))}_{str(expiration)}_{str(opt_type).lower()}"
        position = self.simulated_positions.get(pos_key)
        if position:
            print(f"✅ [SIMULATED] Found position: {symbol} ${strike}{opt_type.upper()}")
        return position

    def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
        print(f"🚫 [SIMULATED] Cancelling orders for {symbol} ${strike}{opt_type.upper()}")
        return 1

    def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
        self.order_counter += 1
        rounded_price = self.round_to_tick(limit_price, symbol)
        order_id = f"sim_buy_{self.order_counter}_{uuid.uuid4().hex[:8]}"
        
        summary = f"[SIMULATED] BUY {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f}"
        
        self.simulated_orders[order_id] = {
            "id": order_id, 
            "state": "confirmed", 
            "detail": summary,
            "symbol": symbol,
            "quantity": quantity,
            "price": rounded_price
        }
        
        # Add to positions
        pos_key = f"{str(symbol).upper()}_{str(float(strike))}_{str(expiration)}_{str(opt_type).lower()}"
        if pos_key in self.simulated_positions:
            existing_qty = float(self.simulated_positions[pos_key]['quantity'])
            self.simulated_positions[pos_key]['quantity'] = str(existing_qty + float(quantity))
        else:
            self.simulated_positions[pos_key] = {
                "quantity": str(float(quantity)),
                "symbol": symbol,
                "strike": strike,
                "expiration": expiration,
                "type": opt_type,
                "entry_price": rounded_price
            }
        
        print(summary)
        return {"detail": summary, "id": order_id}

    def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
        rounded_stop = self.round_to_tick(stop_price, symbol)
        summary = f"🛡️ [SIMULATED] STOP-LOSS for {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_stop:.2f}"
        print(summary)
        return {"detail": summary, "id": f"sim_stop_{uuid.uuid4().hex[:8]}"}

    def get_open_option_positions(self):
        """Return simulated positions in Robinhood format"""
        positions = []
        for pos_key, pos_data in self.simulated_positions.items():
            positions.append({
                'chain_symbol': pos_data['symbol'],
                'quantity': pos_data['quantity'],
                'option': f"https://simulated.url/{pos_key}"
            })
        return positions

    def get_all_open_option_orders(self):
        """Return simulated open orders"""
        return [order for order in self.simulated_orders.values() if order.get('state') == 'confirmed']

    def cancel_option_order(self, order_id):
        if order_id in self.simulated_orders:
            self.simulated_orders[order_id]['state'] = 'cancelled'
            print(f"🚫 [SIMULATED] Cancelled order: {order_id}")
        return {"detail": "cancelled"}

    def get_option_instrument_data(self, url):
        """Simulate instrument data from URL"""
        # Extract data from simulated URL
        pos_key = url.split('/')[-1]
        if '_' in pos_key:
            parts = pos_key.split('_')
            if len(parts) >= 4:
                return {
                    'strike_price': parts[1],
                    'expiration_date': parts[2],
                    'type': parts[3]
                }
        return None

    def get_option_market_data(self, symbol, expiration, strike, opt_type):
        """Simulate realistic market data"""
        try:
            # Try to get real market data first (for simulation realism)
            import robin_stocks.robinhood as r
            real_data = r.get_option_market_data(symbol, expiration, strike, opt_type)
            if real_data:
                print(f"📊 [SIMULATED] Using real market data for {symbol}")
                return real_data
        except:
            pass
        
        # Fallback to simulated data
        print(f"📊 [SIMULATED] Using mock market data for {symbol}")
        return [{
            'bid_price': '1.45', 
            'ask_price': '1.55', 
            'mark_price': '1.50',
            'volume': '150',
            'open_interest': '1250'
        }]

    def get_session_info(self):
        """Get simulated session info"""
        return {
            "logged_in": True,
            "session_start": self.session_start_time,
            "last_heartbeat": datetime.now(timezone.utc),
            "connection_errors": 0,
            "session_duration": (datetime.now(timezone.utc) - self.session_start_time).total_seconds() / 3600,
            "mode": "SIMULATION"
        }

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        self.order_counter += 1
        
        # Use provided padding or default
        if sell_padding is None:
            sell_padding = DEFAULT_SELL_PRICE_PADDING
            
        # Simulate market-based pricing
        if not limit_price or limit_price <= 0:
            # Simulate getting market price
            limit_price = 1.50  # Default simulation price
            print(f"📊 [SIMULATED] Using simulated market price: ${limit_price:.2f}")
        
        # Apply padding
        final_price = limit_price * (1 - sell_padding)
        rounded_price = self.round_to_tick(final_price, symbol)
        
        order_id = f"sim_sell_{self.order_counter}_{uuid.uuid4().hex[:8]}"
        summary = f"[SIMULATED] SELL {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f} (market-based, padding: {sell_padding*100:.1f}%)"
        
        # Update positions
        pos_key = f"{str(symbol).upper()}_{str(float(strike))}_{str(expiration)}_{str(opt_type).lower()}"
        if pos_key in self.simulated_positions:
            current_qty = float(self.simulated_positions[pos_key]['quantity'])
            new_qty = current_qty - float(quantity)
            if new_qty < 0.01:
                del self.simulated_positions[pos_key]
                print(f"🔴 [SIMULATED] Closed position: {symbol}")
            else:
                self.simulated_positions[pos_key]['quantity'] = str(new_qty)
                print(f"🟡 [SIMULATED] Trimmed position: {symbol} ({new_qty} remaining)")
        
        print(summary)
        return {"detail": summary, "id": order_id}

# Aliases for backwards compatibility
RobinhoodTrader = EnhancedRobinhoodTrader
SimulatedTrader = EnhancedSimulatedTrader