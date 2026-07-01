# DrayTek Vigor 167 MCP Server

MCP-Server für DSL-Diagnose und CLI-Zugriff am **DrayTek Vigor 167** (Firmware 5.2.8) über interaktive SSH-Shell.

Befehle werden **nicht geraten**: Discovery läuft live gegen das Gerät (`?` / `help`) und wird unter `cache/command_tree.json` gecacht. Convenience-Tools und Parser basieren auf **verifiziertem** CLI-Output.

## Status

| Komponente | Status |
|------------|--------|
| Python venv (`.venv`) | `mcp[cli]` + `paramiko` installiert |
| Cursor MCP (`~/.cursor/mcp.json`) | **Noch nicht eingetragen** — siehe Abschnitt [Cursor einbinden](#cursor-einbinden) |
| `.env` mit Modem-Credentials | Lokal vorhanden, nicht im Git |

## Voraussetzungen

- Python 3.11+
- Netzwerkzugang zum Modem (Standard: `192.168.167.1:22`)
- Cursor oder anderer MCP-Client
- DrayTek Vigor 167 mit eingeschränkter Bridge-CLI (kein voller DrayOS-Befehlssatz)

## Schnellstart

```bash
cd ~/Workspaces/draytek-vigor-mcp
python -m venv .venv
source .venv/bin/activate
pip install "mcp[cli]" paramiko
```

`.env` anlegen (Format siehe unten), dann Discovery testen:

```bash
.venv/bin/python discover.py 2 --refresh
.venv/bin/python -c "from vigor_ssh import run_command; print(run_command('exec dslinfo'))"
```

Server manuell starten (stdio-MCP):

```bash
.venv/bin/python server.py
```

## Credentials (`.env`)

Nicht committen (steht in `.gitignore`). **Kein Standard-dotenv** — Parsing: erstes `:` trennt Schlüssel und Wert, umschließende `"` am Wert werden entfernt.

```env
mcp:"geheim"
VIGOR_HOST:"192.168.167.1"
VIGOR_PORT:"22"
```

Optional:

```env
VIGOR_PROMPT:"vigor>\\s*$"
VIGOR_IDLE_SEC:"0.8"
```

Die erste Zeile ohne reservierten Schlüssel (`VIGOR_*`) ist der **CLI-Benutzername**; der Wert ist das CLI-Passwort.

## SSH- und CLI-Ablauf (Vigor 167)

Am 167 unterscheidet sich der Ablauf von klassischen DrayTek-Routern:

1. **SSH-Transport**: `auth_none` (kein SSH-Passwort/Key nötig)
2. **Interaktive Shell**: `invoke_shell` + PTY — `exec_command` liefert oft leere Ausgabe
3. **CLI-Login**: Gerät fragt `Username:` / `Password:` (Credentials aus `.env`)
4. **Prompt**: `vigor>`
5. **Neue Session pro Aufruf**: Das Modem beendet idle SSH-Sessions

`enable` ist in der CLI vorhanden, aber am Vigor 167 **ohne konfigurierbares Passwort nutzlos** (*Access denied*). DSL-Diagnose funktioniert ohne privilegierten Modus.

## Cursor einbinden

Eintrag in `~/.cursor/mcp.json` unter `mcpServers` ergänzen:

```json
{
  "mcpServers": {
    "draytek-vigor": {
      "command": "/home/ladwein/Workspaces/draytek-vigor-mcp/.venv/bin/python",
      "args": ["/home/ladwein/Workspaces/draytek-vigor-mcp/server.py"],
      "cwd": "/home/ladwein/Workspaces/draytek-vigor-mcp"
    }
  }
}
```

Danach Cursor neu laden oder MCP-Server in den Einstellungen aktivieren.

## MCP-Tools

| Tool | CLI-Befehl | Beschreibung |
|------|------------|--------------|
| `discover_commands` | `?`, `exec ?`, `config ?`, `help` | Befehlsbaum vom Gerät (gecacht) |
| `run_command` | beliebig | Einzelbefehl ausführen |
| `run_commands` | beliebig | Mehrere Befehle in einer SSH-Session |
| `get_dsl_info` | `exec dslinfo` | Sync-Status, Profil, Raten, SNR |
| `get_system_info` | `exec sysinfo` | Modell, Firmware, Build-Infos |
| `get_device_time` | `exec date` | Gerätezeit |
| `get_services` | `exec services` | Offene Dienste/Ports |
| `get_config_status` | `exec cfg status` | Config-Profil-Status |
| `get_command_tree_summary` | — | Gecachter Discovery-Baum |

`run_command` / `run_commands` decken per Definition alle vom Gerät akzeptierten Befehle ab. Ungültige Befehle liefern die Geräte-Fehlermeldung im Ergebnis, keine Exception nach außen.

### Beispiel `get_dsl_info` (FW 5.2.8, verifiziert)

```
Status : Showtime
Mode : VDSL2
Profile : 17a
Annex : ANNEX B
DSL Version : 5.12.31.0_B_A60901
Line Uptime : …
Downstream Line Rate : … kbps
Upstream Line Rate : … kbps
SNR Downstream : … dB
SNR Upstream : … dB
```

**Nicht verfügbar** in `exec dslinfo` auf 5.2.8: Attenuation, CRC/FEC/ES/SES — dafür gibt es bewusst kein Convenience-Tool.

## Verifizierter Befehlsbaum (Kurzüberblick)

### Top-Level (`?`)

`help`, `quit`, `logout`, `history`, `enable`, `exit`, `config`, `exec`

### Exec (`exec ?`)

`date`, `ping`, `reboot_system`, `operation_mode`, `lan_mtu`, `wan_mtu`, `dot3ah_oam`, `y1731`, `dsl_dbg`, `dsl_35b_enhance`, `dsl_35b_target`, `process_dbg`, `tr069`, `coredump`, `sysinfo`, `telnet`, `cfg`, `services`, `dslinfo`, `nat_prio`

### Config (`help`, Auszug)

```
config Configuration Physical_Interface
config Configuration WAN WAN_Connections
config Monitoring DSL_Status Monitoring_DSL_General
config Monitoring DSL_Status Monitoring_DSL_Tone
config System_Maintenance Device_Settings Time
config System_Maintenance Management Access_Control
…
```

Config-Zweige nutzen Web-Form-CLI (`show` / `edit`); ohne `enable` kaum schreibbar.

Vollständiger Baum: `cache/command_tree.json` oder `discover.py 2 --refresh`.

## Discovery manuell

```bash
.venv/bin/python discover.py 2 --refresh
```

Parameter: Tiefe (Standard `2`), `--refresh` erzwingt Neuerkennung.

## Projektstruktur

```
server.py       MCP-Server (FastMCP)
vigor_ssh.py    SSH auth_none, CLI-Login, Prompt-Handling
discover.py     Befehls-Discovery via ?
parsers.py      Regex-Parser für verifizierte Ausgaben
pyproject.toml  Abhängigkeiten
cache/          command_tree.json (generiert, nicht committen)
.env            Credentials (lokal, nicht committen)
```

## Hinweise und Grenzen

- **Bridge-Modem**: Absichtlich eingeschränkte CLI — kein voip/qos/etc. wie bei großen DrayOS-Routern.
- **Kein `enable`**: Privilegierte Config-Befehle über CLI nicht erreichbar.
- **Timing**: `VIGOR_IDLE_SEC` erhöhen (z. B. `1.0`), falls Ausgaben abgeschnitten werden.
- **Credentials**: Niemals in Code, Logs oder Commits — nur in `.env`.
- **Parser**: Nur für tatsächlich gelieferte Felder; bei Firmware-Änderungen Discovery und Parser neu verifizieren.

## Fehlerbehebung

| Symptom | Ursache / Lösung |
|---------|------------------|
| Leere SSH-Ausgabe | Kein PTY / `exec_command` — dieser Server nutzt `invoke_shell` |
| `Access denied` bei `enable` | Erwartet; am 167 kein Enable-Passwort |
| `Authentication failed` (Paramiko) | Am 167 `auth_none` + CLI-Login — `vigor_ssh.py` nutzt Transport, nicht Passwort-SSH |
| Abgeschnittene CLI-Ausgabe | `VIGOR_IDLE_SEC` in `.env` erhöhen |
| MCP-Tools fehlen in Cursor | Eintrag in `~/.cursor/mcp.json` fehlt — siehe oben |

## Lizenz / Gerät

Getestet gegen DrayTek Vigor 167, Firmware **5.2.8**, Host `192.168.167.1`.
