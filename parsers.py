"""Parse verified DrayTek Vigor 167 CLI output."""

from __future__ import annotations

import re
from typing import Any


def parse_key_value_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if " : " not in line:
            continue
        key, _, value = line.partition(" : ")
        result[key.strip()] = value.strip()
    return result


def parse_dslinfo(text: str) -> dict[str, Any]:
    """Parse output of 'exec dslinfo'."""
    kv = parse_key_value_lines(text)
    numeric_fields = {
        "Downstream Line Rate": "downstream_rate_kbps",
        "Upstream Line Rate": "upstream_rate_kbps",
        "SNR Downstream": "snr_downstream_db",
        "SNR Upstream": "snr_upstream_db",
    }
    out: dict[str, Any] = {
        "status": kv.get("Status"),
        "mode": kv.get("Mode"),
        "profile": kv.get("Profile"),
        "annex": kv.get("Annex"),
        "dsl_version": kv.get("DSL Version"),
        "line_uptime": kv.get("Line Uptime"),
        "raw": kv,
    }
    for src, dst in numeric_fields.items():
        if src in kv:
            m = re.search(r"([\d.]+)", kv[src])
            out[dst] = float(m.group(1)) if m else kv[src]
            out[f"{dst}_text"] = kv[src]
    return out


def parse_sysinfo(text: str) -> dict[str, str]:
    """Parse output of 'exec sysinfo'."""
    kv = parse_key_value_lines(text)
    return {
        "model": kv.get("Model Name"),
        "device_name": kv.get("Device Name"),
        "firmware_version": kv.get("Firmware Version"),
        "branch": kv.get("Branch"),
        "build_time": kv.get("Build Time"),
        "release_mode": kv.get("Release Mode"),
        "web_version": kv.get("Web Version"),
        "core_version": kv.get("Core Version"),
        "bootloader_version": kv.get("Bootloader Version"),
        "country_code": kv.get("CountryCode"),
        "raw": kv,
    }


def parse_services(text: str) -> list[dict[str, str]]:
    """Parse output of 'exec services'."""
    services: list[dict[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in {"TCP", "UDP"}:
            services.append({"protocol": parts[0], "service": parts[1], "port": parts[2]})
    return services


def parse_cfg_status(text: str) -> dict[str, str]:
    """Parse output of 'exec cfg status'."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "Profile version:" in line:
            m = re.search(r"Profile version:\s*(\S+)\s+Status:\s*(\S+)", line)
            if m:
                out["profile_version"] = m.group(1)
                out["status"] = m.group(2)
    return out
