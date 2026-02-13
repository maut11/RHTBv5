#!/usr/bin/env python3
"""
Benchmark latency: Current FiFi prompt vs New improved prompt
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
    """Current FiFi prompt (simplified from fifi.py)"""
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


def build_new_prompt(msg):
    """New improved prompt with recap detection and averaging"""
    return f'''You are a highly accurate data extraction assistant for option trading signals from a trader named FiFi.
Your ONLY job is to extract EXECUTED trade actions and return a JSON array. Each distinct trade = one object.

--- NEGATIVE CONSTRAINTS (HIGHEST PRIORITY — CHECK THESE FIRST) ---
Before classifying ANY message, check if it matches these patterns. If it does → return [{{"action": "null"}}].

1. RECAPS & PERFORMANCE SUMMARIES (CRITICAL):
   Messages listing PAST performance are NOT live trades → "null".
   Pattern: "Ticker $Entry to $Exit" (e.g., "SPY $3.70 to $8.60").
   Pattern: Lists of multiple tickers with emojis like 💰, 💇‍♀️, or 🩸 (e.g., "💰 XOM... 💰 SPY...").
   Headers: "TRIMS", "RECAP", "CLOSED", "PROFITS", "PnL".
   Any message that lists multiple "trims" or "exits" with "to" prices is a summary.

2. CONDITIONAL SETUPS / WATCHLISTS:
   Messages containing "Pullback to", "Rejection of", "Break over", "Break under", or "TP:" with price targets are WATCHLIST posts, NOT live trades → "null".

3. INTENT / PLANS (not yet executed):
   "Plan:", "I want", "Going to open", "will be looking", "might grab", "eyeing", "watching", "looking at" → "null".

4. BARE TICKER MENTIONS:
   Messages that are ONLY a ticker symbol ("$FLNC", "$MRK", "XOM") with no strike/price/action → "null".

5. CORRECTION FRAGMENTS:
   Isolated fragments like "82c", "245p", "9c" without a ticker or price → "null".

6. TARGET PRICES: "TP 630", "TP: $A, $B, $C" are targets, NOT trims → "null".

--- ACTION DEFINITIONS ---
- "buy": EXECUTED new entry.
    - Explicit: "in", "bought", "added", "grabbed", "opening", "back in", "scaling into".
    - NOTE: "added", "scaling into", "back in" imply adding to existing position → set size "half".
- "trim": Partial take-profit. "trim", "trimmed", "sold half", "sold 1/2", "sold some", "asold" (typo), "small trim".
- "exit": Full close. "out", "all out", "sold all", "closed", "done", "stopped out", "got stopped", "exiting".
- "null": Everything else. Commentary, watchlists, analysis, stop management, recaps.

--- OUTPUT FORMAT ---
Return a JSON array. Keys: lowercase snake_case.
- action: "buy", "trim", "exit", "null"
- ticker: Uppercase, no "$"
- strike: Number
- type: "call" or "put"
- price: Number, "BE", or "market"
- expiration: YYYY-MM-DD
- size: "full" (default), "half" (scaling/adds), "lotto" (tiny/1/8)

--- FEW-SHOT EXAMPLES ---

**RECAP (batch summary - CRITICAL NULL):**
"💇‍♀️ TRIMS\\n💰 XOM $4.05 to 9.30\\n💰 SPY $3.70 to $8.60"
→ [{{"action": "null"}}]

**TRIM (small trim with 'from'):**
"small trim $5 from 4.05"
→ [{{"action": "trim", "price": 5}}]

**BUY (averaging):**
"scaling back into XOM $150c $3.30"
→ [{{"action": "buy", "ticker": "XOM", "strike": 150, "type": "call", "price": 3.30, "size": "half"}}]

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
    print('LATENCY BENCHMARK: Current vs New FiFi Prompt')
    print('=' * 70)
    print(f'Testing {len(messages)} unique messages...')
    print()

    current_times = []
    new_times = []
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

        # New prompt
        try:
            start = time.time()
            resp = client.chat.completions.create(
                model='gpt-4o-mini',
                messages=[{'role': 'user', 'content': build_new_prompt(msg)}],
                response_format={'type': 'json_object'},
                temperature=0
            )
            new_time = (time.time() - start) * 1000
            new_result = resp.choices[0].message.content
        except Exception as e:
            new_time = 0
            new_result = str(e)

        new_times.append(new_time)

        delta = new_time - current_time
        results.append({
            'msg': msg_preview,
            'current_ms': current_time,
            'new_ms': new_time,
            'delta_ms': delta,
            'current_result': current_result,
            'new_result': new_result
        })

        print(f'[{i+1:3d}/100] Current={current_time:4.0f}ms | New={new_time:4.0f}ms | Δ={delta:+4.0f}ms | {msg_preview}...')

        time.sleep(0.05)  # Rate limiting

    # Summary statistics
    print()
    print('=' * 70)
    print('SUMMARY')
    print('=' * 70)

    avg_current = sum(current_times) / len(current_times)
    avg_new = sum(new_times) / len(new_times)
    min_current = min(current_times)
    max_current = max(current_times)
    min_new = min(new_times)
    max_new = max(new_times)

    print(f'CURRENT PROMPT:')
    print(f'  Average: {avg_current:.0f}ms')
    print(f'  Min:     {min_current:.0f}ms')
    print(f'  Max:     {max_current:.0f}ms')
    print()
    print(f'NEW PROMPT:')
    print(f'  Average: {avg_new:.0f}ms')
    print(f'  Min:     {min_new:.0f}ms')
    print(f'  Max:     {max_new:.0f}ms')
    print()
    print(f'DIFFERENCE:')
    print(f'  Average Delta: {avg_new - avg_current:+.0f}ms ({((avg_new/avg_current)-1)*100:+.1f}%)')
    print()

    # Token comparison
    sample_msg = "test message here"
    current_tokens = len(build_current_prompt(sample_msg).split())
    new_tokens = len(build_new_prompt(sample_msg).split())
    print(f'PROMPT SIZE:')
    print(f'  Current: ~{current_tokens} words')
    print(f'  New:     ~{new_tokens} words')
    print(f'  Delta:   {new_tokens - current_tokens:+d} words ({((new_tokens/current_tokens)-1)*100:+.1f}%)')

    # Check for parsing differences
    print()
    print('=' * 70)
    print('PARSING DIFFERENCES (where results differ)')
    print('=' * 70)

    diff_count = 0
    for r in results:
        try:
            curr = json.loads(r['current_result'])
            new = json.loads(r['new_result'])
            if curr != new:
                diff_count += 1
                if diff_count <= 10:  # Show first 10
                    print(f"\nMsg: {r['msg']}...")
                    print(f"  Current: {json.dumps(curr)[:100]}")
                    print(f"  New:     {json.dumps(new)[:100]}")
        except:
            pass

    print(f'\nTotal parsing differences: {diff_count}/{len(messages)}')

    # Save detailed results
    with open('tsc_analysis/prompt_benchmark_results.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['msg', 'current_ms', 'new_ms', 'delta_ms', 'current_result', 'new_result'])
        writer.writeheader()
        writer.writerows(results)

    print(f'\nDetailed results saved to: tsc_analysis/prompt_benchmark_results.csv')


if __name__ == '__main__':
    main()
