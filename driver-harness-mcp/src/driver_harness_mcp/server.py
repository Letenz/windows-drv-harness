"""MCP server entrypoint.

This server exposes high-level orchestration tools that wrap operations from
`vmware-mcp` and `windbg-ext-mcp`. Tools intentionally don't reach into the
host's other MCP servers via MCP — instead they call the same underlying APIs
(vmrun, named pipes) directly. This keeps the harness self-contained.
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from .tools.debugger import (
    cleanup_windbg_instances,
    ensure_debugger_ready,
    list_windbg_processes,
    query_debugger_status,
)
from .tools.driver_cycle import run_driver_load_verify
from .tools.environment import diagnose_environment, start_vkd_monitor
from .tools.recover_to_clean_state import recover_to_clean_state
from .tools.wait_mcp_ready import wait_mcp_ready


logger = logging.getLogger("driver_harness_mcp")


def build_server() -> FastMCP:
    mcp = FastMCP("driver-harness-mcp")

    # High-level tools. Prefer these from skills before falling back to raw
    # vmware/windbg primitives; they encode the fragile guest/debugger timing.
    mcp.tool()(diagnose_environment)
    mcp.tool()(start_vkd_monitor)
    mcp.tool()(list_windbg_processes)
    mcp.tool()(cleanup_windbg_instances)
    mcp.tool()(query_debugger_status)
    mcp.tool()(ensure_debugger_ready)
    mcp.tool()(recover_to_clean_state)
    mcp.tool()(wait_mcp_ready)
    mcp.tool()(run_driver_load_verify)

    return mcp


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s %(name)s] %(message)s",
        stream=sys.stderr,
    )
    server = build_server()
    server.run()  # FastMCP handles transport selection (stdio default)


if __name__ == "__main__":
    main()
