"""PyInstaller entry point."""

import sys

from sbc_designer.app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
