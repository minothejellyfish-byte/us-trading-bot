"""
Alpaca API Setup & Test
=======================

Helps user configure API keys and test connection.

Usage:
    python3 setup_alpaca.py
    
    # Or set keys manually:
    export ALPACA_API_KEY="PK..."
    export ALPACA_SECRET_KEY="..."
"""

import os
import sys
import json

CONFIG_FILE = os.path.expanduser("~/.alpaca_config.json")

def get_api_keys():
    """Get API keys from environment or prompt user."""
    api_key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    
    if not api_key or not secret_key:
        print("="*60)
        print("ALPACA API KEY SETUP")
        print("="*60)
        print()
        print("1. Go to: https://app.alpaca.markets/paper")
        print("2. Click 'Generate New Key'")
        print("3. Copy API Key ID and Secret Key")
        print()
        
        api_key = input("API Key ID: ").strip()
        secret_key = input("Secret Key: ").strip()
        
        if not api_key or not secret_key:
            print("❌ Both keys are required")
            return None, None
    
    return api_key, secret_key

def save_config(api_key, secret_key, paper=True):
    """Save config to file."""
    config = {
        "api_key": api_key,
        "secret_key": secret_key,
        "paper": paper,
        "created_at": __import__('datetime').datetime.now().isoformat(),
    }
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    
    os.chmod(CONFIG_FILE, 0o600)  # Secure permissions
    print(f"✅ Config saved to {CONFIG_FILE}")

def load_config():
    """Load config from file."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return None

def test_connection(api_key, secret_key, paper=True):
    """Test Alpaca connection."""
    try:
        from alpaca_api import AlpacaTrader
        
        trader = AlpacaTrader(api_key=api_key, secret_key=secret_key, paper=paper)
        
        # Get account
        acc = trader.get_account()
        print(f"\n✅ Connection successful!")
        print(f"   Account ID: {acc.get('id', 'N/A')}")
        print(f"   Status: {acc.get('status', 'N/A')}")
        print(f"   Cash: ${acc.get('cash', 0):,.2f}")
        print(f"   Equity: ${acc.get('equity', 0):,.2f}")
        print(f"   Buying Power: ${acc.get('buying_power', 0):,.2f}")
        
        # Get positions
        positions = trader.get_positions()
        print(f"\n📈 Positions: {len(positions)}")
        for p in positions:
            print(f"   {p['symbol']}: {p['qty']} shares @ ${p['avg_entry_price']:.2f}")
        
        # Get clock
        clock = trader.get_clock()
        print(f"\n🕐 Market: {'OPEN' if clock['is_open'] else 'CLOSED'}")
        print(f"   Next open: {clock['next_open']}")
        print(f"   Next close: {clock['next_close']}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        return False

def main():
    print("="*60)
    print("ALPACA PAPER TRADING SETUP")
    print("="*60)
    print()
    
    # Check if already configured
    config = load_config()
    if config:
        print("Found existing config:")
        print(f"  API Key: {config['api_key'][:8]}...")
        print(f"  Paper: {config['paper']}")
        use_existing = input("\nUse existing config? (y/n): ").strip().lower()
        if use_existing == 'y':
            api_key = config['api_key']
            secret_key = config['secret_key']
            paper = config['paper']
        else:
            api_key, secret_key = get_api_keys()
            paper = True
    else:
        api_key, secret_key = get_api_keys()
        paper = True
    
    if not api_key or not secret_key:
        print("❌ Setup cancelled")
        return
    
    # Test connection
    print("\n" + "="*60)
    print("TESTING CONNECTION...")
    print("="*60)
    
    if test_connection(api_key, secret_key, paper):
        # Save config
        save_config(api_key, secret_key, paper)
        
        print("\n" + "="*60)
        print("SETUP COMPLETE")
        print("="*60)
        print()
        print("Add these lines to ~/.bashrc:")
        print(f'export ALPACA_API_KEY="{api_key}"')
        print(f'export ALPACA_SECRET_KEY="{secret_key}"')
        print(f'export ALPACA_PAPER="true"')
        print()
        print("Then run: source ~/.bashrc")
        
        # Optional: Add to bashrc
        add_to_bashrc = input("\nAdd to ~/.bashrc automatically? (y/n): ").strip().lower()
        if add_to_bashrc == 'y':
            bashrc = os.path.expanduser("~/.bashrc")
            with open(bashrc, "a") as f:
                f.write(f"\n# Alpaca API keys (added {__import__('datetime').datetime.now().date()})\n")
                f.write(f'export ALPACA_API_KEY="{api_key}"\n')
                f.write(f'export ALPACA_SECRET_KEY="{secret_key}"\n')
                f.write(f'export ALPACA_PAPER="true"\n')
            print("✅ Added to ~/.bashrc")
    else:
        print("\n❌ Please check your API keys and try again")

if __name__ == "__main__":
    main()
