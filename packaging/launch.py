"""PyInstaller entry point."""

import sys

from scb_designer.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
