"""SSH shell helpers for DrayTek Vigor 167 CLI."""

from __future__ import annotations

import os
import re
import socket
import time
from dataclasses import dataclass
from pathlib import Path

import paramiko


DEFAULT_PROMPT_RE = r"vigor>\s*$"
DEFAULT_IDLE_SEC = 0.6
DEFAULT_CONNECT_TIMEOUT = 15
DEFAULT_COMMAND_TIMEOUT = 30
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


@dataclass(frozen=True)
class VigorConfig:
    host: str
    port: int
    username: str
    password: str
    prompt_re: str
    idle_sec: float
    connect_timeout: int
    command_timeout: int


def parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def load_env_file(path: Path | None = None) -> dict[str, str]:
    env_path = path or Path(__file__).resolve().parent / ".env"
    result: dict[str, str] = {}
    if not env_path.is_file():
        return result
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(":")
        if not rest:
            continue
        result[key.strip()] = parse_env_value(rest.strip())
    return result


def load_config(env_path: Path | None = None) -> VigorConfig:
    env = load_env_file(env_path)
    skip = {"VIGOR_HOST", "VIGOR_PORT", "VIGOR_PROMPT", "VIGOR_IDLE_SEC"}
    cred_key = next((k for k in env if k not in skip), None)
    if not cred_key:
        raise ValueError('Keine SSH-Credentials in .env gefunden (Format: user:"passwort")')
    host = env.get("VIGOR_HOST")
    if not host:
        raise ValueError("VIGOR_HOST fehlt in .env")
    port = int(env.get("VIGOR_PORT", "22"))
    prompt_re = os.environ.get("VIGOR_PROMPT") or env.get("VIGOR_PROMPT") or DEFAULT_PROMPT_RE
    idle_raw = os.environ.get("VIGOR_IDLE_SEC") or env.get("VIGOR_IDLE_SEC")
    idle_sec = float(idle_raw) if idle_raw else DEFAULT_IDLE_SEC
    return VigorConfig(
        host=host,
        port=port,
        username=cred_key,
        password=env[cred_key],
        prompt_re=prompt_re,
        idle_sec=idle_sec,
        connect_timeout=DEFAULT_CONNECT_TIMEOUT,
        command_timeout=DEFAULT_COMMAND_TIMEOUT,
    )


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


class VigorShell:
    """Interactive DrayTek CLI session over SSH (invoke_shell + pty)."""

    def __init__(self, config: VigorConfig | None = None) -> None:
        self.config = config or load_config()
        self._transport: paramiko.Transport | None = None
        self._channel: paramiko.Channel | None = None
        self._prompt_pattern = re.compile(self.config.prompt_re, re.MULTILINE)
        self._logged_in = False

    def __enter__(self) -> VigorShell:
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        self.close()
        sock = socket.create_connection(
            (self.config.host, self.config.port),
            timeout=self.config.connect_timeout,
        )
        transport = paramiko.Transport(sock)
        transport.start_client()
        # Vigor 167 accepts SSH auth_none; CLI login follows interactively.
        transport.auth_none(self.config.username)
        channel = transport.open_session()
        channel.get_pty(term="vt100", width=200, height=50)
        channel.invoke_shell()
        channel.settimeout(self.config.command_timeout)
        self._transport = transport
        self._channel = channel
        self._cli_login()

    def close(self) -> None:
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
            self._channel = None
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._logged_in = False

    def _recv_available(self) -> str:
        assert self._channel is not None
        chunks: list[str] = []
        while self._channel.recv_ready():
            chunks.append(self._channel.recv(65535).decode("utf-8", errors="replace"))
        return strip_ansi("".join(chunks))

    def _read_until(self, predicate, timeout: float | None = None) -> str:
        assert self._channel is not None
        deadline = time.monotonic() + (timeout or self.config.command_timeout)
        buffer = ""
        last_data = time.monotonic()
        while time.monotonic() < deadline:
            chunk = self._recv_available()
            if chunk:
                buffer += chunk
                last_data = time.monotonic()
                if predicate(buffer):
                    return buffer
            elif time.monotonic() - last_data >= self.config.idle_sec:
                if predicate(buffer):
                    return buffer
                break
            time.sleep(0.05)
        return buffer

    def _read_until_prompt(self) -> str:
        return self._read_until(lambda buf: bool(self._prompt_pattern.search(buf)))

    def _cli_login(self) -> None:
        assert self._channel is not None
        self._read_until(lambda buf: "username" in buf.lower() or "password" in buf.lower())
        self._channel.send(self.config.username + "\r")
        self._read_until(lambda buf: "password" in buf.lower())
        self._channel.send(self.config.password + "\r")
        self._read_until_prompt()
        self._logged_in = True

    def run(self, command: str) -> tuple[str, str | None]:
        if self._channel is None or not self._logged_in:
            self.connect()
        assert self._channel is not None
        self._channel.send(command + "\r")
        raw = self._read_until_prompt()
        cleaned = strip_cli_output(raw, command)
        lower = cleaned.lower()
        if any(h in lower for h in ("invalid", "unknown command", "syntax error", "incomplete command")):
            return cleaned, cleaned
        return cleaned, None

    def run_many(self, commands: list[str]) -> list[tuple[str, str | None]]:
        return [self.run(cmd) for cmd in commands]


def strip_cli_output(raw: str, command: str) -> str:
    text = strip_ansi(raw).replace("\r", "")
    lines = [ln.rstrip() for ln in text.split("\n")]
    prompt_re = re.compile(r"^vigor(?:\([^)]+\))?>?\s*$")
    cmd = command.strip()
    cmd_base = cmd.split()[0] if cmd else cmd

    # Drop prompts and empty lines at ends
    filtered: list[str] = []
    for line in lines:
        if prompt_re.match(line.strip()):
            continue
        filtered.append(line)

    # Remove command echo (exact, partial, or base command only)
    start = 0
    for i, line in enumerate(filtered):
        s = line.strip()
        if not s:
            start = i + 1
            continue
        if s == cmd or s.startswith(cmd) or cmd.startswith(s) or s == cmd_base:
            start = i + 1
            continue
        break

    cleaned = [ln for ln in filtered[start:] if ln.strip()]
    cleaned = [ln for ln in cleaned if not ln.strip().startswith("vigor")]
    # Drop trailing incomplete-command noise
    while cleaned and cleaned[-1].strip().lower() in {"incomplete command", "invalid command"}:
        cleaned.pop()
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return "\n".join(cleaned).strip()


def run_command(command: str, config: VigorConfig | None = None) -> str:
    with VigorShell(config) as shell:
        output, _ = shell.run(command)
        return output


def run_commands(commands: list[str], config: VigorConfig | None = None) -> list[str]:
    with VigorShell(config) as shell:
        return [out for out, _ in shell.run_many(commands)]
