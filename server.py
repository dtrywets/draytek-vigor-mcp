#!/usr/bin/env python3
"""MCP server for DrayTek Vigor 167 DSL diagnostics via SSH."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from discover import CACHE_PATH, discover, print_tree
from parsers import parse_cfg_status, parse_dslinfo, parse_services, parse_sysinfo
from vigor_ssh import run_command as ssh_run_command, run_commands as ssh_run_commands

mcp = FastMCP("draytek-vigor")


def _command_result(output: str, error: str | None = None) -> dict[str, Any]:
    return {"output": output, "error": error}


@mcp.tool()
def discover_commands(depth: int = 2, refresh: bool = False) -> dict[str, Any]:
    """Discover CLI commands via '?' on the device. Results are cached on disk."""
    result = discover(max_depth=depth, refresh=refresh)
    return {
        "cached_path": str(CACHE_PATH),
        "top_level": result.get("top_level", []),
        "exec_commands": result.get("exec_commands", []),
        "config_branches": result.get("config_branches", []),
        "help_paths": result.get("help_paths", []),
    }


@mcp.tool()
def run_command(command: str) -> dict[str, Any]:
    """Run an arbitrary DrayTek CLI command over SSH."""
    try:
        output = ssh_run_command(command)
        lower = output.lower()
        if any(h in lower for h in ("invalid", "unknown command", "syntax error", "incomplete command", "access denied")):
            return _command_result(output, output)
        return _command_result(output)
    except Exception as exc:
        return _command_result("", str(exc))


@mcp.tool()
def run_commands(commands: list[str]) -> dict[str, Any]:
    """Run multiple CLI commands in one SSH session."""
    try:
        outputs = ssh_run_commands(commands)
        results = []
        for cmd, output in zip(commands, outputs):
            lower = output.lower()
            err = output if any(h in lower for h in ("invalid", "unknown command", "syntax error", "incomplete command", "access denied")) else None
            results.append({"command": cmd, "output": output, "error": err})
        return {"results": results}
    except Exception as exc:
        return {"results": [], "error": str(exc)}


@mcp.tool()
def get_dsl_info() -> dict[str, Any]:
    """DSL sync status via verified command 'exec dslinfo'."""
    output = ssh_run_command("exec dslinfo")
    return {"command": "exec dslinfo", "parsed": parse_dslinfo(output), "raw": output}


@mcp.tool()
def get_system_info() -> dict[str, Any]:
    """Firmware and device info via verified command 'exec sysinfo'."""
    output = ssh_run_command("exec sysinfo")
    parsed = parse_sysinfo(output)
    parsed.pop("raw", None)
    return {"command": "exec sysinfo", **parsed, "raw": output}


@mcp.tool()
def get_device_time() -> dict[str, Any]:
    """Device clock via verified command 'exec date'."""
    output = ssh_run_command("exec date")
    return {"command": "exec date", "datetime": output.strip(), "raw": output}


@mcp.tool()
def get_services() -> dict[str, Any]:
    """Open CPE services via verified command 'exec services'."""
    output = ssh_run_command("exec services")
    return {"command": "exec services", "services": parse_services(output), "raw": output}


@mcp.tool()
def get_config_status() -> dict[str, Any]:
    """Config profile status via verified command 'exec cfg status'."""
    output = ssh_run_command("exec cfg status")
    return {"command": "exec cfg status", **parse_cfg_status(output), "raw": output}


@mcp.tool()
def get_command_tree_summary() -> dict[str, Any]:
    """Return cached discovery tree or refresh if missing."""
    if not CACHE_PATH.is_file():
        discover(refresh=True)
    data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {
        "top_level": data.get("top_level", []),
        "exec_commands": [{"path": c.get("path"), "description": c.get("description")} for c in data.get("exec_commands", [])],
        "config_branches": data.get("config_branches", []),
        "help_paths": data.get("help_paths", []),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
