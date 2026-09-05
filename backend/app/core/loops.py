"""Custom uvicorn loop factories.

aiomqtt (MQTT over TCP) requires loop.add_reader/add_writer, which Windows'
default ProactorEventLoop does not implement. uvicorn 0.52 hard-codes the
Proactor choice on win32 (uvicorn/loops/asyncio.py), so we hand it an explicit
factory instead (supported: `loop` accepts an import string).

`selector_event_loop_factory` returns a SelectorEventLoop on every platform -
on Linux this is exactly what uvicorn's own "asyncio" factory produces.
"""

import asyncio


def selector_event_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
