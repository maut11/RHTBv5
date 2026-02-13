#!/usr/bin/env python3
"""
Benchmark latency: Current FiFi prompt vs Fixed prompt (v2)
Tests all 100 unique messages from scraped data
"""

import time
import json
import csv
import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

today = datetime.now(timezone.utc)
today_str = today.strftime('%Y-%m-%d')
current_year = today.year


def build_current_prompt(msg):
    """Current FiFi prompt (from fifi.py)"""
    return f'''You are a highly accurate data extraction assistant for option trading signals from a trader named FiFi.
Your ONLY job is to extract EXECUTED trade actions and return a JSON array. Each distinct trade = one object.

--- NEGATIVE CONSTRAINTS (HIGHEST PRIORITY — CHECK THESE FIRST) ---
Before classifying ANY message, check if it matches these patterns. If it does → return [{{"action": "null"}}].

1. CONDITIONAL SETUPS / WATCHLISTS:
   Messages containing "Pullback to", "Rejection of", "Break over", "Break under", or "TP:" with price targets are WATCHLIST posts, NOT live trades → "null".

2. INTENT / PLANS (not yet executed):
   "Plan:", "I want", "Going to open", "will be looking", "might grab", "eyeing", "watching", "looking at" → "null".

3. BARE TICKER MENTIONS:
   Messages that are ONLY a ticker symbol ("$FLNC", "$MRK", "XOM") with no strike/price/action → "null".

4. CORRECTION FRAGMENTS:
   Isolated fragments like "82c", "245p", "9c" without a ticker or price → "null".

5. RECAPS & STOP MANAGEMENT:
   Trim summaries (💇 emoji recaps), "SL is HOD", "stops at BE", "move stops to", video recaps, open position lists → "null".

6. TARGET PRICES: "TP 630", "TP: $A, $B, $C" are targets, NOT trims → "null".

--- ACTION DEFINITIONS ---
- "buy": EXECUTED new entry. "in", "bought", "added", "grabbed", "opening", "back in", "scaling into".
- "trim": Partial take-profit. "trim", "trimmed", "sold half", "sold 1/2", "sold some", "asold" (typo).
- "exit": Full close. "out", "all out", "sold all", "closed", "done", "stopped out", "got stopped".
- "null": Everything else.

--- OUTPUT FORMAT ---
Return a JSON array. Keys: action, ticker, strike, type, price, expiration, size.

Today: {today_str}

MESSAGE: "{msg}"'''


def build_fixed_prompt(msg):
    """Fixed prompt with regression fixes"""
    return f'''You are a highly accurate data extraction assistant for option trading signals from a trader named FiFi.
Your ONLY job is to extract EXECUTED trade actions and return a JSON array. Each distinct trade = one object.

--- NEGATIVE CONSTRAINTS (HIGHEST PRIORITY — CHECK THESE FIRST) ---
Before classifying ANY message, check if it matches these patterns. If it does → return [{{"action": "null"}}].

1. RECAPS vs. LIVE TRADES (CRITICAL):
   - RECAPS: Summaries of past trades. Often use "to" syntax (e.g., "TRIMS XOM $4.05 to 9.30"). → "null"
   - LIVE TRADES: Often use "from" syntax (e.g., "trim SPY $6.50 from 3.70"). → KEEP, extract as "trim".
   - IF unsure, and it lists multiple tickers with "to" prices, it's likely a recap.

2. CONDITIONAL SETUPS / WATCHLISTS:
   Messages containing "Pullback to", "Rejection of", "Break over", "Break under", or "TP:" with price targets are WATCHLIST posts, NOT live trades → "null".

3. INTENT / PLANS (not yet executed):
   "Plan:", "I want", "Going to open", "will be looking", "might grab", "eyeing", "watching", "looking at", "Have a limit sell" → "null".

4. BARE TICKER MENTIONS:
   Messages that are ONLY a ticker symbol ("$FLNC", "$MRK", "XOM") with no strike/price/action → "null".

5. CORRECTION FRAGMENTS:
   Isolated fragments like "82c", "245p", "9c" without a ticker or price → "null".

6. STOP MANAGEMENT:
   "SL is HOD", "stops at BE", "move stops to" → "null".

7. TARGET PRICES: "TP 630", "TP: $A, $B, $C" are targets, NOT trims → "null".

--- ACTION DEFINITIONS ---
- "buy": EXECUTED new entry.
    - Explicit: "in", "bought", "added", "grabbed", "opening", "back in", "scaling into".
    - Implicit: Ticker+strike+type+price WITHOUT any conditional words from Negative Constraints.
    - "sold" / "asold" (typo) with "from $X" context = TRIM, not buy.
- "trim": Partial take-profit. "trim", "trimmed", "sold half", "sold 1/2", "sold some", "asold" (typo for sold), "taking some off", "scaling out".
    - Price: If "from X", ignore X. Use the execution price.
- "exit": Full close. "out", "all out", "sold all", "closed", "done", "stopped out", "got stopped", "exiting", "rest out".
    - Price: If explicit price is given (e.g. "out 8.60"), USE IT. Only use "market" for "stopped out" or if no price is specified.
- "null": Everything else. Commentary, watchlists, analysis, stop management, recaps.

--- MULTI-TRADE DETECTION (CRITICAL) ---
A SINGLE message can contain MULTIPLE trades. Count distinct trades BEFORE generating output.
Each distinct price point, expiration, or ticker = SEPARATE trade object in the array.
Trades are separated by newlines, "/", or listed vertically.
EXAMPLES:
- "trim SPY $6.50 / trim QQQ $7.50" = TWO trims
- "sold 1/4 MRK $2.60 / trim TSLA $3.7" = TWO trims (different tickers)

--- OUTPUT FORMAT ---
Return a JSON array. Even single trades: [{{...}}]. Keys: lowercase snake_case.
- `action`: "buy", "trim", "exit", "null"
- `ticker`: Uppercase, no "$"
- `strike`: Number
- `type`: "call" or "put"
- `price`: Number, "BE", or "market"
- `expiration`: YYYY-MM-DD
- `size`: "full" (default), "half" (1/4, small, starter, couple cons), "lotto" (1/8, tiny, super small, lite)

--- PRICE PARSING ---
- "from $X" = entry price context. Extract the CURRENT price, ignore "from".
  "trimmed spy 7.20 from 4.60" → price is 7.20.

--- FEW-SHOT EXAMPLES ---

**TRIM (from syntax - LIVE):**
"trim SPY weekly puts $6.50 from 3.70"
→ [{{"action": "trim", "ticker": "SPY", "price": 6.50}}]

**EXIT (Explicit Price):**
"all out weekly SPY 8.60"
→ [{{"action": "exit", "ticker": "SPY", "price": 8.60}}]

**EXIT (Stopped):**
"got stopped on rest of RGTI"
→ [{{"action": "exit", "ticker": "RGTI", "price": "market"}}]

**NULL (Recap - "to" syntax):**
"Trims 💇‍♀️ PLTR $2.70 to $4.00"
→ [{{"action": "null"}}]

**NULL (Intent - Limit Sell):**
"Heading into meetings. Have a limit sell for 1/2"
→ [{{"action": "null"}}]

Today: {today_str}

MESSAGE: "{msg}"'''


def main():
    # Load unique messages from CSV
    with open('tsc_analysis/fifi_parsed_100.csv', 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Get unique messages by message_id
    unique_msgs = {}
    for r in rows:
        if r['message_id'] not in unique_msgs:
            unique_msgs[r['message_id']] = r['content']

    messages = list(unique_msgs.values())
    print('=' * 70)
    print('LATENCY BENCHMARK: Current vs Fixed Prompt (V2)')
    print('=' * 70)
    print(f'Testing {len(messages)} unique messages...')
    print()

    current_times = []
    fixed_times = []
    results = []

    for i, msg in enumerate(messages):
        msg_preview = msg[:50].replace('\n', ' ')

        # Current prompt
        try:
            start = time.time()
            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': build_current_prompt(msg)}],
                response_format={'type': 'json_object'},
                temperature=0
            )
            current_time = (time.time() - start) * 1000
            current_result = resp.choices[0].message.content
        except Exception as e:
            current_time = 0
            current_result = str(e)

        current_times.append(current_time)

        # Fixed prompt
        try:
            start = time.time()
            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': build_fixed_prompt(msg)}],
                response_format={'type': 'json_object'},
                temperature=0
            )
            fixed_time = (time.time() - start) * 1000
            fixed_result = resp.choices[0].message.content
        except Exception as e:
            fixed_time = 0
            fixed_result = str(e)

        fixed_times.append(fixed_time)

        delta = fixed_time - current_time
        results.append({
            'msg': msg_preview,
            'current_ms': current_time,
            'fixed_ms': fixed_time,
            'delta_ms': delta,
            'current_result': current_result,
            'fixed_result': fixed_result
        })

        print(f'[{i+1:3d}/100] Current={current_time:4.0f}ms | Fixed={fixed_time:4.0f}ms | Δ={delta:+4.0f}ms | {msg_preview}...')

        time.sleep(0.05)  # Rate limiting

    # Summary statistics
    print()
    print('=' * 70)
    print('SUMMARY')
    print('=' * 70)

    avg_current = sum(current_times) / len(current_times)
    avg_fixed = sum(fixed_times) / len(fixed_times)
    min_current = min(current_times)
    max_current = max(current_times)
    min_fixed = min(fixed_times)
    max_fixed = max(fixed_times)

    print(f'CURRENT PROMPT:')
    print(f'  Average: {avg_current:.0f}ms')
    print(f'  Min:     {min_current:.0f}ms')
    print(f'  Max:     {max_current:.0f}ms')
    print()
    print(f'FIXED PROMPT:')
    print(f'  Average: {avg_fixed:.0f}ms')
    print(f'  Min:     {min_fixed:.0f}ms')
    print(f'  Max:     {max_fixed:.0f}ms')
    print()
    print(f'DIFFERENCE:')
    print(f'  Average Delta: {avg_fixed - avg_current:+.0f}ms ({((avg_fixed/avg_current)-1)*100:+.1f}%)')
    print()

    # Check for parsing differences
    print('=' * 70)
    print('PARSING DIFFERENCES (where results differ)')
    print('=' * 70)

    diff_count = 0
    improvements = []
    regressions = []

    for r in results:
        try:
            curr = json.loads(r['current_result'])
            fixed = json.loads(r['fixed_result'])
            if curr != fixed:
                diff_count += 1
                if diff_count <= 15:  # Show first 15
                    print(f"\nMsg: {r['msg']}...")
                    print(f"  Current: {json.dumps(curr)[:120]}")
                    print(f"  Fixed:   {json.dumps(fixed)[:120]}")
        except:
            pass

    print(f'\nTotal parsing differences: {diff_count}/{len(messages)}')

    # Save detailed results
    with open('tsc_analysis/prompt_benchmark_v2_results.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['msg', 'current_ms', 'fixed_ms', 'delta_ms', 'current_result', 'fixed_result'])
        writer.writeheader()
        writer.writerows(results)

    print(f'\nDetailed results saved to: tsc_analysis/prompt_benchmark_v2_results.csv')


if __name__ == '__main__':
    main()
