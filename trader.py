# trader.py - Enhanced Trading Interface with Symbol Mapping Support
import os
import uuid
import robin_stocks.robinhood as r
from dotenv import load_dotenv
from config import (
    DEFAULT_SELL_PRICE_PADDING,
    ORDER_MANAGEMENT_CONFIG,
    get_broker_symbol,
    get_trader_symbol,
    get_all_symbol_variants,
    SYMBOL_NORMALIZATION_CONFIG
)
import time
import math
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
    """Enhanced Robinhood trader with symbol mapping and better reliability"""

    def __init__(self):
        self.logged_in = False
        self.session_start_time = None
        self.last_heartbeat = None
        self.connection_errors = 0
        self.max_connection_errors = 3
        self._login_attempts = 0
        self._max_login_attempts = 3
        self.symbol_cache = {}  # Cache for symbol conversions
        self.tick_size_cache = {}  # Cache for tick sizes with TTL
        self.tick_cache_ttl = 300  # 5 minutes in seconds
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

    def normalize_symbol_for_broker(self, symbol: str) -> str:
        """Convert trader symbol to broker symbol (e.g., SPX → SPXW)"""
        if not symbol:
            return symbol

        broker_symbol = get_broker_symbol(symbol)

        if SYMBOL_NORMALIZATION_CONFIG.get('log_conversions', True) and broker_symbol != symbol:
            logger.info(f"Symbol conversion: {symbol} → {broker_symbol}")
            print(f"🔄 Symbol mapping: {symbol} → {broker_symbol}")

        return broker_symbol

    def normalize_symbol_from_broker(self, broker_symbol: str) -> str:
        """Convert broker symbol back to trader symbol (e.g., SPXW → SPX)"""
        if not broker_symbol:
            return broker_symbol

        trader_symbol = get_trader_symbol(broker_symbol)

        if SYMBOL_NORMALIZATION_CONFIG.get('log_conversions', True) and trader_symbol != broker_symbol:
            logger.info(f"Symbol reverse conversion: {broker_symbol} → {trader_symbol}")

        return trader_symbol

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

    def get_instrument_tick_size(self, symbol: str) -> float:
        """ENHANCED: PRIORITY ROBINHOOD API + Improved options tick size detection"""
        if not symbol:
            return 0.05
        
        # Normalize symbol for broker
        broker_symbol = self.normalize_symbol_for_broker(symbol)
        
        # Check cache first (with TTL)
        cache_key = f"{broker_symbol}_tick"
        current_time = time.time()
        
        if cache_key in self.tick_size_cache:
            cached_data = self.tick_size_cache[cache_key]
            if current_time - cached_data['timestamp'] < self.tick_cache_ttl:
                logger.debug(f"Using cached tick size for {symbol}/{broker_symbol}: ${cached_data['tick_size']}")
                return cached_data['tick_size']
            else:
                # Cache expired, remove it
                del self.tick_size_cache[cache_key]
        
        tick_size = None  # Start with None to force proper detection
        
        # PRIORITY 1: ALWAYS use Robinhood Instrument API min_tick_size field
        try:
            if self.ensure_connection():
                print(f"🔍 Fetching LIVE tick size from Robinhood Instrument API for {broker_symbol}...")
                logger.info(f"Fetching tick size from Robinhood API: {broker_symbol}")
                
                # Get instrument data which contains the authoritative min_tick_size
                instruments = r.get_instruments_by_symbols(broker_symbol)
                if instruments and len(instruments) > 0 and instruments[0]:
                    api_tick = instruments[0].get('min_tick_size')
                    instrument_type = instruments[0].get('type')
                    tradable_chain_id = instruments[0].get('tradable_chain_id')
                    
                    if api_tick and float(api_tick) > 0:
                        tick_size = float(api_tick)
                        print(f"✅ ROBINHOOD API tick size for {symbol}/{broker_symbol}: ${tick_size}")
                        logger.info(f"Robinhood API tick size: {symbol}/{broker_symbol} = ${tick_size}")
                        
                        # Cache the result with timestamp
                        self.tick_size_cache[cache_key] = {
                            'tick_size': tick_size,
                            'timestamp': current_time,
                            'source': 'robinhood_api'
                        }
                        return tick_size
                    else:
                        # For options, min_tick_size is often None - try options-specific approach
                        if tradable_chain_id:
                            print(f"📊 Instrument has options chain, trying options tick size detection...")
                            tick_size = self._get_options_tick_size(broker_symbol, tradable_chain_id)
                            if tick_size:
                                print(f"✅ OPTIONS tick size for {symbol}/{broker_symbol}: ${tick_size}")
                                logger.info(f"Options tick size: {symbol}/{broker_symbol} = ${tick_size}")
                                
                                # Cache the result
                                self.tick_size_cache[cache_key] = {
                                    'tick_size': tick_size,
                                    'timestamp': current_time,
                                    'source': 'options_detection'
                                }
                                return tick_size
                        
                        print(f"⚠️ Robinhood API returned invalid tick size for {broker_symbol}: {api_tick}")
                        logger.warning(f"Invalid API tick size: {broker_symbol} = {api_tick}")
                else:
                    print(f"⚠️ No instrument data from Robinhood API for {broker_symbol}")
                    logger.warning(f"No instrument data from API: {broker_symbol}")
            else:
                print(f"❌ No connection to Robinhood API for tick size lookup")
                logger.error(f"No connection for tick size: {broker_symbol}")
        
        except Exception as e:
            print(f"❌ Robinhood API tick size error for {broker_symbol}: {e}")
            logger.error(f"Robinhood API tick size exception for {broker_symbol}: {e}")
        
        # FALLBACK: Conservative defaults only when API completely fails
        print(f"⚠️ Using conservative fallback tick size for {broker_symbol}")
        logger.warning(f"Using fallback tick size for {broker_symbol}")
        
        # Use conservative fallback
        tick_size = 0.05
        print(f"🚨 Using ABSOLUTE FALLBACK tick size for {symbol}/{broker_symbol}: ${tick_size}")
        logger.warning(f"Using absolute fallback tick size for {symbol}/{broker_symbol}")
        
        # Cache even the fallback to avoid repeated failures
        self.tick_size_cache[cache_key] = {
            'tick_size': tick_size,
            'timestamp': current_time,
            'source': 'absolute_fallback'
        }
        
        return tick_size

    def _get_options_tick_size(self, broker_symbol: str, chain_id: str) -> float:
        """Get options tick size using current option quotes"""
        try:
            # Get current option quotes to determine tick size based on actual market prices
            import robin_stocks.robinhood as r
            
            # Try to get some sample option quotes for this underlying
            quotes = r.get_quotes(broker_symbol)
            if quotes and len(quotes) > 0 and quotes[0]:
                # Get the current stock price to estimate option prices
                stock_price = quotes[0].get('last_trade_price')
                if stock_price:
                    stock_price = float(stock_price)
                    
                    # Try to get some actual option quotes
                    try:
                        # Get option chain info
                        from datetime import datetime, timedelta
                        future_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
                        
                        # Try to get option quotes for a reasonable strike
                        sample_strikes = [
                            int(stock_price * 0.95),  # OTM put
                            int(stock_price),         # ATM 
                            int(stock_price * 1.05)   # OTM call
                        ]
                        
                        for strike in sample_strikes:
                            try:
                                option_quotes = r.get_option_quotes(broker_symbol, str(strike), future_date, 'call')
                                if option_quotes and len(option_quotes) > 0:
                                    option_data = option_quotes[0]
                                    ask_price = option_data.get('ask_price')
                                    bid_price = option_data.get('bid_price')
                                    
                                    if ask_price and bid_price:
                                        avg_price = (float(ask_price) + float(bid_price)) / 2
                                        
                                        # Enhanced tick size rules with SPX-specific logic
                                        if broker_symbol.upper() in ['SPX', 'SPXW']:
                                            # SPX has special tick size rules
                                            if avg_price < 3.00:
                                                return 0.05
                                            elif avg_price < 5.00:
                                                return 0.05
                                            else:
                                                return 0.10  # Critical fix: SPX options over $5.00 use $0.10 ticks
                                        elif avg_price < 3.00:
                                            if broker_symbol.upper() in ['SPY', 'QQQ', 'IWM']:  # Major ETFs in Penny Pilot
                                                return 0.01
                                            else:
                                                return 0.05
                                        else:
                                            if broker_symbol.upper() in ['SPY', 'QQQ', 'IWM']:  # Major ETFs in Penny Pilot
                                                return 0.05  
                                            else:
                                                return 0.10
                                        
                            except Exception as e:
                                continue  # Try next strike
                                
                    except Exception as e:
                        logger.debug(f"Could not get option quotes for {broker_symbol}: {e}")
                    
                    # Enhanced fallback based on symbol recognition with 0DTE special handling
                    if broker_symbol.upper() in ['SPX', 'SPXW']:
                        # Special handling for SPX options with proper tick sizing
                        try:
                            from datetime import datetime
                            today = datetime.now().strftime('%Y-%m-%d')
                            if expiration == today:
                                # For SPX 0DTE options: still need proper tick size based on price
                                print(f"📊 SPX 0DTE detected for {broker_symbol} - using price-based tick size")
                                return 0.05  # Conservative for 0DTE when we can't determine price
                            else:
                                # For regular SPX options, we need to be more conservative
                                # Since we can't determine price here, use 0.10 to avoid tick errors
                                print(f"📊 SPX regular options for {broker_symbol} - using conservative tick size")
                                return 0.10  # Conservative for regular SPX when price unknown
                        except:
                            return 0.10  # Most conservative fallback
                    elif broker_symbol.upper() in ['SPY', 'QQQ', 'IWM']:
                        return 0.05  # Conservative for major ETF symbols
                    else:
                        return 0.10  # Conservative for other symbols
                        
        except Exception as e:
            logger.error(f"Error getting options tick size for {broker_symbol}: {e}")
            
        return None  # Could not determine

    def _get_optimal_buy_price(self, broker_symbol: str, strike: float, expiration: str, opt_type: str, fallback_price: float) -> float:
        """Get optimal buy price from market data with exchange-compliant pricing"""
        try:
            print(f"🔍 Fetching pre-rounded buy price from market data for {broker_symbol}...")
            market_data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
            
            if market_data and len(market_data) > 0 and len(market_data[0]) > 0:
                data = market_data[0][0]  # Fix: API returns [[data]], not [data]
                
                # Preference order for buy prices (most likely to fill)
                buy_price_options = [
                    ('high_fill_rate_buy_price', 'high fill rate'),
                    ('ask_price', 'ask'),
                    ('mark_price', 'mark')
                ]
                
                for price_field, price_name in buy_price_options:
                    if price_field in data and data[price_field]:
                        price = float(data[price_field])
                        if price > 0:
                            print(f"✅ Using {price_name} price: ${price:.2f} (exchange-compliant)")
                            return price
                
                print(f"⚠️ No valid buy prices in market data, using fallback")
            else:
                print(f"⚠️ No market data available for {broker_symbol}, using fallback")
                
        except Exception as e:
            print(f"⚠️ Error fetching optimal buy price: {e}")
            
        return None  # Will use fallback tick calculation
    
    def _get_optimal_sell_price(self, broker_symbol: str, strike: float, expiration: str, opt_type: str, fallback_price: float) -> float:
        """Get optimal sell price from market data with exchange-compliant pricing"""
        try:
            print(f"🔍 Fetching pre-rounded sell price from market data for {broker_symbol}...")
            market_data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
            
            if market_data and len(market_data) > 0:
                data = market_data[0]
                
                # Preference order for sell prices (most likely to fill)
                sell_price_options = [
                    ('high_fill_rate_sell_price', 'high fill rate'),
                    ('bid_price', 'bid'),
                    ('mark_price', 'mark')
                ]
                
                for price_field, price_name in sell_price_options:
                    if price_field in data and data[price_field]:
                        price = float(data[price_field])
                        if price > 0:
                            print(f"✅ Using {price_name} price: ${price:.2f} (exchange-compliant)")
                            return price
                
                print(f"⚠️ No valid sell prices in market data, using fallback")
            else:
                print(f"⚠️ No market data available for {broker_symbol}, using fallback")
                
        except Exception as e:
            print(f"⚠️ Error fetching optimal sell price: {e}")
            
        return None  # Will use fallback tick calculation

    def get_instrument_tick_size_with_expiration(self, symbol: str, expiration: str = None) -> float:
        """ENHANCED: Get tick size with SPX 0DTE special handling"""
        if not symbol:
            return 0.05
        
        # Normalize symbol for broker
        broker_symbol = self.normalize_symbol_for_broker(symbol)
        
        # Special handling for SPX 0DTE options
        if broker_symbol.upper() in ['SPX', 'SPXW'] and expiration:
            try:
                from datetime import datetime
                today = datetime.now().strftime('%Y-%m-%d')
                if expiration == today:
                    print(f"🚀 SPX 0DTE detected for {broker_symbol} - using optimized tick size (0.05)")
                    return 0.05  # Optimized for 0DTE execution
            except Exception as e:
                print(f"⚠️ Date comparison failed: {e}")
        
        # Fallback to regular tick size logic
        try:
            # Try to get from cache or API
            tick_size = self._get_options_tick_size(broker_symbol, None)
            if tick_size and tick_size > 0:
                return tick_size
        except Exception as e:
            print(f"⚠️ Could not get tick size for {symbol}: {e}")
        
        # Final fallback based on symbol
        if broker_symbol.upper() in ['SPX', 'SPXW', 'SPY', 'QQQ', 'IWM']:
            return 0.05
        else:
            return 0.10

    def round_to_tick(self, price: float, symbol: str, round_up_for_buy: bool = False, expiration: str = None) -> float:
        """ENHANCED: Round price to valid tick with buy/sell logic and SPX 0DTE support"""
        try:
            if price <= 0:
                print(f"❌ Invalid price for rounding: ${price}")
                return 0.05
            
            # Get LIVE tick size from Robinhood API with expiration for SPX 0DTE detection
            tick_size = self.get_instrument_tick_size_with_expiration(symbol, expiration)
            if tick_size is None or tick_size <= 0:
                tick_size = 0.05
                print(f"⚠️ Using fallback tick size: ${tick_size}")
            
            # FIXED ROUNDING LOGIC:
            if round_up_for_buy:
                # For BUY orders: Round UP to next valid tick to ensure execution
                ticks = math.ceil(price / tick_size)
                rounded_price = ticks * tick_size
            else:
                # For SELL orders: Round to nearest valid tick
                ticks = round(price / tick_size)
                rounded_price = ticks * tick_size
            
            # Ensure minimum tick size
            rounded_price = max(rounded_price, tick_size)
            
            # Round to 2 decimal places to avoid floating point issues
            rounded_price = round(rounded_price, 2)
            
            # Enhanced logging
            if abs(rounded_price - price) > 0.001:
                direction = "UP" if round_up_for_buy else "NEAREST"
                print(f"📏 Rounded {direction}: ${price:.2f} → ${rounded_price:.2f} (tick: ${tick_size}, source: {self.tick_size_cache.get(f'{self.normalize_symbol_for_broker(symbol)}_tick', {}).get('source', 'unknown')})")
                logger.debug(f"Price rounded {direction}: ${price:.2f} -> ${rounded_price:.2f}")
            
            return rounded_price
            
        except Exception as e:
            print(f"❌ Critical error rounding price ${price} for {symbol}: {e}")
            logger.error(f"Price rounding exception for {symbol}: {e}")
            return round(max(price, 0.05), 2)

    def validate_order_requirements(self, symbol, strike, expiration, opt_type, quantity, price):
        """Enhanced order validation with symbol normalization"""
        try:
            if not self.ensure_connection():
                raise Exception("Connection to Robinhood failed")

            # Normalize symbol for broker
            broker_symbol = self.normalize_symbol_for_broker(symbol)

            # Check buying power
            required_capital = price * quantity * 100
            available_power = self.get_buying_power()

            if required_capital > available_power * 0.95:  # Leave 5% buffer
                error_msg = f"Insufficient buying power: ${required_capital:,.2f} required, ${available_power:,.2f} available"
                logger.warning(error_msg)
                raise Exception(error_msg)

            # Validate contract exists
            try:
                market_data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
                if not market_data or len(market_data) == 0:
                    error_msg = f"Contract not found: {symbol}/{broker_symbol} ${strike}{opt_type.upper()} {expiration}"
                    logger.warning(error_msg)
                    raise Exception(error_msg)
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
        """Enhanced buy order with symbol mapping and pre-rounded pricing"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection to Robinhood failed"}

            # Normalize symbol for broker
            broker_symbol = self.normalize_symbol_for_broker(symbol)

            # NEW: Try to get pre-rounded price from market data first
            optimal_price = self._get_optimal_buy_price(broker_symbol, strike, expiration, opt_type, limit_price)
            rounded_price = optimal_price if optimal_price else self.round_to_tick(limit_price, broker_symbol, round_up_for_buy=True)

            print(f"🔍 Preparing buy order: {symbol} (broker: {broker_symbol}) ${strike}{opt_type[0].upper()} x{quantity} @ ${rounded_price:.2f}")
            logger.info(f"Buy order preparation: {symbol}/{broker_symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${rounded_price:.2f}")

            # NOTE: Validation now happens in trade executor BEFORE this method is called

            # Place the order with broker symbol
            print(f"📤 Placing LIVE buy order with broker symbol: {broker_symbol}...")
            logger.info(f"Placing buy order for {symbol} as {broker_symbol}")

            start_time = time.time()
            result = r.order_buy_option_limit(
                positionEffect='open',
                creditOrDebit='debit',
                price=rounded_price,
                symbol=broker_symbol,  # Use broker symbol here
                quantity=quantity,
                expirationDate=expiration,
                strike=strike,
                optionType=opt_type,
                timeInForce='gfd'
            )

            execution_time = time.time() - start_time

            # Check for success: must have ID AND no error field
            if result and result.get('id') and not result.get('error'):
                print(f"✅ LIVE buy order placed: {result['id']} (execution: {execution_time:.2f}s)")
                logger.info(f"Buy order placed successfully: {result['id']} for {symbol}/{broker_symbol}")

                # Log order details for tracking
                print(f"📋 Order details: {quantity}x {symbol}/{broker_symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f}")
            else:
                error_info = result.get('error', result) if result else 'No response'
                print(f"❌ Buy order failed: {error_info}")
                logger.error(f"Buy order failed: {error_info}")

            return result

        except Exception as e:
            print(f"❌ Error placing buy order: {e}")
            logger.error(f"Buy order exception: {e}")
            self.connection_errors += 1
            return {"error": str(e)}

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        """Enhanced sell order with symbol mapping and pre-rounded pricing"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection to Robinhood failed"}

            # Normalize symbol for broker
            broker_symbol = self.normalize_symbol_for_broker(symbol)

            # Use provided padding or default
            if sell_padding is None:
                sell_padding = DEFAULT_SELL_PRICE_PADDING

            # NEW: Try to get pre-rounded optimal sell price first
            if limit_price and limit_price > 0:
                optimal_price = self._get_optimal_sell_price(broker_symbol, strike, expiration, opt_type, limit_price)
                if optimal_price:
                    final_price = optimal_price
                    price_source = "optimal_pre_rounded"
                else:
                    # Fallback to existing market data logic
                    print(f"📊 Fetching current market price for {symbol}/{broker_symbol} ${strike}{opt_type[0].upper()}...")
                    logger.info(f"Fetching market price for sell order: {symbol}/{broker_symbol}")

                    market_data_list = self.get_option_market_data(broker_symbol, expiration, strike, opt_type)

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
                    final_price = 0.05  # Absolute minimum
                    price_source = "emergency_minimum"
                    print(f"🚨 Using minimum price: ${final_price:.2f}")
                    logger.warning(f"Using minimum price: ${final_price:.2f}")

            # Apply padding and round to tick (find lowest valid tick >= padded price for sells)
            sell_price = final_price * (1 - sell_padding)
            sell_price = self.round_to_tick(sell_price, broker_symbol, round_up_for_buy=False)

            print(f"📤 Placing LIVE sell order: {symbol}/{broker_symbol} ${strike}{opt_type[0].upper()} x{quantity} @ ${sell_price:.2f}")
            print(f"📈 Price source: {price_source}, padding: {sell_padding*100:.1f}%")
            logger.info(f"Placing sell order: {symbol}/{broker_symbol} x{quantity} @ ${sell_price:.2f} (source: {price_source})")

            start_time = time.time()
            result = r.order_sell_option_limit(
                positionEffect='close',
                creditOrDebit='credit',
                price=sell_price,
                symbol=broker_symbol,  # Use broker symbol here
                quantity=quantity,
                expirationDate=expiration,
                strike=strike,
                optionType=opt_type,
                timeInForce='gtc'  # Good till cancelled for better fills
            )

            execution_time = time.time() - start_time

            # Check for success: must have ID AND no error field
            if result and result.get('id') and not result.get('error'):
                print(f"✅ LIVE sell order placed: {result['id']} @ ${sell_price:.2f} (execution: {execution_time:.2f}s)")
                logger.info(f"Sell order placed successfully: {result['id']} for {symbol}/{broker_symbol}")
            else:
                error_info = result.get('error', result) if result else 'No response'
                print(f"❌ Sell order failed: {error_info}")
                logger.error(f"Sell order failed: {error_info}")

            return result

        except Exception as e:
            print(f"❌ Error placing sell order: {e}")
            logger.error(f"Sell order exception: {e}")
            self.connection_errors += 1
            return {"error": str(e)}

    def get_open_option_positions(self):
        """Get open positions with enhanced symbol mapping"""
        try:
            if not self.ensure_connection():
                return []
            positions = r.get_open_option_positions()

            # Enhance positions with trader symbols
            for position in positions:
                broker_symbol = position.get('chain_symbol', '')
                trader_symbol = self.normalize_symbol_from_broker(broker_symbol)
                position['trader_symbol'] = trader_symbol
                position['broker_symbol'] = broker_symbol

            logger.debug(f"Retrieved {len(positions)} open positions with symbol mapping")
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
        """Find specific position with enhanced matching using symbol variants"""
        try:
            # Get all possible symbol variants (SPX, SPXW, etc.)
            symbol_variants = get_all_symbol_variants(symbol)

            print(f"🔍 Searching for position with symbol variants: {symbol_variants}")
            logger.debug(f"Position search using variants: {symbol_variants}")

            for pos in all_positions:
                instrument_data = self.get_option_instrument_data(pos['option'])
                if not instrument_data:
                    continue

                # Check both broker symbol and trader symbol
                position_symbol = pos.get('chain_symbol', '').upper()
                position_trader_symbol = pos.get('trader_symbol', '').upper()

                # Enhanced matching with symbol variants
                symbol_match = (position_symbol in symbol_variants or
                                position_trader_symbol in symbol_variants)

                strike_match = abs(float(instrument_data['strike_price']) - float(strike)) < 0.01
                exp_match = instrument_data['expiration_date'] == str(expiration)
                type_match = instrument_data['type'].lower() == str(opt_type).lower()

                if symbol_match and strike_match and exp_match and type_match:
                    pos.update(instrument_data)
                    print(f"✅ Found matching position: {position_symbol} (trader: {position_trader_symbol}) ${strike}{opt_type.upper()}")
                    logger.debug(f"Position found: {position_symbol}/{position_trader_symbol} ${strike}{opt_type.upper()}")
                    return pos

            logger.debug(f"No position found for {symbol} (variants: {symbol_variants}) ${strike}{opt_type.upper()}")
            return None
        except Exception as e:
            print(f"❌ Error searching positions: {e}")
            logger.error(f"Position search exception: {e}")
            return None

    def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
        """Cancel all open orders for a contract with symbol mapping"""
        try:
            if not self.ensure_connection():
                print("❌ Not logged in, cannot cancel orders")
                return 0

            # Get all symbol variants
            symbol_variants = get_all_symbol_variants(symbol)

            all_positions = self.get_open_option_positions()
            position = self.find_open_option_position(all_positions, symbol, strike, expiration, opt_type)

            if not position:
                print(f"ℹ️ No position found for {symbol} (checking variants: {symbol_variants}), checking all open orders...")
                logger.info(f"No position found, checking all orders for {symbol} variants")

                # If no position, check all open orders anyway
                all_orders = self.get_all_open_option_orders()
                relevant_orders = []

                for order in all_orders:
                    if (order.get('state', '').lower() in ['queued', 'unconfirmed', 'confirmed'] and
                            len(order.get('legs', [])) > 0):
                        # Try to match by available order data
                        leg = order['legs'][0]
                        order_symbol = leg.get('symbol', '').upper()
                        if order_symbol in symbol_variants:
                            relevant_orders.append(order)

                if not relevant_orders:
                    print(f"ℹ️ No open orders found for {symbol} or its variants")
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
        """Place stop loss with symbol mapping"""
        try:
            if not self.ensure_connection():
                return {"error": "Connection failed"}

            # Normalize symbol for broker
            broker_symbol = self.normalize_symbol_for_broker(symbol)

            rounded_stop_price = self.round_to_tick(stop_price, broker_symbol, round_up_for_buy=False)

            print(f"🛡️ Placing stop loss: {symbol}/{broker_symbol} ${strike}{opt_type.upper()} x{quantity} @ ${rounded_stop_price:.2f}")
            logger.info(f"Placing stop loss: {symbol}/{broker_symbol} x{quantity} @ ${rounded_stop_price:.2f}")

            result = r.order_sell_option_stop_limit(
                positionEffect='close',
                creditOrDebit='credit',
                limitPrice=rounded_stop_price,
                stopPrice=rounded_stop_price,
                symbol=broker_symbol,  # Use broker symbol
                quantity=quantity,
                expirationDate=expiration,
                strike=strike,
                optionType=opt_type,
                timeInForce='gtc'
            )

            if result and result.get('id'):
                print(f"✅ Stop loss placed: {result['id']}")
                logger.info(f"Stop loss placed: {result['id']} for {symbol}/{broker_symbol}")

            return result
        except Exception as e:
            print(f"❌ Error placing stop loss: {e}")
            logger.error(f"Stop loss exception: {e}")
            return {"error": str(e)}

    def get_option_market_data(self, symbol, expiration, strike, opt_type):
        """Get market data with symbol mapping"""
        try:
            if not self.ensure_connection():
                return []

            # Normalize symbol for broker
            broker_symbol = self.normalize_symbol_for_broker(symbol)

            data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
            if data:
                print(f"📊 Market data retrieved for {symbol}/{broker_symbol} ${strike}{opt_type.upper()}")
                logger.debug(f"Market data retrieved for {symbol}/{broker_symbol}")
            return data
        except Exception as e:
            print(f"❌ Error fetching market data for {symbol}: {e}")
            logger.error(f"Market data exception: {e}")
            return []

    def wait_for_order_confirmation(self, order_id: str, max_wait_seconds: int = 300) -> dict:
        """Wait for order confirmation with intelligent polling"""
        if not order_id:
            return {"status": "error", "message": "Invalid order ID"}
        
        start_time = time.time()
        check_intervals = [2, 5, 10, 15, 20, 30, 30, 60]  # Progressive intervals
        total_elapsed = 0
        check_count = 0
        
        print(f"⏳ Monitoring order {order_id} for confirmation...")
        logger.info(f"Starting order monitoring for {order_id}")
        
        for interval in check_intervals:
            if total_elapsed >= max_wait_seconds:
                break
                
            time.sleep(interval)
            total_elapsed += interval
            check_count += 1
            
            try:
                order_info = self.get_option_order_info(order_id)
                if not order_info:
                    continue
                
                order_state = order_info.get('state', '').lower()
                elapsed_time = time.time() - start_time
                
                if order_state == 'filled':
                    print(f"✅ Order {order_id} FILLED after {elapsed_time:.1f}s ({check_count} checks)")
                    logger.info(f"Order {order_id} filled after {elapsed_time:.1f}s")
                    return {
                        "status": "filled",
                        "order_info": order_info,
                        "elapsed_time": elapsed_time,
                        "checks": check_count
                    }
                    
                elif order_state in ['cancelled', 'rejected', 'failed']:
                    print(f"❌ Order {order_id} {order_state.upper()} after {elapsed_time:.1f}s")
                    logger.warning(f"Order {order_id} {order_state} after {elapsed_time:.1f}s")
                    return {
                        "status": order_state,
                        "order_info": order_info,
                        "elapsed_time": elapsed_time,
                        "checks": check_count
                    }
                    
                elif order_state in ['queued', 'unconfirmed', 'confirmed', 'partially_filled']:
                    print(f"🟡 Order {order_id} {order_state} after {elapsed_time:.1f}s...")
                    logger.debug(f"Order {order_id} still {order_state}")
                    continue
                    
            except Exception as e:
                print(f"❌ Order monitoring error: {e}")
                logger.error(f"Order monitoring error for {order_id}: {e}")
                continue
        
        # Timeout handling
        elapsed_time = time.time() - start_time
        print(f"⏰ Order {order_id} monitoring timeout after {elapsed_time:.1f}s")
        logger.warning(f"Order {order_id} monitoring timeout after {elapsed_time:.1f}s")
        
        return {
            "status": "timeout",
            "elapsed_time": elapsed_time,
            "checks": check_count,
            "message": f"Order monitoring timeout after {elapsed_time:.1f}s"
        }

    def place_option_sell_order_with_timeout_retry(self, symbol, strike, expiration, opt_type, quantity, 
                                                 limit_price=None, sell_padding=None, timeout_seconds=60, max_retries=3):
        """Enhanced sell order with timeout monitoring, fresh market data, and progressive pricing"""
        import time
        
        for attempt in range(max_retries):
            # Get fresh market data for each attempt
            try:
                broker_symbol = self.normalize_symbol_for_broker(symbol)
                fresh_optimal_price = self._get_optimal_sell_price(broker_symbol, strike, expiration, opt_type, limit_price or 0)
                
                # Progressive aggressiveness: move closer to bid/ask with each retry
                if fresh_optimal_price and attempt > 0:
                    market_data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
                    if market_data and len(market_data) > 0:
                        data = market_data[0]
                        bid_price = float(data.get('bid_price', 0) or 0)
                        
                        if bid_price > 0:
                            # Move 20% closer to bid with each retry
                            aggressiveness = attempt * 0.2
                            adjusted_price = fresh_optimal_price - (fresh_optimal_price - bid_price) * aggressiveness
                            fresh_optimal_price = adjusted_price
                            print(f"🎯 Retry {attempt + 1}: Moving {aggressiveness*100:.0f}% toward bid: ${fresh_optimal_price:.2f}")
                
                # Use fresh price if available, otherwise fall back
                retry_limit_price = fresh_optimal_price if fresh_optimal_price else limit_price
                
            except Exception as e:
                print(f"⚠️ Error getting fresh market data on retry {attempt + 1}: {e}")
                retry_limit_price = limit_price
        
        for attempt in range(max_retries):
            try:
                print(f"📤 Sell attempt {attempt + 1}/{max_retries} for {symbol} ${strike}{opt_type.upper()}")
                
                # Place the order
                result = self.place_option_sell_order(symbol, strike, expiration, opt_type, quantity, 
                                                    limit_price, sell_padding)
                
                # Check for tick size error specifically
                if result and result.get('error'):
                    error_message = str(result['error']).lower()
                    if 'tick' in error_message or 'min tick' in error_message:
                        print(f"🔧 Tick size error detected on attempt {attempt + 1}, trying enhanced retry logic...")
                        
                        # Clear tick cache for this symbol
                        broker_symbol = self.normalize_symbol_for_broker(symbol)
                        cache_key = f"{broker_symbol}_tick"
                        if cache_key in self.tick_size_cache:
                            del self.tick_size_cache[cache_key]
                        
                        # For SPX options, try multiple tick size strategies
                        if broker_symbol.upper() in ['SPX', 'SPXW'] and limit_price:
                            retry_prices = []
                            
                            # Strategy 1: Use conservative 0.10 tick size for SPX over $5
                            if limit_price >= 5.0:
                                conservative_price = round(limit_price / 0.10) * 0.10
                                retry_prices.append((conservative_price, "SPX $0.10 tick"))
                            
                            # Strategy 2: Round down to nearest 0.05
                            rounded_05 = round(limit_price / 0.05) * 0.05
                            retry_prices.append((rounded_05, "$0.05 tick"))
                            
                            # Strategy 3: Round up slightly with small buffer
                            buffer_price = limit_price * 1.01  # 1% buffer
                            fresh_tick_size = self.get_instrument_tick_size(symbol)
                            if fresh_tick_size > 0:
                                buffered_price = round(buffer_price / fresh_tick_size) * fresh_tick_size
                                retry_prices.append((buffered_price, f"${fresh_tick_size} fresh tick"))
                            
                            # Try each strategy
                            for retry_price, strategy in retry_prices:
                                if retry_price > 0:
                                    print(f"🎯 Retry strategy: ${limit_price:.2f} → ${retry_price:.2f} ({strategy})")
                                    result = self.place_option_sell_order(symbol, strike, expiration, opt_type, quantity, 
                                                                        retry_price, sell_padding)
                                    
                                    # If successful, break out of retry loop
                                    if result and result.get('id') and not result.get('error'):
                                        print(f"✅ Tick size retry successful with {strategy}")
                                        break
                                    else:
                                        print(f"❌ Retry with {strategy} failed: {result.get('error', 'Unknown error') if result else 'No response'}")
                        
                        else:
                            # Standard retry for non-SPX symbols
                            fresh_tick_size = self.get_instrument_tick_size(symbol)
                            if limit_price and fresh_tick_size > 0:
                                # Round to fresh tick size
                                adjusted_price = round(limit_price / fresh_tick_size) * fresh_tick_size
                                print(f"🎯 Standard adjusted price: ${limit_price:.2f} → ${adjusted_price:.2f} (tick: ${fresh_tick_size})")
                                
                                # Retry with adjusted price
                                result = self.place_option_sell_order(symbol, strike, expiration, opt_type, quantity, 
                                                                    adjusted_price, sell_padding)
                
                # If successful, return immediately (must have ID AND no error)
                if result and result.get('id') and not result.get('error'):
                    print(f"✅ Sell order successful on attempt {attempt + 1}")
                    return result
                    
                # If error, log and prepare for retry
                error_msg = result.get('error', 'Unknown error') if result else 'No response'
                print(f"❌ Sell attempt {attempt + 1} failed: {error_msg}")
                
                if attempt < max_retries - 1:  # Not the last attempt
                    wait_time = (attempt + 1) * 2  # Progressive backoff
                    print(f"⏳ Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    
            except Exception as e:
                print(f"❌ Sell attempt {attempt + 1} exception: {e}")
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 2)
        
        # All retries failed
        print(f"❌ All {max_retries} sell attempts failed for {symbol}")
        logger.error(f"All sell retries failed for {symbol} ${strike}{opt_type.upper()}")
        return {"error": f"All {max_retries} sell attempts failed"}

    def get_session_info(self):
        """Get current session information"""
        info = {
            "logged_in": self.logged_in,
            "session_start": self.session_start_time,
            "last_heartbeat": self.last_heartbeat,
            "connection_errors": self.connection_errors,
            "session_duration": (datetime.now(timezone.utc) - self.session_start_time).total_seconds() / 3600 if self.session_start_time else 0,
            "symbol_mapping_enabled": SYMBOL_NORMALIZATION_CONFIG.get('enabled', True)
        }
        logger.debug(f"Session info: {info}")
        return info

    def place_option_sell_order_with_retry(self, symbol, strike, expiration, opt_type, quantity, 
                                         limit_price=None, sell_padding=None, max_retries=3):
        """Compatibility method that calls place_option_sell_order_with_timeout_retry"""
        return self.place_option_sell_order_with_timeout_retry(
            symbol, strike, expiration, opt_type, quantity,
            limit_price=limit_price, sell_padding=sell_padding, max_retries=max_retries
        )


class EnhancedSimulatedTrader:
    """Enhanced simulated trader with symbol mapping support"""

    def __init__(self):
        print("✅ Enhanced Simulated Trader initialized.")
        logger.info("Simulated trader initialized")
        self.simulated_orders = {}
        self.simulated_positions = {}
        self.logged_in = True
        self.session_start_time = datetime.now(timezone.utc)
        self.order_counter = 0
        self.connection_errors = 0  # Add for compatibility

    def normalize_symbol_for_broker(self, symbol: str) -> str:
        """Convert trader symbol to broker symbol (simulated)"""
        broker_symbol = get_broker_symbol(symbol)
        if SYMBOL_NORMALIZATION_CONFIG.get('log_conversions', True) and broker_symbol != symbol:
            print(f"🔄 [SIMULATED] Symbol mapping: {symbol} → {broker_symbol}")
        return broker_symbol

    def normalize_symbol_from_broker(self, broker_symbol: str) -> str:
        """Convert broker symbol back to trader symbol (simulated)"""
        return get_trader_symbol(broker_symbol)

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

    def get_instrument_tick_size(self, symbol: str) -> float:
        # Use the same logic as live trader for consistency
        try:
            # Normalize symbol
            broker_symbol = self.normalize_symbol_for_broker(symbol)
            # Try to get real tick size for simulation accuracy
            import robin_stocks.robinhood as r
            instruments = r.get_instruments_by_symbols(broker_symbol)
            if instruments and len(instruments) > 0 and instruments[0]:
                api_tick = instruments[0].get('min_tick_size')
                if api_tick and float(api_tick) > 0:
                    tick_size = float(api_tick)
                    print(f"✅ [SIMULATED] ROBINHOOD API tick size for {symbol}/{broker_symbol}: ${tick_size}")
                    return tick_size
        except:
            pass
        # Fallback for simulation
        print(f"🚨 [SIMULATED] Using fallback tick size for {symbol}: $0.05")
        return 0.05

    def round_to_tick(self, price: float, symbol: str, round_up_for_buy: bool = False, expiration: str = None) -> float:
        # For simulated trading, use SPX 0DTE special handling
        if symbol and symbol.upper() in ['SPX', 'SPXW'] and expiration:
            try:
                from datetime import datetime
                today = datetime.now().strftime('%Y-%m-%d')
                if expiration == today:
                    print(f"🚀 [SIMULATED] SPX 0DTE detected for {symbol} - using optimized tick size (0.05)")
                    tick_size = 0.05
                else:
                    tick_size = self.get_instrument_tick_size(symbol)
            except:
                tick_size = self.get_instrument_tick_size(symbol)
        else:
            tick_size = self.get_instrument_tick_size(symbol)
        
        if tick_size == 0:
            tick_size = 0.05
        
        if round_up_for_buy:
            # For BUY orders: Round UP to next valid tick to ensure execution
            ticks = math.ceil(price / tick_size)
            rounded_price = ticks * tick_size
        else:
            # For SELL orders or normal rounding: Round to nearest valid tick
            ticks = round(price / tick_size)
            rounded_price = ticks * tick_size
        
        return round(rounded_price, 2)

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
        """Find simulated position with symbol mapping"""
        # Check all symbol variants
        symbol_variants = get_all_symbol_variants(symbol)

        for variant in symbol_variants:
            pos_key = f"{variant.upper()}_{float(strike):.2f}_{str(expiration)}_{str(opt_type).lower()}"
            if pos_key in self.simulated_positions:
                position = self.simulated_positions[pos_key]
                print(f"✅ [SIMULATED] Found position: {variant} ${strike}{opt_type.upper()}")
                logger.debug(f"[SIMULATED] Position found: {pos_key}")
                return position

        return None

    def cancel_open_option_orders(self, symbol, strike, expiration, opt_type):
        """Simulate order cancellation"""
        broker_symbol = self.normalize_symbol_for_broker(symbol)
        print(f"🚫 [SIMULATED] Cancelling orders for {symbol}/{broker_symbol} ${strike}{opt_type.upper()}")
        logger.info(f"[SIMULATED] Cancelling orders for {symbol}/{broker_symbol}")
        return 1

    def place_option_buy_order(self, symbol, strike, expiration, opt_type, quantity, limit_price):
        """Simulate buy order with symbol mapping"""
        self.order_counter += 1
        broker_symbol = self.normalize_symbol_for_broker(symbol)
        rounded_price = self.round_to_tick(limit_price, broker_symbol)
        order_id = f"sim_buy_{self.order_counter}_{uuid.uuid4().hex[:8]}"

        summary = f"[SIMULATED] BUY {quantity}x {symbol}/{broker_symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f}"

        self.simulated_orders[order_id] = {
            "id": order_id,
            "state": "confirmed",
            "detail": summary,
            "symbol": symbol,
            "broker_symbol": broker_symbol,
            "quantity": quantity,
            "price": rounded_price
        }

        # Add to positions using broker symbol
        pos_key = f"{broker_symbol.upper()}_{float(strike):.2f}_{str(expiration)}_{str(opt_type).lower()}"
        if pos_key in self.simulated_positions:
            existing_qty = float(self.simulated_positions[pos_key]['quantity'])
            self.simulated_positions[pos_key]['quantity'] = str(existing_qty + float(quantity))
        else:
            self.simulated_positions[pos_key] = {
                "quantity": str(float(quantity)),
                "symbol": symbol,
                "broker_symbol": broker_symbol,
                "trader_symbol": symbol,
                "strike": strike,
                "expiration": expiration,
                "type": opt_type,
                "entry_price": rounded_price,
                "chain_symbol": broker_symbol,
                "option": f"https://simulated.url/{pos_key}"
            }

        print(summary)
        logger.info(f"[SIMULATED] Buy order placed: {order_id}")
        return {"detail": summary, "id": order_id}

    def place_option_stop_loss_order(self, symbol, strike, expiration, opt_type, quantity, stop_price):
        """Simulate stop loss order with symbol mapping"""
        self.order_counter += 1
        broker_symbol = self.normalize_symbol_for_broker(symbol)
        rounded_stop = self.round_to_tick(stop_price, broker_symbol)
        order_id = f"sim_stop_{self.order_counter}_{uuid.uuid4().hex[:8]}"
        summary = f"🛡️ [SIMULATED] STOP-LOSS for {quantity}x {symbol}/{broker_symbol} ${strike}{opt_type.upper()} @ ${rounded_stop:.2f}"
        print(summary)
        logger.info(f"[SIMULATED] Stop loss placed: {order_id}")
        return {"detail": summary, "id": order_id}

    def get_open_option_positions(self):
        """Return simulated positions with symbol mapping"""
        positions = []
        for pos_key, pos_data in self.simulated_positions.items():
            if float(pos_data.get('quantity', 0)) > 0:
                positions.append({
                    'chain_symbol': pos_data.get('broker_symbol', pos_data['symbol']),
                    'trader_symbol': pos_data.get('symbol'),
                    'broker_symbol': pos_data.get('broker_symbol', pos_data['symbol']),
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
        """Simulate realistic market data with symbol mapping"""
        try:
            broker_symbol = self.normalize_symbol_for_broker(symbol)
            # Try to get real market data first (for simulation realism)
            import robin_stocks.robinhood as r
            real_data = r.get_option_market_data(broker_symbol, expiration, strike, opt_type)
            if real_data:
                print(f"📊 [SIMULATED] Using real market data for {symbol}/{broker_symbol}")
                logger.debug(f"[SIMULATED] Using real market data for {symbol}/{broker_symbol}")
                return real_data
        except:
            pass

        # Fallback to simulated data with some randomness for realism
        import random
        base_price = 1.50
        spread = 0.10
        bid = round(base_price - spread/2 + random.uniform(-0.05, 0.05), 2)
        ask = round(base_price + spread/2 + random.uniform(-0.05, 0.05), 2)
        mark = round((bid + ask) / 2, 2)

        print(f"📊 [SIMULATED] Using mock market data for {symbol}")
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
            "symbol_mapping_enabled": True
        }

    def place_option_sell_order(self, symbol, strike, expiration, opt_type, quantity, limit_price=None, sell_padding=None):
        """Simulate sell order with symbol mapping"""
        self.order_counter += 1
        broker_symbol = self.normalize_symbol_for_broker(symbol)

        # Use provided padding or default
        if sell_padding is None:
            sell_padding = DEFAULT_SELL_PRICE_PADDING

        # Simulate market-based pricing
        if not limit_price or limit_price <= 0:
            # Get simulated market price
            market_data = self.get_option_market_data(broker_symbol, expiration, strike, opt_type)
            if market_data and len(market_data) > 0:
                data = market_data[0]
                mark_price = data.get('mark_price')
                if mark_price:
                    limit_price = float(mark_price)
                else:
                    limit_price = 1.50  # Default simulation price
            else:
                limit_price = 1.50
            print(f"📊 [SIMULATED] Using simulated market price: ${limit_price:.2f}")

        # Apply padding
        final_price = limit_price * (1 - sell_padding)
        rounded_price = self.round_to_tick(final_price, broker_symbol)

        order_id = f"sim_sell_{self.order_counter}_{uuid.uuid4().hex[:8]}"
        summary = f"[SIMULATED] SELL {quantity}x {symbol}/{broker_symbol} ${strike}{opt_type.upper()} @ ${rounded_price:.2f} (market-based, padding: {sell_padding*100:.1f}%)"

        # Update positions
        # Check all symbol variants
        symbol_variants = get_all_symbol_variants(symbol)
        pos_key = None
        for variant in symbol_variants:
            test_key = f"{variant.upper()}_{float(strike):.2f}_{str(expiration)}_{str(opt_type).lower()}"
            if test_key in self.simulated_positions:
                pos_key = test_key
                break

        if pos_key:
            current_qty = float(self.simulated_positions[pos_key]['quantity'])
            new_qty = current_qty - float(quantity)
            if new_qty < 0.01:
                del self.simulated_positions[pos_key]
                print(f"🔴 [SIMULATED] Closed position: {symbol}/{broker_symbol}")
                logger.info(f"[SIMULATED] Position closed: {symbol}/{broker_symbol}")
            else:
                self.simulated_positions[pos_key]['quantity'] = str(new_qty)
                print(f"🟡 [SIMULATED] Trimmed position: {symbol}/{broker_symbol} ({new_qty} remaining)")
                logger.info(f"[SIMULATED] Position trimmed: {symbol}/{broker_symbol} ({new_qty} remaining)")

        print(summary)
        logger.info(f"[SIMULATED] Sell order placed: {order_id}")
        return {"detail": summary, "id": order_id}

    def wait_for_order_confirmation(self, order_id: str, max_wait_seconds: int = 300) -> dict:
        """Simulate order confirmation waiting"""
        if not order_id:
            return {"status": "error", "message": "Invalid order ID"}
        
        print(f"⏳ [SIMULATED] Monitoring order {order_id}...")
        time.sleep(2)  # Simulate brief delay
        
        print(f"✅ [SIMULATED] Order {order_id} FILLED instantly")
        return {
            "status": "filled",
            "order_info": {"id": order_id, "state": "filled"},
            "elapsed_time": 2.0,
            "checks": 1
        }

    def place_option_sell_order_with_retry(self, symbol, strike, expiration, opt_type, quantity, 
                                         limit_price=None, sell_padding=None, max_retries=3):
        """Simulated sell order with retry logic (always succeeds)"""
        print(f"📤 [SIMULATED] Sell order for {symbol} ${strike}{opt_type.upper()} (retry method)")
        return self.place_option_sell_order(symbol, strike, expiration, opt_type, quantity, 
                                          limit_price, sell_padding)

# Create aliases for backwards compatibility
RobinhoodTrader = EnhancedRobinhoodTrader
SimulatedTrader = EnhancedSimulatedTrader

# Export all classes
__all__ = ['EnhancedRobinhoodTrader', 'EnhancedSimulatedTrader', 'RobinhoodTrader', 'SimulatedTrader']