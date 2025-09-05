#!/usr/bin/env python3
"""
Debug script to test SPX option market data structure
"""
import robin_stocks.robinhood as r
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
ROBINHOOD_USER = os.getenv("ROBINHOOD_USER")
ROBINHOOD_PASS = os.getenv("ROBINHOOD_PASS")

def test_spx_market_data():
    """Test SPX option market data structure"""
    
    print("🔐 Logging into Robinhood...")
    try:
        r.login(ROBINHOOD_USER, ROBINHOOD_PASS)
        print("✅ Login successful")
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return
    
    # Test SPX options with next Friday expiration
    today = datetime.now()
    
    # Calculate next Friday
    days_until_friday = (4 - today.weekday()) % 7  # Friday is weekday 4
    if days_until_friday == 0 and today.weekday() == 4:  # If today is Friday, get next Friday
        days_until_friday = 7
    elif days_until_friday == 0:  # If today is after Friday, get next Friday
        days_until_friday = (4 - today.weekday()) + 7
        
    next_friday = today + timedelta(days=days_until_friday)
    
    print(f"📅 Today: {today.strftime('%Y-%m-%d (%A)')}")
    print(f"📅 Next Friday: {next_friday.strftime('%Y-%m-%d (%A)')}")
    
    test_expirations = [next_friday.strftime('%Y-%m-%d')]
    
    # SPX strikes around current level - more realistic range
    test_strikes = [5500, 5550, 5600, 5650, 5700, 5750, 5800, 5850, 5900]
    test_types = ['call', 'put']
    
    # Focus on actual SPX index options
    symbols_to_test = ['SPXW']  # SPXW is weekly SPX options
    
    for symbol in symbols_to_test:
        print(f"\n{'='*80}")
        print(f"🔍 Testing {symbol} Options")
        print(f"{'='*80}")
        
        found_data = False
        
        for expiration in test_expirations:
            for strike in test_strikes:
                for opt_type in test_types:
                    try:
                        print(f"\n🎯 Testing: {symbol} ${strike}{opt_type[0].upper()} {expiration}")
                        
                        market_data = r.get_option_market_data(symbol, expiration, strike, opt_type)
                        
                        if market_data and len(market_data) > 0:
                            print(f"✅ Found market data!")
                            found_data = True
                            
                            data = market_data[0]
                            if isinstance(data, list) and len(data) > 0:
                                data = data[0]
                            
                            print(f"📊 Market Data Keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
                            
                            if isinstance(data, dict):
                                # Key pricing fields
                                print(f"\n💰 PRICING ANALYSIS:")
                                print(f"Mark Price: ${data.get('mark_price', 'N/A')}")
                                print(f"Bid: ${data.get('bid_price', 'N/A')} (size: {data.get('bid_size', 'N/A')})")
                                print(f"Ask: ${data.get('ask_price', 'N/A')} (size: {data.get('ask_size', 'N/A')})")
                                print(f"High Fill Buy: ${data.get('high_fill_rate_buy_price', 'N/A')}")
                                print(f"High Fill Sell: ${data.get('high_fill_rate_sell_price', 'N/A')}")
                                print(f"Low Fill Buy: ${data.get('low_fill_rate_buy_price', 'N/A')}")
                                print(f"Low Fill Sell: ${data.get('low_fill_rate_sell_price', 'N/A')}")
                                
                                # Contract info
                                print(f"\n📋 CONTRACT INFO:")
                                print(f"Symbol: {data.get('symbol')}")
                                print(f"OCC Symbol: {data.get('occ_symbol', 'N/A')}")
                                print(f"State: {data.get('state')}")
                                print(f"Volume: {data.get('volume')}")
                                print(f"Open Interest: {data.get('open_interest')}")
                                
                                # Greeks
                                print(f"\n📈 GREEKS:")
                                print(f"Delta: {data.get('delta')}")
                                print(f"Gamma: {data.get('gamma')}")
                                print(f"Theta: {data.get('theta')}")
                                print(f"Vega: {data.get('vega')}")
                                
                                print(f"\n📋 FULL DATA:")
                                print(json.dumps(data, indent=2))
                                
                                # Analyze the pricing structure
                                print(f"\n🧮 PRICING ANALYSIS:")
                                mark = float(data.get('mark_price', 0))
                                bid = float(data.get('bid_price', 0))
                                ask = float(data.get('ask_price', 0))
                                high_buy = data.get('high_fill_rate_buy_price')
                                high_sell = data.get('high_fill_rate_sell_price')
                                
                                if high_buy:
                                    high_buy = float(high_buy)
                                    buy_vs_mark = high_buy - mark
                                    buy_vs_ask = ask - high_buy
                                    print(f"📈 Buy Analysis:")
                                    print(f"   High Fill Buy: ${high_buy:.2f}")
                                    print(f"   vs Mark: ${buy_vs_mark:+.2f} ({'above' if buy_vs_mark > 0 else 'below'} mark)")
                                    print(f"   vs Ask: ${buy_vs_ask:+.2f} ({'below' if buy_vs_ask > 0 else 'above'} ask)")
                                    print(f"   Savings vs Ask: ${buy_vs_ask:.2f}")
                                
                                if high_sell:
                                    high_sell = float(high_sell)
                                    sell_vs_mark = high_sell - mark
                                    sell_vs_bid = high_sell - bid
                                    print(f"📉 Sell Analysis:")
                                    print(f"   High Fill Sell: ${high_sell:.2f}")
                                    print(f"   vs Mark: ${sell_vs_mark:+.2f} ({'above' if sell_vs_mark > 0 else 'below'} mark)")
                                    print(f"   vs Bid: ${sell_vs_bid:+.2f} ({'above' if sell_vs_bid > 0 else 'below'} bid)")
                                    print(f"   Gain vs Bid: ${sell_vs_bid:.2f}")
                                
                                spread = ask - bid if bid > 0 and ask > 0 else 0
                                print(f"📊 Spread: ${spread:.2f} ({spread/mark*100:.1f}% of mark price)")
                                
                                print(f"\n✅ SUCCESS: Found {symbol} ${strike}{opt_type[0].upper()} option data")
                                
                                # Continue searching to find more examples
                                if found_data:  # If we found at least 2 examples, stop
                                    return
                        else:
                            print(f"❌ No data")
                            
                    except Exception as e:
                        print(f"❌ Error: {e}")
        
        if not found_data:
            print(f"❌ No market data found for {symbol} with tested strikes/expirations")
    
    print(f"\n❌ Could not find any SPX option market data with the tested parameters")

if __name__ == "__main__":
    test_spx_market_data()