#!/usr/bin/env python3
"""
TSC (The Stocks Channel) Backtester
Analyzes TQQQ/SQQQ allocation signals and calculates P&L using Yahoo Finance data.
"""

import os
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
STARTING_CAPITAL = 100000.0

# ═══════════════════════════════════════════════════════════════════════════════
# SIGNAL DATA STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    date: str           # YYYY-MM-DD
    time: str           # HH:MM (24hr)
    action: str         # "INCREASE" or "DECREASE"
    pct_change: int     # Allocation change (5, 10, 15, etc.)
    symbol: str         # "TQQQ" or "SQQQ"
    new_total: int      # New portfolio allocation after signal
    is_initial_buy: bool = False

# ═══════════════════════════════════════════════════════════════════════════════
# PARSED SIGNALS FROM USER DATA
# ═══════════════════════════════════════════════════════════════════════════════

SIGNALS: List[Signal] = [
    # August 2025
    Signal("2025-08-07", "06:31", "DECREASE", 5, "TQQQ", 0),
    Signal("2025-08-07", "12:51", "INCREASE", 5, "TQQQ", 5),
    Signal("2025-08-12", "06:15", "DECREASE", 5, "TQQQ", 0),
    Signal("2025-08-13", "06:16", "INCREASE", 10, "SQQQ", 10, True),
    Signal("2025-08-13", "12:56", "DECREASE", 10, "SQQQ", 0),
    Signal("2025-08-14", "06:37", "INCREASE", 10, "SQQQ", 10, True),
    Signal("2025-08-15", "12:50", "DECREASE", 10, "SQQQ", 0),
    Signal("2025-08-19", "06:18", "INCREASE", 5, "TQQQ", 5, True),
    Signal("2025-08-19", "12:50", "INCREASE", 5, "TQQQ", 10),
    Signal("2025-08-20", "06:32", "INCREASE", 5, "TQQQ", 15),
    Signal("2025-08-21", "06:18", "INCREASE", 5, "TQQQ", 20),
    Signal("2025-08-22", "12:51", "DECREASE", 10, "TQQQ", 10),
    Signal("2025-08-25", "12:52", "DECREASE", 5, "TQQQ", 5),
    Signal("2025-08-28", "06:41", "DECREASE", 5, "TQQQ", 0),
    Signal("2025-08-29", "12:50", "INCREASE", 5, "TQQQ", 5),

    # September 2025
    Signal("2025-09-02", "06:21", "INCREASE", 5, "TQQQ", 10),
    Signal("2025-09-03", "06:39", "DECREASE", 5, "TQQQ", 5),
    Signal("2025-09-05", "06:21", "DECREASE", 5, "TQQQ", 0),
    Signal("2025-09-10", "06:29", "INCREASE", 10, "SQQQ", 10, True),
    Signal("2025-09-10", "12:52", "DECREASE", 10, "SQQQ", 0),
    Signal("2025-09-12", "06:18", "INCREASE", 10, "SQQQ", 10, True),
    Signal("2025-09-15", "06:16", "INCREASE", 5, "SQQQ", 15),
    Signal("2025-09-15", "12:50", "INCREASE", 5, "SQQQ", 20),
    Signal("2025-09-16", "06:17", "INCREASE", 5, "SQQQ", 25),
    Signal("2025-09-18", "06:15", "INCREASE", 5, "SQQQ", 30),
    Signal("2025-09-18", "12:50", "INCREASE", 5, "SQQQ", 35),
    Signal("2025-09-19", "06:21", "INCREASE", 5, "SQQQ", 40),
    Signal("2025-09-19", "12:50", "INCREASE", 5, "SQQQ", 45),
    Signal("2025-09-22", "12:50", "INCREASE", 5, "SQQQ", 50),
    Signal("2025-09-25", "06:17", "DECREASE", 50, "SQQQ", 0),
    Signal("2025-09-25", "12:51", "INCREASE", 10, "TQQQ", 10, True),
    Signal("2025-09-29", "06:17", "DECREASE", 10, "TQQQ", 0),

    # October 2025
    Signal("2025-10-01", "06:21", "INCREASE", 10, "TQQQ", 10),
    Signal("2025-10-02", "06:15", "DECREASE", 10, "TQQQ", 0),
    Signal("2025-10-02", "06:45", "INCREASE", 10, "TQQQ", 10),
    Signal("2025-10-03", "06:33", "DECREASE", 10, "TQQQ", 0),
    Signal("2025-10-10", "12:55", "INCREASE", 15, "TQQQ", 15),
    Signal("2025-10-13", "06:17", "DECREASE", 5, "TQQQ", 10),
    Signal("2025-10-15", "06:33", "DECREASE", 10, "TQQQ", 0),
    Signal("2025-10-24", "06:36", "INCREASE", 10, "SQQQ", 10, True),
    Signal("2025-10-27", "06:15", "INCREASE", 10, "SQQQ", 20),
    Signal("2025-10-27", "12:52", "INCREASE", 5, "SQQQ", 25),
    Signal("2025-10-28", "06:32", "INCREASE", 5, "SQQQ", 30),
    Signal("2025-10-29", "06:17", "INCREASE", 5, "SQQQ", 35),
    Signal("2025-10-30", "12:53", "DECREASE", 15, "SQQQ", 20),
    Signal("2025-10-31", "06:21", "INCREASE", 5, "SQQQ", 25),

    # November 2025
    Signal("2025-11-03", "06:17", "INCREASE", 5, "SQQQ", 30),
    Signal("2025-11-04", "06:35", "DECREASE", 30, "SQQQ", 0),
    Signal("2025-11-06", "12:51", "INCREASE", 10, "TQQQ", 10, True),
    Signal("2025-11-07", "06:21", "INCREASE", 5, "TQQQ", 15),
    Signal("2025-11-07", "06:40", "INCREASE", 5, "TQQQ", 20),
    Signal("2025-11-10", "06:15", "DECREASE", 20, "TQQQ", 0),
    Signal("2025-11-13", "12:59", "INCREASE", 10, "TQQQ", 10),
    Signal("2025-11-14", "06:21", "INCREASE", 5, "TQQQ", 15),
    Signal("2025-11-14", "06:33", "INCREASE", 5, "TQQQ", 20),
    Signal("2025-11-17", "12:52", "INCREASE", 5, "TQQQ", 25),
    Signal("2025-11-18", "06:30", "INCREASE", 5, "TQQQ", 30),
    Signal("2025-11-20", "06:15", "DECREASE", 10, "TQQQ", 20),
    Signal("2025-11-20", "12:50", "INCREASE", 20, "TQQQ", 40),
    Signal("2025-11-21", "06:25", "INCREASE", 5, "TQQQ", 45),
    Signal("2025-11-24", "06:15", "DECREASE", 15, "TQQQ", 30),
    Signal("2025-11-24", "12:50", "DECREASE", 10, "TQQQ", 20),
    Signal("2025-11-25", "06:16", "DECREASE", 10, "TQQQ", 10),
    Signal("2025-11-26", "06:15", "DECREASE", 10, "TQQQ", 0),

    # December 2025
    Signal("2025-12-12", "12:56", "INCREASE", 10, "TQQQ", 10),
    Signal("2025-12-16", "06:16", "INCREASE", 10, "TQQQ", 20),
    Signal("2025-12-17", "12:51", "INCREASE", 25, "TQQQ", 45),
    Signal("2025-12-18", "06:17", "INCREASE", 5, "TQQQ", 50),
    Signal("2025-12-18", "06:42", "INCREASE", 5, "TQQQ", 55),
    Signal("2025-12-19", "12:50", "DECREASE", 35, "TQQQ", 20),
    Signal("2025-12-22", "06:18", "DECREASE", 20, "TQQQ", 0),

    # January 2026
    Signal("2026-01-08", "06:44", "INCREASE", 10, "TQQQ", 10),
    Signal("2026-01-20", "06:16", "INCREASE", 10, "TQQQ", 20),
]

# ═══════════════════════════════════════════════════════════════════════════════
# PRICE DATA FETCHING (Yahoo Finance)
# ═══════════════════════════════════════════════════════════════════════════════

def load_price_data() -> Dict[str, pd.DataFrame]:
    """Load daily price data for TQQQ and SQQQ from Yahoo Finance."""
    print("\n" + "="*60)
    print("FETCHING PRICE DATA (Yahoo Finance)")
    print("="*60)

    data = {}
    for symbol in ["TQQQ", "SQQQ"]:
        print(f"  Downloading {symbol}...")
        df = yf.download(symbol, start='2025-08-01', end='2026-01-25', progress=False)
        if not df.empty:
            # Flatten multi-index columns if present
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            df['Date'] = pd.to_datetime(df['Date']).dt.date
            data[symbol] = df
            print(f"    {symbol}: {len(df)} days ({df['Date'].min()} to {df['Date'].max()})")
        else:
            print(f"    {symbol}: No data!")

    return data


def get_price_for_signal(df: pd.DataFrame, date_str: str, time_str: str) -> Optional[float]:
    """
    Get price for a signal.
    Morning signals (before 10:00) use Open price.
    Midday signals (after 10:00) use Close price.
    """
    if df is None or df.empty:
        return None

    from datetime import date
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Find the row for this date
    row = df[df['Date'] == target_date]
    if row.empty:
        return None

    # Parse time to determine open vs close
    hour = int(time_str.split(":")[0])

    if hour < 10:
        # Morning signal -> use Open price
        return float(row['Open'].iloc[0])
    else:
        # Midday signal -> use Close price (or midpoint)
        return float(row['Close'].iloc[0])


# ═══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    symbol: str
    shares: float
    cost_basis: float
    entry_date: str

@dataclass
class Trade:
    signal_idx: int
    date: str
    time: str
    symbol: str
    action: str
    allocation_pct: int
    shares: float
    price: float
    dollar_value: float
    portfolio_value: float
    realized_pnl: float = 0.0


def run_simulation(signals: List[Signal], price_data: Dict[str, pd.DataFrame]) -> Tuple[List[Trade], float]:
    """Simulate the TSC strategy with actual prices."""
    cash = STARTING_CAPITAL
    positions: Dict[str, Position] = {}
    trades: List[Trade] = []

    print("\n" + "="*60)
    print("RUNNING SIMULATION")
    print(f"Starting Capital: ${STARTING_CAPITAL:,.2f}")
    print("="*60 + "\n")

    for idx, sig in enumerate(signals):
        # Get current price
        if sig.symbol not in price_data:
            print(f"  [{idx}] {sig.date} - No data for {sig.symbol}, skipping")
            continue

        price = get_price_for_signal(price_data[sig.symbol], sig.date, sig.time)
        if price is None:
            print(f"  [{idx}] {sig.date} - No price for {sig.symbol}, skipping")
            continue

        # Calculate current portfolio value (mark-to-market)
        portfolio_value = cash
        for sym, pos in positions.items():
            if sym in price_data:
                current_price = get_price_for_signal(price_data[sym], sig.date, sig.time)
                if current_price:
                    portfolio_value += pos.shares * current_price

        # Calculate target dollar allocation
        target_allocation_dollars = portfolio_value * (sig.new_total / 100.0)

        # Calculate current position value in this symbol
        current_position_value = 0.0
        if sig.symbol in positions:
            current_position_value = positions[sig.symbol].shares * price

        # Determine trade
        shares_to_trade = 0.0
        dollar_value = 0.0
        realized_pnl = 0.0

        if sig.action == "INCREASE":
            # Buy more shares
            dollars_to_buy = target_allocation_dollars - current_position_value
            if dollars_to_buy > 0 and dollars_to_buy <= cash:
                shares_to_trade = dollars_to_buy / price
                dollar_value = dollars_to_buy
                cash -= dollars_to_buy

                if sig.symbol in positions:
                    old_pos = positions[sig.symbol]
                    total_shares = old_pos.shares + shares_to_trade
                    total_cost = old_pos.cost_basis * old_pos.shares + dollar_value
                    positions[sig.symbol] = Position(
                        symbol=sig.symbol,
                        shares=total_shares,
                        cost_basis=total_cost / total_shares,
                        entry_date=old_pos.entry_date
                    )
                else:
                    positions[sig.symbol] = Position(
                        symbol=sig.symbol,
                        shares=shares_to_trade,
                        cost_basis=price,
                        entry_date=sig.date
                    )

        elif sig.action == "DECREASE":
            if sig.symbol in positions:
                pos = positions[sig.symbol]

                if sig.new_total == 0:
                    # Full exit
                    shares_to_trade = pos.shares
                    dollar_value = shares_to_trade * price
                    realized_pnl = (price - pos.cost_basis) * shares_to_trade
                    cash += dollar_value
                    del positions[sig.symbol]
                else:
                    # Partial exit
                    dollars_to_sell = current_position_value - target_allocation_dollars
                    if dollars_to_sell > 0:
                        shares_to_trade = dollars_to_sell / price
                        shares_to_trade = min(shares_to_trade, pos.shares)
                        dollar_value = shares_to_trade * price
                        realized_pnl = (price - pos.cost_basis) * shares_to_trade
                        cash += dollar_value

                        new_shares = pos.shares - shares_to_trade
                        if new_shares > 0.01:
                            positions[sig.symbol] = Position(
                                symbol=pos.symbol,
                                shares=new_shares,
                                cost_basis=pos.cost_basis,
                                entry_date=pos.entry_date
                            )
                        else:
                            del positions[sig.symbol]

        # Record trade
        trade = Trade(
            signal_idx=idx,
            date=sig.date,
            time=sig.time,
            symbol=sig.symbol,
            action=sig.action,
            allocation_pct=sig.new_total,
            shares=shares_to_trade,
            price=price,
            dollar_value=dollar_value,
            portfolio_value=portfolio_value,
            realized_pnl=realized_pnl
        )
        trades.append(trade)

        # Print trade
        action_emoji = "🟢" if sig.action == "INCREASE" else "🔴"
        time_type = "OPEN" if int(sig.time.split(":")[0]) < 10 else "CLOSE"
        pnl_str = f" | P&L: ${realized_pnl:+,.2f}" if realized_pnl != 0 else ""
        print(f"{action_emoji} {sig.date} {sig.time} [{time_type}] | {sig.symbol} → {sig.new_total:>2}% | "
              f"${dollar_value:>8,.0f} @ ${price:>6.2f} ({shares_to_trade:>7.1f} sh){pnl_str}")

    # Calculate final portfolio value
    final_value = cash
    print(f"\n--- OPEN POSITIONS ---")
    for sym, pos in positions.items():
        last_date = signals[-1].date
        if sym in price_data:
            price = get_price_for_signal(price_data[sym], last_date, "12:00")
            if price:
                pos_value = pos.shares * price
                unrealized = (price - pos.cost_basis) * pos.shares
                final_value += pos_value
                print(f"  {sym}: {pos.shares:.1f} shares @ ${pos.cost_basis:.2f} → ${price:.2f} "
                      f"(${pos_value:,.0f}, P&L: ${unrealized:+,.2f})")

    return trades, final_value


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTING
# ═══════════════════════════════════════════════════════════════════════════════

def generate_report(trades: List[Trade], final_value: float):
    """Generate comprehensive P&L report."""
    print("\n" + "="*60)
    print("TSC BACKTEST RESULTS")
    print("="*60)

    # Overall P&L
    total_return = (final_value - STARTING_CAPITAL) / STARTING_CAPITAL * 100
    total_pnl = final_value - STARTING_CAPITAL

    print(f"\n{'Starting Capital:':<20} ${STARTING_CAPITAL:>12,.2f}")
    print(f"{'Final Value:':<20} ${final_value:>12,.2f}")
    print(f"{'Total P&L:':<20} ${total_pnl:>+12,.2f} ({total_return:+.2f}%)")

    # Realized P&L breakdown
    realized_pnl = sum(t.realized_pnl for t in trades)
    print(f"{'Realized P&L:':<20} ${realized_pnl:>+12,.2f}")

    # Trade statistics
    exit_trades = [t for t in trades if t.action == "DECREASE" and t.realized_pnl != 0]
    winning_trades = [t for t in exit_trades if t.realized_pnl > 0]
    losing_trades = [t for t in exit_trades if t.realized_pnl < 0]

    if exit_trades:
        win_rate = len(winning_trades) / len(exit_trades) * 100
        avg_win = sum(t.realized_pnl for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.realized_pnl for t in losing_trades) / len(losing_trades) if losing_trades else 0
        profit_factor = abs(sum(t.realized_pnl for t in winning_trades) / sum(t.realized_pnl for t in losing_trades)) if losing_trades else float('inf')

        print(f"\n{'Trade Statistics:'}")
        print(f"  {'Total Signals:':<18} {len(trades)}")
        print(f"  {'Exit Trades:':<18} {len(exit_trades)}")
        print(f"  {'Winners:':<18} {len(winning_trades)} ({win_rate:.1f}%)")
        print(f"  {'Losers:':<18} {len(losing_trades)}")
        print(f"  {'Avg Win:':<18} ${avg_win:+,.2f}")
        print(f"  {'Avg Loss:':<18} ${avg_loss:+,.2f}")
        print(f"  {'Profit Factor:':<18} {profit_factor:.2f}")

    # By symbol
    print(f"\n{'By Symbol:'}")
    for symbol in ["TQQQ", "SQQQ"]:
        sym_exits = [t for t in exit_trades if t.symbol == symbol]
        sym_pnl = sum(t.realized_pnl for t in sym_exits)
        sym_wins = len([t for t in sym_exits if t.realized_pnl > 0])
        sym_total = len(sym_exits)
        wr = (sym_wins / sym_total * 100) if sym_total > 0 else 0
        print(f"  {symbol}: {sym_total} exits, P&L: ${sym_pnl:+,.2f}, Win Rate: {wr:.0f}%")

    # Monthly breakdown
    print(f"\n{'Monthly P&L:'}")
    monthly_pnl = {}
    for t in trades:
        month = t.date[:7]
        if month not in monthly_pnl:
            monthly_pnl[month] = 0
        monthly_pnl[month] += t.realized_pnl

    for month in sorted(monthly_pnl.keys()):
        bar_len = int(abs(monthly_pnl[month]) / 500)
        bar = "█" * min(bar_len, 30)
        sign = "+" if monthly_pnl[month] >= 0 else "-"
        print(f"  {month}: ${monthly_pnl[month]:>+10,.2f} {bar}")

    # Save detailed trades to CSV
    csv_path = os.path.join(DATA_DIR, "backtest_results.csv")
    df = pd.DataFrame([{
        'date': t.date,
        'time': t.time,
        'symbol': t.symbol,
        'action': t.action,
        'allocation_pct': t.allocation_pct,
        'shares': round(t.shares, 2),
        'price': round(t.price, 2),
        'dollar_value': round(t.dollar_value, 2),
        'portfolio_value': round(t.portfolio_value, 2),
        'realized_pnl': round(t.realized_pnl, 2)
    } for t in trades])
    df.to_csv(csv_path, index=False)
    print(f"\nDetailed trades saved to: {csv_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("="*60)
    print("TSC (The Stocks Channel) BACKTESTER")
    print("="*60)
    print(f"Signals: {len(SIGNALS)}")
    print(f"Date Range: {SIGNALS[0].date} to {SIGNALS[-1].date}")

    # Load price data
    price_data = load_price_data()

    if not price_data:
        print("\nERROR: Could not load price data.")
        return

    # Run simulation
    trades, final_value = run_simulation(SIGNALS, price_data)

    # Generate report
    generate_report(trades, final_value)


if __name__ == "__main__":
    main()
