"""Wire BrowserArena to Pyodide: fetch for HTTP, the page's sandbox worker, on-demand packages.

Called once by the engine web worker (web/src/engine/engine.worker.ts):
    arena = create_arena(emit, sandbox_run)
where `emit` posts run events to the UI thread and `sandbox_run` runs code in the sandbox worker.
"""

from __future__ import annotations

from typing import Any

from llm_arena.adapters.browser.arena import BrowserArena
from llm_arena.adapters.browser.js_sandbox import JsSandbox
from llm_arena.adapters.browser.pyfetch_transport import PyfetchTransport, pyfetch_bytes, pyfetch_get_json


async def _load_package(name: str) -> None:
    import pyodide_js  # the JS module object of the running Pyodide

    await pyodide_js.loadPackage(name)


def create_arena(emit: Any, sandbox_run: Any = None, browser_network: str = "not network-isolated") -> BrowserArena:
    return BrowserArena(
        transport=PyfetchTransport(),
        http_get=pyfetch_get_json,
        get_bytes=pyfetch_bytes,
        emit=lambda raw: emit(raw),
        sandbox=JsSandbox(sandbox_run, network_isolation=browser_network) if sandbox_run is not None else None,
        load_package=_load_package,
    )
