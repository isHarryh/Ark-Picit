"""Ark Picit — unified entry point.

Run the GUI client by default, or start the plaza server with --server.
Server settings (port, admin token, upload status) come from ``config.toml``
in the server data directory, not from the command line.

    python main.py          # GUI client
    python main.py --server # plaza server
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ark Picit")
    parser.add_argument(
        "--server",
        action="store_true",
        help="start the plaza server instead of the GUI client",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.server:
        from server.src.main import run_server

        run_server()
        return

    sys.path.insert(0, str(ROOT / "client"))
    from client.main import run_client

    run_client()


if __name__ == "__main__":
    main()
