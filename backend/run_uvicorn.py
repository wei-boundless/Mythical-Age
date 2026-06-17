from __future__ import annotations

import argparse
import asyncio
import sys

import uvicorn


def _windows_safe_loop_factory() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


def _install_windows_selector_loop_policy() -> None:
    if sys.platform != "win32":
        return
    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return
    asyncio.set_event_loop_policy(selector_policy())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the backend ASGI app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8003)
    args = parser.parse_args()

    _install_windows_selector_loop_policy()
    uvicorn.run("app:app", host=args.host, port=args.port, loop=_windows_safe_loop_factory)


if __name__ == "__main__":
    main()


