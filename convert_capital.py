#!/usr/bin/env python3
"""
Convert capital file to expected format
"""

import json
import os

BASE_DIR = "/home/mino/us-exec"
CAPITAL_FILE = os.path.normpath(os.path.join(BASE_DIR, "us_capital.json"))

def convert_capital_file():
    """Convert capital file to expected format."""
    if not os.path.exists(CAPITAL_FILE):
        print("Capital file not found")
        return False
    
    try:
        with open(CAPITAL_FILE, 'r') as f:
            data = json.load(f)
        
        # Convert to expected format
        converted_data = {
            "available_capital": data.get("cash", 100000.0),
            "updated_at": data.get("updated_at", "")
        }
        
        # Save the converted data
        with open(CAPITAL_FILE, 'w') as f:
            json.dump(converted_data, f, indent=2)
        
        print("Capital file converted successfully")
        return True
    except Exception as e:
        print(f"Error converting capital file: {e}")
        return False

if __name__ == "__main__":
    convert_capital_file()