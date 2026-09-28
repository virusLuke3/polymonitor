#!/usr/bin/env python3
"""Command-line entrypoint for the Polymonitor consumer API."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from api.app import main

if __name__ == "__main__":
    main()
