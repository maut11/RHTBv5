# trader.py - Enhanced Trading Interface with PRIORITIZED Robinhood API Tick Size
import os
import uuid
import robin_stocks.robinhood as r
from dotenv import load_dotenv
from config import DEFAULT_SELL_PRICE_PADDING, ORDER_MANAGEMENT_CONFIG
import time
from datetime import datetime, timezone
import logging

# Setup logging for trader module
logger = logging.getLogger('trader')
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    if not os.path.exists('logs'):
        os.makedirs('logs')
    handler = logging.FileHandler('logs/trader.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

load_dotenv()
ROBINHOOD_USER = os.getenv("ROBINHOOD_USER")
ROBINHOOD_PASS = os.getenv("ROBINHOOD_PASS")

class EnhancedRobinhoodTrader:
    """Enhanced Robinhood trader with PRIORITIZED tick size from RH API"""
    
    def __init__(self):
        self.logged_in = False
        self.session_start_time = None
        self.last_heartbeat = None
        self.connection_errors = 0
        self.max_connection_errors = 3
        self._login_attempts = 0
        self._max_login_attempts = 3
        
        # ENHANCED: Aggressive tick size caching
        self._tick_size_cache = {}
        self._instrument_cache = {}
        self._cache_timestamps = {}
        self._cache_ttl = 300  # 5 minutes cache TTL
        
        self.login()

    def login(self):
        """Enhanced login with better error handling and retry logic"""
        self._login_attempts += 1
        
        if self._login_attempts > self._max_login_attempts:
            logger.error(f"Max login attempts ({self._max_login_attempts}) exceeded")
            print(f"❌ Max login attempts exceeded. Please check credentials.")
            return False
            
        try:
            print(f"🔐 Attempting Robinhood login (attempt {self._login_attempts}/{self._max_login_attempts})...")
            logger.info(f"Login attempt {self._login_attempts}")
            
            # Clear any existing session first
            try:
                r.logout()
            except:
                pass
            
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
                self._login_attempts = 0  # Reset on success
                print("✅ Robinhood login successful.")
                logger.info("Login successful")
                
                # Enhanced verification
                try:
                    account_info = r.load_account_profile()
                    if account_info:
                        account_number = account_info.get('account_number', 'N/A')
                        print(f"📊 Account verified: {account_number[:4]}****")
                        logger.info(f"Account verified: {account_number[:4]}****")
                        
                        # Check trading permissions
                        positions = r.get_open_option_positions()
                        print(f"✅ Options trading verified: {len(positions)} open positions")
                        logger.info(f"Options trading verified with {len(positions)} positions")
                        return True
                    else:
                        print("⚠️ Login successful but couldn't verify account access")
                        logger.warning("Could not verify account access")
                except Exception as e:
                    print(f"⚠️ Login successful but verification failed: {e}")
                    logger.warning(f"Verification failed: {e}")
                
                return True
            else:
                print(f"❌ Robinhood login failed - attempt {self._login_attempts}")
                logger.error(f"Login failed - attempt {self._login_attempts}")
                self.logged_in = False
                
                # Retry with delay
                if self._login_attempts < self._max_login_attempts:
                    wait_time = 2 ** self._login_attempts
                    print(f"⏳ Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    return self.login()
                    
                return False
            
        except Exception as e:
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ["challenge", "mfa", "two", "verification"]):
                print("❌ 2FA/Challenge required but not supported in this version")
                print("💡 Please disable 2FA on your Robinhood account or use app-specific password")
                logger.error("2FA required but not supported")
            else:
                print(f"❌ Robinhood login failed with error: {e}")
                logger.error(f"Login exception: {e}")
            
            self.logged_in = False
            return False

    def check_connection(self):
        """Enhanced connection check with automatic recovery"""
        try:
            if not self.logged_in:
                logger.warning("Not logged in during connection check")
                return False
                
            # Quick connection test
            account = r.load_account_profile()
            if account:
                self.last_heartbeat = datetime.now(timezone.utc)
                self.connection_errors = 0
                return True
            else:
                self.connection_errors += 1
                logger.warning(f"Connection check failed - error count: {self.connection_errors}")
                return False
                
        except Exception as e:
            self.connection_errors += 1
            print(f"⚠️ Connection check failed: {e}")
            logger.error(f"Connection check exception: {e}")
            
            # Auto-reconnect if too many errors
            if self.connection_errors >= self.max_connection_errors:
                print("🔄 Too many connection errors, attempting reconnect...")
                logger.info("Auto-reconnect triggered")
                self.reconnect()
            
            return False

    def reconnect(self):
        """Enhanced reconnection with exponential backoff"""
        print("⚙️ Attempting to reconnect to Robinhood...")
        logger.info("Reconnection attempt started")
        
        try:
            # Clear session and wait
            try:
                r.logout()
            except:
                pass
            time.sleep(2)
            
            # Reset login attempts counter for reconnect
            self._login_attempts = 0
            
            # Attempt fresh login with backoff
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    if self.login():
                        print(f"✅ Reconnection successful on attempt {attempt + 1}")
                        logger.info(f"Reconnection successful on attempt {attempt + 1}")
                        return True
                except Exception as e:
                    wait_time = 2 ** attempt  # Exponential backoff
                    print(f"❌ Reconnection attempt {attempt + 1} failed: {e}")
                    logger.error(f"Reconnection attempt {attempt + 1} failed: {e}")
                    if attempt < max_attempts - 1:
                        print(f"⏳ Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)
            
            print("❌ All reconnection attempts failed")
            logger.error("All reconnection attempts failed")
            self.logged_in = False
            return False
            
        except Exception as e:
            print(f"❌ Failed to reconnect to Robinhood: {e}")
            logger.error(f"Reconnection exception: {e}")
            self.logged_in = False
            return False

    def ensure_connection(self):
        """Ensure we have a valid connection before trading operations"""
        if not self.logged_in:
            print("❌ Not logged in to Robinhood")
            logger.warning("ensure_connection called but not logged in")
            return False
            
        if not self.check_connection():
            print("⚠️ Connection lost, attempting reconnect...")
            logger.info("Connection lost, triggering reconnect")
            return self.reconnect()
        
        return True

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache entry is still valid"""
        if cache_key not in self._cache_timestamps:
            return False
        
        cache_time = self._cache_timestamps[cache_key]
        current_time = time.time()
        return (current_time - cache_time) < self._cache_ttl

    def get_instruments_by_symbols(self, symbols):
        """Cached instrument data retrieval"""
        if isinstance(symbols, str):
            symbols = [symbols]
        
        results = []
        
        for symbol in symbols:
            cache_key = f"instrument_{symbol}"
            
            # Check cache first
            if cache_key in self._instrument_cache and self._is_cache_valid(cache_key):
                results.append(self._instrument_cache[cache_key])
                continue
            
            try:
                if not self.ensure_connection():
                    results.append(None)
                    continue
                
                # Fetch from API
                instruments = r.get_instruments_by_symbols([symbol])
                if instruments and len(instruments) > 0:
                    instrument = instruments[0]
                    # Cache the result
                    self._instrument_cache[cache_key] = instrument
                    self._cache_timestamps[cache_key] = time.time()
                    results.append(instrument)
                else:
                    results.append(None)
                    
            except Exception as e:
                logger.error(f"Error fetching instrument for {symbol}: {e}")
                results.append(None)
        
        return results

    def get_quotes(self, symbols):
        """Get stock quotes (used for price-based tick size fallback)"""
        try:
            if not self.ensure_connection():
                return []
            
            if isinstance(symbols, str):
                symbols = [symbols]
            
            quotes = r.get_quotes(symbols)
            return quotes
            
        except Exception as e:
            logger.error(f"Error fetching quotes for {symbols}: {e}")
            return []

    def get_instrument_tick_size(self, symbol: str) -> float:
        """PRIORITIZED tick size detection - RH API FIRST, then fallbacks"""
        cache_key = f"tick_{symbol}"
        
        # Priority 1: Check cache (fastest)
        if cache_key in self._tick_size_cache and self._is_cache_valid(cache_key):
            cached_tick = self._tick_size_cache[cache_key]
            logger.debug(f"Using cached tick size for {symbol}: ${cached_tick}")
            return cached_tick
        
        print(f"🔍 Fetching tick size for {symbol}...")
        
        # Priority 2: Robinhood API (PREFERRED - Most Accurate)
        try:
            instruments = self.get_instruments_by_symbols(symbol)
            if instruments and len(instruments) > 0 and instruments[0]:
                instrument = instruments[0]
                if 'min_tick_size' in instrument and instrument['min_tick_size']:
                    tick_size = float(instrument['min_tick_size'])
                    
                    # Cache the result
                    self._tick_size_cache[cache_key] = tick_size
                    self._cache_timestamps[cache_key] = time.time()
                    
                    print(f"📏 ✅ RH API tick size for {symbol}: ${tick_size}")
                    logger.info(f"RH API tick size for {symbol}: ${tick_size}")
                    return tick_size
                else:
                    print(f"⚠️ RH API returned instrument but no min_tick_size for {symbol}")
        except Exception as e:
            print(f"⚠️ RH API tick size failed for {symbol}: {e}")
            logger.warning(f"RH API tick size failed for {symbol}: {e}")
        
        # Priority 3: Price-based logic (smart fallback)
        try:
            quotes = self.get_quotes(symbol)
            if quotes and len(quotes) > 0 and quotes[0]:
                price = float(quotes[0].get('last_trade_price', 1.0))
                
                # Enhanced price-based tick size rules
                if price < 3.00:
                    tick_size = 0.05
                elif price >= 3.00:
                    tick_size = 0.10
                else:
                    tick_size = 0.05  # Conservative default
                
                # Cache the result
                self._tick_size_cache[cache_key] = tick_size
                self._cache_timestamps[cache_key] = time.time()
                
                print(f"📏 💡 Price-based tick size for {symbol}: ${tick_size} (price: ${price})")
                logger.info(f"Price-based tick size for {symbol}: ${tick_size} (price: ${price})")
                return tick_size
        except Exception as e:
            print(f"⚠️ Price-based tick size failed for {symbol}: {e}")
            logger.warning(f"Price-based tick size failed for {symbol}: {e}")
        
        # Priority 4: Smart symbol-based defaults
        if symbol.upper() in ['SPX', 'SPY', 'QQQ', 'IWM', 'TLT', 'GLD', 'VIX']:
            # Major ETFs and indices typically use 0.05
            tick_size = 0.05
        elif symbol.upper() in ['TSLA', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']:
            # High-priced individual stocks typically use 0.10 for options > $3
            tick_size = 0.05  # Conservative for options
        else:
            # Default for unknown symbols
            tick_size = 0.05
        
        # Cache even the default
        self._tick_size_cache[cache_key] = tick_size
        self._cache_timestamps[cache_key] = time.time()
        
        print(f"📏 ⚙️ Default tick size for {symbol}: ${tick_size}")
        logger.info(f"Default tick size used for {symbol}: ${tick_size}")
        return tick_size

    def round_to_tick(self, price: float, symbol: str, round_up: bool = False) -> float:
        """Enhanced tick rounding with round_up option"""
        try:
            tick_size = self.get_instrument_tick_size(symbol)
            if tick_size is None or tick_size == 0:
                tick_size = 0.05
            
            if round_up:
                import math
                ticks = math.ceil(price / tick_size)
            else:
                ticks = round(price / tick_size)
            
            rounded_price = ticks * tick_size
            
            # Ensure minimum tick size
            if rounded_price < tick_size:
                rounded_price = tick_size
            
            # Round to avoid floating point precision issues
            rounded_price = round(rounded_price, 2)
            
            if abs(rounded_price - price) > 0.001:  # Only log if significant difference
                print(f"📏 Rounded price: ${price:.3f} → ${rounded_price:.2f} (tick: ${tick_size}, up: {round_up})")
                logger.debug(f"Price rounded: ${price:.3f} -> ${rounded_price:.2f} (tick: ${tick_size})")
            
            return rounded_price
            
        except Exception as e:
            print(f"❌ Error rounding price for {symbol}: {e}")
            logger.error(f"Price rounding exception: {e}")
            return round(max(price, 0.05), 2)

    def get_portfolio_value(self) -> float:
        """Get current portfolio value with enhanced error handling"""
        try:
            if not self.ensure_connection():
                print("❌ Cannot get portfolio value - connection failed")
                logger.error("Portfolio value fetch failed - no connection")
                return 0.0
            
            profile = r.load_portfolio_profile()
            if profile and 'equity' in profile:
                equity = float(profile['equity'])
                print(f"💰 Current portfolio value: ${equity:,.2f}")
                logger.debug(f"Portfolio value: ${equity:,.2f}")
                return equity
            else:
                print("❌ Could not fetch portfolio value - invalid response")
                logger.error("Invalid portfolio response")
                return 0.0
                
        except Exception as e:
            print(f"❌ Error fetching portfolio value: {e}")
            logger.error(f"Portfolio value exception: {e}")
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
                logger.debug(f"Buying power: ${buying_power:,.2f}")
                return buying_power
            return 0.0
        except Exception as e:
            print(f"❌ Error fetching buying power: {e}")
            logger.error(f"Buying power exception: {e}")
            return 0.0

    def validate_order_requirements(self, symbol, strike, expiration, opt_type, quantity, price):
        """Enhanced order validation with tick size verification"""
        try:
            if not self.ensure_connection():
                raise Exception("Connection to Robinhood failed")
                
            # Check buying power
            required_capital = price * quantity * 100
            available_power = self.get_buying_power()
            
            if required_capital > available_power * 0.95:  # Leave 5% buffer
                error_msg = f"Insufficient buying power: ${required_capital:,.2f} required, ${available_power:,.2f} available"
                logger.warning(error_msg)
                raise Exception(error_msg)
            
            # Validate price is properly rounded to tick size
            tick_size = self.get_instrument_tick_size(symbol)
            expected_price = self.round_to_tick(price, symbol)
            if abs(price - expected_price) > 0.001:
                print(f"⚠️ Price ${price:.3f} not properly rounded, should be ${expected_price:.2f}")
                logger.warning(f"Price not tick-aligned: ${price:.3f} vs ${expected_price:.2f}")
            
            # Validate contract exists (optional check)
            try:
                market_data = r.get_option_market_data(symbol, expiration, strike, opt_type)
                if not market_data or len(market_data) == 0:
                    error_msg = f"Contract may not exist: {symbol} ${strike}{opt_type.upper()} {expiration}"
                    logger.warning(error_msg)
                    print(f"⚠️ {error_msg}")
            except Exception as e:
                print(f"⚠️ Could not validate contract existence: {e}")
                logger.warning(f"Contract validation failed: {e}")
            
            # Check market hours (informational)
            from datetime import datetime, time as dt_time
            now = datetime.now()
            market_open = dt_time(9, 30)
            market_close = dt_time(16, 0)
            current_time = now.time()
            
            if not (market_open <= current_time <= market_close):
                print(f"⚠️ Warning: Trading outside market hours ({current_time.strftime('%H:%M')})")
                logger.info(f"Trading outside market hours: {current_time.strftime('%H:%M')}")
            
            return True
            
        except Exception as e:
            print(f"❌ Order validation failed: {e}")
            logger.error(f"Order validation exception: {e}")
            return False

    def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
        """Enhanced buy order with OPTIMIZED tick rounding"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection to Robinhood failed"}
            
            # ENHANCED: Round to proper tick size with round_up for buys
            rounded_price = self.round_to_tick(limit_price, symbol, round_up=True)
            
            print(f"🔍 Validating buy order: {symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${rounded_price:.2f}")
            logger.info(f"Buy order validation: {symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${rounded_price:.2f}")
            
            # Validate order
            if not self.validate_order_requirements(symbol, strike, expiration, opt_type, quantity, rounded_price):
                return {"error": "Order validation failed"}
            
            # Place the order with timeout
            print(f"📤 Placing LIVE buy order with optimized tick size...")
            logger.info(f"Placing buy order for {symbol}")
            
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
                logger.info(f"Buy order placed successfully: {result['id']}")
                
                # Log order details for tracking
                print(f"📋 Order details: {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f}")
            else:
                print(f"❌ Buy order failed: {result}")
                logger.error(f"Buy order failed: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Error placing buy order: {e}")
            logger.error(f"Buy order exception: {e}")
            self.connection_errors += 1
            return {"error": str(e)}

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        """Enhanced sell order with OPTIMIZED market pricing and tick rounding"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection to Robinhood failed"}
            
            # Use provided padding or default
            if sell_padding is None:
                sell_padding = DEFAULT_SELL_PRICE_PADDING
            
            # ALWAYS get current market price for sells
            print(f"📊 Fetching current market price for {symbol} ${strike}{opt_type[0].upper()}...")
            logger.info(f"Fetching market price for sell order: {symbol}")
            
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
                        logger.debug(f"Using mark price: ${final_price:.2f}")
                    # Priority 2: Bid/Ask midpoint
                    elif bid_price > 0 and ask_price > 0:
                        final_price = (bid_price + ask_price) / 2
                        price_source = "midpoint"
                        print(f"✅ Using bid/ask midpoint: ${final_price:.2f} (bid: ${bid_price:.2f}, ask: ${ask_price:.2f})")
                        logger.debug(f"Using midpoint: ${final_price:.2f}")
                    # Priority 3: Bid only (conservative)
                    elif bid_price > 0:
                        final_price = bid_price
                        price_source = "bid"
                        print(f"✅ Using bid price: ${final_price:.2f}")
                        logger.debug(f"Using bid price: ${final_price:.2f}")
                    # Priority 4: Discounted ask
                    elif ask_price > 0:
                        final_price = ask_price * 0.90  # 10% below ask
                        price_source = "discounted_ask"
                        print(f"✅ Using discounted ask: ${final_price:.2f} (ask: ${ask_price:.2f})")
                        logger.debug(f"Using discounted ask: ${final_price:.2f}")
            
            # Emergency fallback pricing
            if not final_price or final_price <= 0:
                if limit_price and limit_price > 0:
                    final_price = limit_price * 0.80  # 20% discount for emergency
                    price_source = "emergency_provided"
                    print(f"⚠️ Using emergency price: ${final_price:.2f}")
                    logger.warning(f"Using emergency price: ${final_price:.2f}")
                else:
                    final_price = 0.50  # Reasonable minimum for options
                    price_source = "emergency_minimum"
                    print(f"🚨 Using minimum price: ${final_price:.2f}")
                    logger.warning(f"Using minimum price: ${final_price:.2f}")
            
            # Apply padding
            sell_price_raw = final_price * (1 - sell_padding)
            
            # ENHANCED: Round to tick with minimum premium protection (same as buy logic)
            tick_size = self.get_instrument_tick_size(symbol)
            sell_price = self.round_to_tick(sell_price_raw, symbol, round_up=False)
            
            # Ensure minimum tick premium cost (SAME AS BUY LOGIC)
            min_premium = max(tick_size, 0.05)  # Same minimum as buy logic
            sell_price = max(sell_price, min_premium)
            
            print(f"📤 Placing LIVE sell order: {symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${sell_price:.2f}")
            print(f"📈 Price source: {price_source}, padding: {sell_padding*100:.1f}%, tick: ${tick_size}")
            logger.info(f"Placing sell order: {symbol} x{quantity} @ ${sell_price:.2f} (source: {price_source})")
            
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
                logger.info(f"Sell order placed successfully: {result['id']}")
            else:
                print(f"❌ Sell order failed: {result}")
                logger.error(f"Sell order failed: {result}")
                
            return result
            
        except Exception as e:
            print(f"❌ Error placing sell order: {e}")
            logger.error(f"Sell order exception: {e}")
            self.connection_errors += 1
            return {"error": str(e)}

    def get_open_option_positions(self):
        """Get open positions with error handling"""
        try:
            if not self.ensure_connection():
                return []
            positions = r.get_open_option_positions()
            logger.debug(f"Retrieved {len(positions)} open positions")
            return positions
        except Exception as e:
            print(f"❌ Error fetching open positions: {e}")
            logger.error(f"Open positions exception: {e}")
            self.connection_errors += 1
            return []

    def get_all_open_option_orders(self):
        """Get open orders with error handling"""
        try:
            if not self.ensure_connection():
                return []
            orders = r.get_all_open_option_orders()
            logger.debug(f"Retrieved {len(orders)} open orders")
            return orders
        except Exception as e:
            print(f"❌ Error fetching open orders: {e}")
            logger.error(f"Open orders exception: {e}")
            return []

    def cancel_option_order(self, order_id):
        """Cancel order with enhanced error handling"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection failed"}
            
            result = r.cancel_option_order(order_id)
            if result:
                print(f"✅ Cancelled order: {order_id}")
                logger.info(f"Order cancelled: {order_id}")
            return result
        except Exception as e:
            print(f"❌ Error cancelling order {order_id}: {e}")
            logger.error(f"Cancel order exception: {e}")
            return {"error": str(e)}
        
    def get_option_instrument_data(self, url):
        """Get instrument data with error handling"""
        try:
            if not self.ensure_connection():
                return None
            data = r.request_get(url)
            return data
        except Exception as e:
            print(f"❌ Error fetching instrument data: {e}")
            logger.error(f"Instrument data exception: {e}")
            return None

    def get_option_order_info(self, order_id):
        """Get order info with error handling"""
        try:
            if not self.ensure_connection():
                return None
            info = r.get_option_order_info(order_id)
            return info
        except Exception as e:
            print(f"❌ Error fetching order info for {order_id}: {e}")
            logger.error(f"Order info exception: {e}")
            return None

    def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type):
        """Find specific position with enhanced matching"""
        try:
            for pos in all_positions:
                instrument_data = self.get_option_instrument_data(pos['option'])
                if not instrument_data: 
                    continue
                    
                # Enhanced matching with type conversion and tolerance
                symbol_match = pos['chain_symbol'].upper() == str(symbol).upper()
                strike_match = abs(float(instrument_data['strike_price']) - float(strike)) < 0.01
                exp_match = instrument_data['expiration_date'] == str(expiration)
                type_match = instrument_data['type'].lower() == str(opt_type).lower()
                
                if symbol_match and strike_match and exp_match and type_match:
                    pos.update(instrument_data)
                    print(f"✅ Found matching position: {symbol} ${strike}{opt_type.upper()}")
                    logger.debug(f"Position found: {symbol} ${strike}{opt_type.upper()}")
                    return pos
                    
            logger.debug(f"No position found for {symbol} ${strike}{opt_type.upper()}")
            return None
        except Exception as e:
            print(f"❌ Error searching positions: {e}")
            logger.error(f"Position search exception: {e}")
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
                logger.info(f"No position found, checking all orders for {symbol}")
                
                # If no position, check all open orders anyway
                all_orders = self.get_all_open_option_orders()
                relevant_orders = []
                
                for order in all_orders:
                    if (order.get('state', '').lower() in ['queued', 'unconfirmed', 'confirmed'] and
                        len(order.get('legs', [])) > 0):
                        # Try to match by available order data
                        leg = order['legs'][0]
                        if leg.get('symbol', '').upper() == symbol.upper():
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
            logger.info(f"Cancelled {cancelled_count} orders for {symbol}")
            return cancelled_count
            
        except Exception as e:
            print(f"❌ Error cancelling orders for {symbol}: {e}")
            logger.error(f"Cancel orders exception: {e}")
            return 0

    def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
        """Place stop loss with OPTIMIZED tick rounding"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection failed"}
            
            # ENHANCED: Round stop price to proper tick size
            rounded_stop_price = self.round_to_tick(stop_price, symbol, round_up=False)
            
            print(f"🛡️ Placing stop loss: {symbol} ${strike}{opt_type.upper()} x{quantity} @ ${rounded_stop_price:.2f}")
            logger.info(f"Placing stop loss: {symbol} x{quantity} @ ${rounded_stop_price:.2f}")
            
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
                logger.info(f"Stop loss placed: {result['id']}")
            
            return result
        except Exception as e:
            print(f"❌ Error placing stop loss: {e}")
            logger.error(f"Stop loss exception: {e}")
            return {"error": str(e)}

    def get_option_market_data(self, symbol, expiration, strike, opt_type):
       """Get market data with enhanced error handling"""
       try:
           if not self.ensure_connection():
               return []
           
           data = r.get_option_market_data(symbol, expiration, strike, opt_type)
           if data:
               print(f"📊 Market data retrieved for {symbol} ${strike}{opt_type.upper()}")
               logger.debug(f"Market data retrieved for {symbol}")
           return data
       except Exception as e:
           print(f"❌ Error fetching market data for {symbol}: {e}")
           logger.error(f"Market data exception: {e}")
           return []

    def get_session_info(self):
       """Get current session information"""
       tick_cache_size = len(self._tick_size_cache)
       instrument_cache_size = len(self._instrument_cache)
       
       info = {
           "logged_in": self.logged_in,
           "session_start": self.session_start_time,
           "last_heartbeat": self.last_heartbeat,
           "connection_errors": self.connection_errors,
           "session_duration": (datetime.now(timezone.utc) - self.session_start_time).total_seconds() / 3600 if self.session_start_time else 0,
           "tick_cache_size": tick_cache_size,
           "instrument_cache_size": instrument_cache_size,
           "cache_ttl_minutes": self._cache_ttl / 60
       }
       logger.debug(f"Session info: {info}")
       return info

    def clear_cache(self):
        """Clear all caches"""
        self._tick_size_cache.clear()
        self._instrument_cache.clear()
        self._cache_timestamps.clear()
        print("🧹 Cleared all trader caches")
        logger.info("Cleared all trader caches")

    def get_cache_stats(self):
        """Get cache statistics"""
        current_time = time.time()
        valid_entries = 0
        
        for cache_key, timestamp in self._cache_timestamps.items():
            if (current_time - timestamp) < self._cache_ttl:
                valid_entries += 1
        
        stats = {
            'tick_cache_total': len(self._tick_size_cache),
            'instrument_cache_total': len(self._instrument_cache),
            'valid_cache_entries': valid_entries,
            'cache_hit_potential': f"{(valid_entries / max(1, len(self._cache_timestamps))) * 100:.1f}%"
        }
        
        return stats


class EnhancedSimulatedTrader:
   """Enhanced simulated trader with realistic tick size behavior"""
   
   def __init__(self):
       print("✅ Enhanced Simulated Trader initialized.")
       logger.info("Simulated trader initialized")
       self.simulated_orders = {}
       self.simulated_positions = {}
       self.logged_in = True
       self.session_start_time = datetime.now(timezone.utc)
       self.order_counter = 0
       self.connection_errors = 0
       
       # Simulate tick size cache for realism
       self._tick_size_cache = {}

   def login(self): 
       print("✅ [SIMULATED] Login successful.")
       logger.info("[SIMULATED] Login")
       self.logged_in = True
       return True
       
   def reconnect(self): 
       print("🔄 [SIMULATED] Reconnect called.")
       logger.info("[SIMULATED] Reconnect")
       return True
       
   def ensure_connection(self):
       return True
       
   def check_connection(self):
       return True
       
   def get_portfolio_value(self) -> float: 
       return 100000.0
       
   def get_buying_power(self) -> float: 
       return 50000.0

   def get_instruments_by_symbols(self, symbols):
       """Simulate instrument data retrieval"""
       if isinstance(symbols, str):
           symbols = [symbols]
       
       results = []
       for symbol in symbols:
           # Try to get real data first for simulation accuracy
           try:
               import robin_stocks.robinhood as r
               real_instruments = r.get_instruments_by_symbols([symbol])
               if real_instruments and len(real_instruments) > 0:
                   results.append(real_instruments[0])
                   continue
           except:
               pass
           
           # Fallback to simulated data
           results.append({
               'symbol': symbol,
               'min_tick_size': '0.05' if symbol.upper() in ['SPY', 'QQQ', 'IWM'] else '0.05',
               'name': f'Simulated {symbol}'
           })
       
       return results

   def get_quotes(self, symbols):
       """Simulate quotes with realistic data"""
       try:
           # Try to get real quotes for simulation accuracy
           import robin_stocks.robinhood as r
           real_quotes = r.get_quotes(symbols)
           if real_quotes:
               print(f"📊 [SIMULATED] Using real quotes for {symbols}")
               return real_quotes
       except:
           pass
       
       # Fallback to simulated quotes
       if isinstance(symbols, str):
           symbols = [symbols]
       
       import random
       quotes = []
       for symbol in symbols:
           # Simulate realistic price ranges
           if symbol.upper() in ['SPY']:
               base_price = 450.0
           elif symbol.upper() in ['QQQ']:
               base_price = 380.0
           elif symbol.upper() in ['AAPL']:
               base_price = 180.0
           else:
               base_price = 100.0
           
           simulated_price = base_price + random.uniform(-10, 10)
           quotes.append({
               'symbol': symbol,
               'last_trade_price': str(round(simulated_price, 2)),
               'bid_price': str(round(simulated_price - 0.05, 2)),
               'ask_price': str(round(simulated_price + 0.05, 2))
           })
       
       return quotes
       
   def get_instrument_tick_size(self, symbol: str) -> float: 
       """Simulate tick size with caching (matches real trader behavior)"""
       cache_key = f"tick_{symbol}"
       
       if cache_key in self._tick_size_cache:
           return self._tick_size_cache[cache_key]
       
       # Try to get real tick size for simulation accuracy
       try:
           instruments = self.get_instruments_by_symbols(symbol)
           if instruments and len(instruments) > 0 and instruments[0]:
               if 'min_tick_size' in instruments[0]:
                   tick_size = float(instruments[0]['min_tick_size'])
                   self._tick_size_cache[cache_key] = tick_size
                   print(f"📏 [SIMULATED] Using real tick size for {symbol}: ${tick_size}")
                   return tick_size
       except:
           pass
       
       # Fallback to realistic defaults
       if symbol.upper() in ['SPX', 'SPY', 'QQQ', 'IWM']:
           tick_size = 0.05
       else:
           tick_size = 0.05
       
       self._tick_size_cache[cache_key] = tick_size
       print(f"📏 [SIMULATED] Using default tick size for {symbol}: ${tick_size}")
       return tick_size
       
   def round_to_tick(self, price: float, symbol: str, round_up: bool = False) -> float:
       """Simulate proper tick rounding"""
       tick_size = self.get_instrument_tick_size(symbol)
       if tick_size == 0:
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
       
   def validate_order_requirements(self, *args): 
       return True

   def get_option_order_info(self, order_id):
       """Simulate order progression"""
       if order_id in self.simulated_orders:
           # Simulate order progression
           order = self.simulated_orders[order_id]
           if order.get('state') == 'confirmed':
               order['state'] = 'filled'
               logger.debug(f"[SIMULATED] Order {order_id} filled")
           return order
       return {'state': 'filled', 'id': order_id}

   def find_open_option_position(self, all_positions, symbol, strike, expiration, opt_type):
       """Find simulated position"""
       pos_key = f"{str(symbol).upper()}_{float(strike):.2f}_{str(expiration)}_{str(opt_type).lower()}"
       position = self.simulated_positions.get(pos_key)
       if position:
           print(f"✅ [SIMULATED] Found position: {symbol} ${strike}{opt_type.upper()}")
           logger.debug(f"[SIMULATED] Position found: {pos_key}")
       return position

   def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
       """Simulate order cancellation"""
       print(f"🚫 [SIMULATED] Cancelling orders for {symbol} ${strike}{opt_type.upper()}")
       logger.info(f"[SIMULATED] Cancelling orders for {symbol}")
       return 1

   def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
       """Simulate buy order with PROPER tick rounding"""
       self.order_counter += 1
       
       # ENHANCED: Use proper tick rounding like real trader
       rounded_price = self.round_to_tick(limit_price, symbol, round_up=True)
       order_id = f"sim_buy_{self.order_counter}_{uuid.uuid4().hex[:8]}"
       
       tick_size = self.get_instrument_tick_size(symbol)
       summary = f"[SIMULATED] BUY {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f} (tick: ${tick_size})"
       
       self.simulated_orders[order_id] = {
           "id": order_id, 
           "state": "confirmed", 
           "detail": summary,
           "symbol": symbol,
           "quantity": quantity,
           "price": rounded_price
       }
       
       # Add to positions
       pos_key = f"{str(symbol).upper()}_{float(strike):.2f}_{str(expiration)}_{str(opt_type).lower()}"
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
               "entry_price": rounded_price,
               "chain_symbol": symbol,
               "option": f"https://simulated.url/{pos_key}"
           }
       
       print(summary)
       logger.info(f"[SIMULATED] Buy order placed: {order_id}")
       return {"detail": summary, "id": order_id}

   def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
       """Simulate stop loss order with PROPER tick rounding"""
       self.order_counter += 1
       
       # ENHANCED: Use proper tick rounding
       rounded_stop = self.round_to_tick(stop_price, symbol, round_up=False)
       order_id = f"sim_stop_{self.order_counter}_{uuid.uuid4().hex[:8]}"
       tick_size = self.get_instrument_tick_size(symbol)
       summary = f"🛡️ [SIMULATED] STOP-LOSS for {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${rounded_stop:.2f} (tick: ${tick_size})"
       
       print(summary)
       logger.info(f"[SIMULATED] Stop loss placed: {order_id}")
       return {"detail": summary, "id": order_id}

   def get_open_option_positions(self):
       """Return simulated positions in Robinhood format"""
       positions = []
       for pos_key, pos_data in self.simulated_positions.items():
           if float(pos_data.get('quantity', 0)) > 0:
               positions.append({
                   'chain_symbol': pos_data['symbol'],
                   'quantity': pos_data['quantity'],
                   'option': pos_data.get('option', f"https://simulated.url/{pos_key}")
               })
       logger.debug(f"[SIMULATED] Returning {len(positions)} positions")
       return positions

   def get_all_open_option_orders(self):
       """Return simulated open orders"""
       orders = [order for order in self.simulated_orders.values() 
                if order.get('state') in ['confirmed', 'queued', 'unconfirmed']]
       logger.debug(f"[SIMULATED] Returning {len(orders)} open orders")
       return orders

   def cancel_option_order(self, order_id):
       """Simulate order cancellation"""
       if order_id in self.simulated_orders:
           self.simulated_orders[order_id]['state'] = 'cancelled'
           print(f"🚫 [SIMULATED] Cancelled order: {order_id}")
           logger.info(f"[SIMULATED] Order cancelled: {order_id}")
       return {"detail": "cancelled"}

   def get_option_instrument_data(self, url):
       """Simulate instrument data from URL"""
       # Extract data from simulated URL
       if isinstance(url, str) and '/' in url:
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
       """Simulate realistic market data with proper tick alignment"""
       try:
           # Try to get real market data first (for simulation realism)
           import robin_stocks.robinhood as r
           real_data = r.get_option_market_data(symbol, expiration, strike, opt_type)
           if real_data:
               print(f"📊 [SIMULATED] Using real market data for {symbol}")
               logger.debug(f"[SIMULATED] Using real market data for {symbol}")
               return real_data
       except:
           pass
       
       # Fallback to simulated data with PROPER tick alignment
       import random
       
       tick_size = self.get_instrument_tick_size(symbol)
       
       # Generate realistic option prices
       base_price = 2.50
       spread = 0.20
       
       # Ensure prices are tick-aligned
       bid_raw = base_price - spread/2 + random.uniform(-0.20, 0.20)
       ask_raw = base_price + spread/2 + random.uniform(-0.20, 0.20)
       
       bid = self.round_to_tick(max(bid_raw, tick_size), symbol, round_up=False)
       ask = self.round_to_tick(max(ask_raw, bid + tick_size), symbol, round_up=True)
       mark = self.round_to_tick((bid + ask) / 2, symbol, round_up=False)
       
       print(f"📊 [SIMULATED] Using tick-aligned mock data for {symbol} (tick: ${tick_size})")
       logger.debug(f"[SIMULATED] Mock market data for {symbol}")
       return [{
           'bid_price': str(bid), 
           'ask_price': str(ask), 
           'mark_price': str(mark),
           'volume': str(random.randint(100, 1000)),
           'open_interest': str(random.randint(500, 5000))
       }]

   def get_session_info(self):
       """Get simulated session info"""
       return {
           "logged_in": True,
           "session_start": self.session_start_time,
           "last_heartbeat": datetime.now(timezone.utc),
           "connection_errors": 0,
           "session_duration": (datetime.now(timezone.utc) - self.session_start_time).total_seconds() / 3600,
           "mode": "SIMULATION",
           "tick_cache_size": len(self._tick_size_cache),
           "simulated_positions": len(self.simulated_positions),
           "simulated_orders": len(self.simulated_orders)
       }

   def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
       """Simulate sell order with ENHANCED tick rounding and minimum premium protection"""
       self.order_counter += 1
       
       # Use provided padding or default
       if sell_padding is None:
           sell_padding = DEFAULT_SELL_PRICE_PADDING
           
       # Simulate market-based pricing
       if not limit_price or limit_price <= 0:
           # Get simulated market price
           market_data = self.get_option_market_data(symbol, expiration, strike, opt_type)
           if market_data and len(market_data) > 0:
               data = market_data[0]
               mark_price = data.get('mark_price')
               if mark_price:
                   limit_price = float(mark_price)
               else:
                   limit_price = 2.50  # Default simulation price
           else:
               limit_price = 2.50
           print(f"📊 [SIMULATED] Using simulated market price: ${limit_price:.2f}")
       
       # Apply padding
       sell_price_raw = limit_price * (1 - sell_padding)
       
       # ENHANCED: Round to tick with minimum premium protection (SAME AS REAL TRADER)
       tick_size = self.get_instrument_tick_size(symbol)
       sell_price = self.round_to_tick(sell_price_raw, symbol, round_up=False)
       
       # Ensure minimum tick premium cost (SAME AS BUY LOGIC)
       min_premium = max(tick_size, 0.05)  # Same minimum as buy logic  
       final_price = max(sell_price, min_premium)
       
       order_id = f"sim_sell_{self.order_counter}_{uuid.uuid4().hex[:8]}"
       summary = f"[SIMULATED] SELL {quantity}x {symbol} ${strike}{opt_type.upper()} @ ${final_price:.2f} (market-based, padding: {sell_padding*100:.1f}%, tick: ${tick_size}, min: ${min_premium:.2f})"
       
       # Update positions
       pos_key = f"{str(symbol).upper()}_{float(strike):.2f}_{str(expiration)}_{str(opt_type).lower()}"
       if pos_key in self.simulated_positions:
           current_qty = float(self.simulated_positions[pos_key]['quantity'])
           new_qty = current_qty - float(quantity)
           if new_qty < 0.01:
               del self.simulated_positions[pos_key]
               print(f"🔴 [SIMULATED] Closed position: {symbol}")
               logger.info(f"[SIMULATED] Position closed: {symbol}")
           else:
               self.simulated_positions[pos_key]['quantity'] = str(new_qty)
               print(f"🟡 [SIMULATED] Trimmed position: {symbol} ({new_qty} remaining)")
               logger.info(f"[SIMULATED] Position trimmed: {symbol} ({new_qty} remaining)")
       
       print(summary)
       logger.info(f"[SIMULATED] Sell order placed: {order_id}")
       return {"detail": summary, "id": order_id}

   def clear_cache(self):
       """Clear simulated caches"""
       self._tick_size_cache.clear()
       print("🧹 [SIMULATED] Cleared all trader caches")
       logger.info("[SIMULATED] Cleared all trader caches")

   def get_cache_stats(self):
       """Get simulated cache statistics"""
       return {
           'tick_cache_total': len(self._tick_size_cache),
           'instrument_cache_total': 0,  # Not implemented in sim
           'valid_cache_entries': len(self._tick_size_cache),
           'cache_hit_potential': "100.0% (simulated)",
           'mode': 'SIMULATION'
       }


# Create aliases for backwards compatibility
RobinhoodTrader = EnhancedRobinhoodTrader
SimulatedTrader = EnhancedSimulatedTrader

# Export all classes
__all__ = ['EnhancedRobinhoodTrader', 'EnhancedSimulatedTrader', 'RobinhoodTrader', 'SimulatedTrader']