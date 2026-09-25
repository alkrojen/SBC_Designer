"""``python -m sbc_designer`` starts the GUI; ``python -m sbc_designer cli ...`` the CLI."""

import sys


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "cli":
        from .cli import main as cli_main
        return cli_main(sys.argv[2:])
    from .app import main as gui_main
    return gui_main(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
