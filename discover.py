#!/usr/bin/env python3
"""Discover DrayTek Vigor CLI command tree via interactive SSH."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from vigor_ssh import VigorShell, load_config, run_command

CACHE_PATH = Path(__file__).resolve().parent / "cache" / "command_tree.json"

HELP_LINE_RE = re.compile(r"^  ([a-zA-Z][\w-]*)\s{2,}(.+)$")
ERROR_HINTS = ("invalid", "unknown", "error", "unrecognized", "not found", "syntax error", "incomplete")


def parse_help_question(output: str) -> list[dict]:
    commands: list[dict] = []
    seen: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        m = HELP_LINE_RE.match(line)
        if not m:
            m2 = re.match(r"^\s+([a-zA-Z][\w-]*)\s+(.+)$", line)
            if not m2:
                continue
            name, desc = m2.group(1), m2.group(2).strip()
        else:
            name, desc = m.group(1), m.group(2).strip()
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        commands.append({"name": name, "description": desc})
    return commands


def parse_config_branches(output: str) -> list[dict]:
    names: list[str] = []
    for line in output.splitlines():
        s = line.strip()
        if not s or s.startswith("vigor"):
            continue
        names.append(s)
    return [{"name": n, "path": f"config {n}"} for n in names]


def parse_help_command(output: str) -> list[dict]:
    """Parse multi-word paths from 'help' output."""
    entries: list[dict] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.rstrip()
        m = re.match(r"^\s{2}(config(?:\s+\S+)+|exec\s+\S+)\s*(.*)$", line)
        if m:
            path = m.group(1).strip()
            desc = m.group(2).strip()
            if path not in seen:
                seen.add(path)
                entries.append({"path": path, "description": desc or None, "source": "help"})
            continue
        m2 = HELP_LINE_RE.match(line)
        if m2:
            name = m2.group(1)
            if name in {"config", "exec"}:
                continue
            if name not in seen:
                seen.add(name)
                entries.append({"path": name, "description": m2.group(2).strip(), "source": "help"})
        else:
            m3 = re.match(r"^([a-zA-Z][\w-]*)\s{2,}(.+)$", line)
            if m3 and m3.group(1) not in seen:
                seen.add(m3.group(1))
                entries.append({"path": m3.group(1), "description": m3.group(2).strip(), "source": "help"})
    return entries


def is_error_output(output: str) -> bool:
    lower = output.lower()
    return any(h in lower for h in ERROR_HINTS)


def discover_exec_subcommands(shell: VigorShell, max_depth: int) -> list[dict]:
    output, _ = shell.run("exec ?")
    entries = parse_help_question(output)
    result: list[dict] = []
    for entry in entries:
        node: dict = {
            "path": f"exec {entry['name']}",
            "name": entry["name"],
            "description": entry["description"],
            "source": "exec ?",
        }
        if max_depth > 1:
            child_help = f"exec {entry['name']} ?"
            child_out, err = shell.run(child_help)
            if child_out and not is_error_output(child_out):
                # If output looks like usage/help text rather than re-running command
                if "Usage:" in child_out or child_out.strip() != output.strip():
                    node["usage"] = child_out
                    sub = parse_help_question(child_out)
                    if sub:
                        node["children"] = [
                            {"name": s["name"], "description": s["description"]} for s in sub
                        ]
                elif child_out != output:
                    node["raw_help"] = child_out
            if err:
                node["note"] = "returns usage or executes directly"
        result.append(node)
    return result


def discover_config_branches(shell: VigorShell) -> list[dict]:
    output, _ = shell.run("config ?")
    branches = parse_config_branches(output)
    result: list[dict] = []
    for branch in branches:
        node: dict = {
            "path": branch["path"],
            "name": branch["name"],
            "source": "config ?",
            "children": [],
        }
        child_help = f"{branch['path']} ?"
        child_out, _ = shell.run(child_help)
        sub = parse_help_question(child_out)
        for s in sub:
            sub_path = f"{branch['path']} {s['name']}"
            sub_help = f"{sub_path} ?"
            sub_out, _ = shell.run(sub_help)
            sub2 = parse_help_question(sub_out)
            node["children"].append(
                {
                    "name": s["name"],
                    "description": s.get("description"),
                    "path": sub_path,
                    "children": [
                        {"name": c["name"], "description": c.get("description"), "path": f"{sub_path} {c['name']}"}
                        for c in sub2
                    ],
                }
            )
        result.append(node)
    return result


def discover_top_level(shell: VigorShell) -> list[dict]:
    output, _ = shell.run("?")
    entries = parse_help_question(output)
    if not entries:
        # Top-level '?' lines may omit leading spaces on first entry
        for line in output.splitlines():
            m = re.match(r"^([a-zA-Z][\w-]*)\s{2,}(.+)$", line)
            if m:
                entries.append({"name": m.group(1), "description": m.group(2).strip()})
    return [{"path": e["name"], **e, "source": "?"} for e in entries]


def discover(max_depth: int = 2, refresh: bool = False) -> dict:
    if CACHE_PATH.is_file() and not refresh:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    config = load_config()
    with VigorShell(config) as shell:
        top = discover_top_level(shell)
        help_out, _ = shell.run("help")
        help_paths = parse_help_command(help_out)
        exec_cmds = discover_exec_subcommands(shell, max_depth) if max_depth >= 1 else []
        config_cmds = discover_config_branches(shell) if max_depth >= 1 else []

    result = {
        "device": {"host": config.host, "prompt": config.prompt_re},
        "max_depth": max_depth,
        "top_level": top,
        "help_paths": help_paths,
        "exec_commands": exec_cmds,
        "config_branches": config_cmds,
        "raw_help": help_out,
    }
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def print_tree(result: dict) -> None:
    print("Top-Level (? ):")
    for cmd in result.get("top_level", []):
        print(f"  - {cmd['name']}: {cmd.get('description', '')}")

    print("\nExec-Befehle (exec ?):")
    for cmd in result.get("exec_commands", []):
        usage = " [usage/doc]" if cmd.get("usage") else ""
        print(f"  - {cmd['path']}: {cmd.get('description', '')}{usage}")

    print("\nConfig-Zweige (config ?):")
    for branch in result.get("config_branches", []):
        print(f"  - {branch['path']}: {branch.get('description', '')}")
        for child in branch.get("children", []):
            print(f"      - {child['path']}: {child.get('description', '')}")

    print("\nVollständige Pfade (help):")
    for entry in result.get("help_paths", []):
        print(f"  - {entry['path']}: {entry.get('description', '')}")


def main() -> None:
    depth = 2
    refresh = True
    for arg in sys.argv[1:]:
        if arg == "--refresh":
            refresh = True
        elif arg == "--no-refresh":
            refresh = False
        elif arg.isdigit():
            depth = int(arg)

    print("=== Connectivity: ? ===")
    try:
        top = run_command("?")
        print(top or "(leer)")
    except Exception as exc:
        print(f"SSH/CLI failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== Discovery (depth={depth}) ===")
    result = discover(max_depth=depth, refresh=refresh)
    print_tree(result)
    print(f"\nCached: {CACHE_PATH}")


if __name__ == "__main__":
    main()
