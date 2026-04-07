from __future__ import annotations

import argparse
import sys
import webbrowser

from desktop.server import start_local_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily Recommender desktop demo")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Open the admin page instead of the public page.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Optional fixed localhost port. Defaults to auto-select.",
    )
    parser.add_argument("--width", type=int, default=1440, help="Window width.")
    parser.add_argument("--height", type=int, default=960, help="Window height.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable more verbose server logging and webview debug mode.",
    )
    parser.add_argument(
        "--browser-fallback",
        action="store_true",
        help="Open the app in the system browser if desktop WebView startup fails.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    log_level = "info" if args.debug else "warning"
    route = "/admin" if args.admin else "/"

    server = start_local_server(port=args.port, log_level=log_level)
    url = f"{server.base_url}{route}"

    try:
        import webview
    except ImportError:
        server.stop()
        print(
            "pywebview is not installed. Install desktop dependencies first:\n"
            "  pip install -r requirements-desktop.txt",
            file=sys.stderr,
        )
        return 1

    try:
        webview.create_window(
            "Daily Recommender",
            url,
            width=args.width,
            height=args.height,
            min_size=(1100, 760),
            text_select=True,
        )
        webview.start(debug=args.debug)
        return 0
    except Exception as exc:
        if args.browser_fallback:
            print(f"Desktop WebView failed, opening browser fallback: {exc}", file=sys.stderr)
            webbrowser.open(url)
            return 0
        print(f"Desktop WebView failed: {exc}", file=sys.stderr)
        return 1
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
