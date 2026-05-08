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

from .tools.recover_to_clean_state import recover_to_clean_state
from .tools.wait_mcp_ready import wait_mcp_ready


logger = logging.getLogger("driver_harness_mcp")


def build_server() -> FastMCP:
    mcp = FastMCP("driver-harness-mcp")

    # v0.1 ships with two high-level tools. More to follow in v0.2.
    mcp.tool()(recover_to_clean_state)
    mcp.tool()(wait_mcp_ready)

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
