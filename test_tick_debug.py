#!/usr/bin/env python3
"""
Debug script to test tick size detection for stocks vs options
"""
import robin_stocks.robinhood as r
import json
import os
from dotenv import load_dotenv

load_dotenv()
ROBINHOOD_USER = os.getenv("ROBINHOOD_USER")
ROBINHOOD_PASS = os.getenv("ROBINHOOD_PASS")

def test_instruments_tick_data():
    """Test what tick data we get from get_instruments_by_symbol"""
    
    print("🔐 Logging into Robinhood...")
    try:
        r.login(ROBINHOOD_USER, ROBINHOOD_PASS)
        print("✅ Login successful")
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return
    
    # Test cases
    symbols = ['SPY', 'JPM', 'SPX', 'SPXW']
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"🔍 Testing symbol: {symbol}")
        print(f"{'='*60}")
        
        try:
            instruments = r.get_instruments_by_symbols(symbol)
            
            if instruments and len(instruments) > 0 and instruments[0]:
                data = instruments[0]
                
                print(f"📊 Raw data keys: {list(data.keys())}")
                print(f"")
                
                # Key fields we care about
                print(f"Symbol: {data.get('symbol')}")
                print(f"Name: {data.get('name')}")
                print(f"Type: {data.get('type')}")
                print(f"Min Tick Size: {data.get('min_tick_size')}")
                print(f"Tradeable: {data.get('tradeable')}")
                print(f"Tradable Chain ID: {data.get('tradable_chain_id')}")
                print(f"State: {data.get('state')}")
                
                # Check if this symbol has options
                chain_id = data.get('tradable_chain_id')
                if chain_id:
                    print(f"✅ Has options chain: {chain_id}")
                else:
                    print(f"❌ No options chain")
                
                print(f"\n📋 Full instrument data:")
                print(json.dumps(data, indent=2))
                
            else:
                print(f"❌ No instrument data found for {symbol}")
                
        except Exception as e:
            print(f"❌ Error fetching {symbol}: {e}")
    
    print(f"\n{'='*60}")
    print("🧪 Testing market data response structure")
    print(f"{'='*60}")
    
    # Test market data to understand the structure better
    try:
        # Get market data for JPM (which we know has that $7.85 price)
        market_data = r.get_option_market_data_by_id("3c075730-a0f4-45b7-bd3e-86865761df45")
        
        if market_data:
            print("📊 JPM Option Market Data Sample:")
            print(json.dumps(market_data, indent=2))
        else:
            print("❌ No market data found")
            
    except Exception as e:
        print(f"❌ Error fetching market data: {e}")

if __name__ == "__main__":
    test_instruments_tick_data()