# CLAUDE.md

Project context for Claude Code. Read this before making changes.

## Project Overview

A passive mitmproxy addon for the Discord desktop client. It decodes gateway and REST traffic from the official client, normalizes events, and publishes them to NATS. Downstream consumers (archivers, dashboards, anything else) are separate projects that subscribe to NATS; they are out of scope here.

Scope is deliberately narrow: **decode Discord traffic, publish to NATS**. Nothing else.

The proxy is for the operator's own account on their own machine. It is strictly read-only: observe and publish, never inject, modify, or automate. This constraint is load-bearing for ToS compliance.

## Architecture

```
Discord client ──(TLS)──> mitmproxy + addon ──(TLS)──> Discord servers
                                │
                                └──> NATS (publish only)
```

The Discord client runs on the host. The proxy and NATS run in Docker via `docker compose up`. In this setup NATS listens on container port 4222 but is published to the host as `nats://127.0.0.1:4333` (see `compose.yaml`), so host-side consumers — `nats sub`, the example scripts — all use port 4333. A bare `nats-server -js` started locally (no Docker) uses the NATS default 4222 instead; see the local-dev section below.

## Discord Protocol Notes

- Gateway is a WebSocket negotiated with `encoding=etf` and `compress=zstd-stream`. Decompressor state must persist across messages within a connection; each new WebSocket gets a fresh decoder instance. Connections that negotiate any other compression are skipped with a warning (the addon will not silently mis-decode).
- erlpack handles ETF decoding. Atom keys arrive as `erlpack.Atom` (a `str` subclass); string values arrive as `bytes`. `_decode()` in `events.py` converts both to plain `str`.
- REST is standard HTTPS. Outgoing message sends go here; the gateway echoes a MESSAGE_CREATE afterward, including to the sender's own session.
- Gateway delivers events for every channel the user can read across all guilds plus DMs, over one WebSocket. No per-channel subscription.
- Snowflake IDs encode creation time and are the canonical order. Do not rely on arrival order.
- Voice and video use separate UDP streams. Out of scope.

## Project Structure

```
discord_proxy/
├── pyproject.toml
├── uv.lock
├── src/
│   └── discord_proxy/
│       ├── addon.py          # mitmproxy entry; exposes `addons` list
│       ├── gateway/
│       │   ├── codec.py      # ETF + zstd-stream decoder + factory
│       │   ├── events.py     # normalization (pure functions)
│       │   └── addon.py      # GatewayAddon, hooks websocket_message
│       ├── rest/
│       │   ├── routes.py     # endpoint classification
│       │   └── addon.py      # RestAddon, hooks request/response
│       ├── nats_client.py    # async NATS publisher
│       ├── envelope.py       # shared event envelope
│       └── config.py
├── examples/                 # standalone PEP 723 consumer scripts
│   ├── subject_tree.py       # live scrollable subject tree with name resolution
│   ├── firehose.py           # colored one-line-per-event tail
│   ├── envelope_peek.py      # wait for one event, pretty-print it
│   ├── rate_meter.py         # live subject-tree with per-node events/sec and sparklines
│   ├── schema_sniff.py       # infer and display payload schemas; dump to md/ts/json
│   ├── rest_classify_sniff.py # rank unclassified REST routes and propose _add() entries
│   └── replay.py             # record events to JSONL and replay with original timing
└── tests/
```

Dependency management uses `uv`. Add deps with `uv add <pkg>`, sync with `uv sync`, run commands inside the project venv with `uv run <cmd>`. The `uv.lock` file is committed; do not edit it by hand. mitmproxy, nats-py, erlpack, and zstandard are project dependencies, not system installs.

## Event Envelope

All published events share this shape:

```json
{
  "captured_at": "2026-04-19T12:34:56.789Z",
  "source": "gateway" | "rest",
  "event_type": "MESSAGE_CREATE",
  "guild_id": "123..." | null,
  "channel_id": "456..." | null,
  "user_id": "789..." | null,
  "payload": { ...normalized... },
  "raw": { ...original... }
}
```

Keep `raw` alongside `payload`. Schema additions can be backfilled by reparsing; data lost to schema drift cannot.

## NATS Subjects

```
discord.gateway.<event_type_lowercase>
discord.guild.<guild_id>.channel.<channel_id>.<EVENT_TYPE>
discord.dm.<channel_id>.<EVENT_TYPE>
discord.rest.<METHOD>.<route_template_tokens>
discord.rest.unclassified.<METHOD>.<route_template_tokens>
discord.meta.<addon_event>
```

`<route_template_tokens>` is the template rendered as NATS-safe tokens by `rest_subject()` in `nats_client.py`: leading slash stripped, `/` → `.`, and `{`/`}` removed. So `/channels/{channel_id}/messages/{message_id}` publishes under `discord.rest.GET.channels.channel_id.messages.message_id`. The literal `route_template` with braces intact is still available inside the payload (`route_template` field) and the envelope's `ids` map.

Classified REST events match a known route pattern; their payload includes semantic `ids` and `"classified": true`. Unclassified events use a generic template (snowflake IDs replaced with `{id}`, other segments kept literal) and carry `"classified": false` with null `guild_id`/`channel_id`/`user_id` on the envelope.

REST `payload` fields: `method`, `path` (path only, no query string), `query` (query string without `?`, or `""`), `route_template`, `ids` (map of named snowflake IDs), `classified`, `status`, `elapsed_ms`, `body` (parsed JSON — object, array, or scalar — or `null` when the response was missing, empty, or not JSON).

Publish each event to both the flat `discord.gateway.<type>` subject and the scoped subject. Consumers filter with wildcards.

Subject tokens cannot contain dots, whitespace, or wildcards. Snowflakes are safe.

## Development Workflow

### Normal operation (Docker)

```sh
docker compose up
```

Starts NATS (with JetStream and a pre-created `discord.>` stream), then the proxy. The mitmproxy CA cert is generated on first run and persisted via the `~/.mitmproxy` bind mount. Trust the cert on the host once; see the per-OS instructions below.

### Local dev without Docker

Project setup (all platforms): `uv sync` from the repo root installs all deps into `.venv/`. Add runtime deps with `uv add`, dev-only deps with `uv add --dev`. Never `pip install` into the venv directly; it bypasses the lockfile.

After cloning, install the pre-commit hook once:

```sh
uv run pre-commit install
```

This runs ruff, mypy, and pytest automatically before each commit.

### Windows 10/11

On Windows 10, WinGet may need to be installed first via the App Installer from the Microsoft Store.

```powershell
# Install NATS
winget install NATSAuthors.NATSServer NATSAuthors.CLI

# Install project dependencies
uv sync

# Trust mitmproxy CA (requires elevated PowerShell)
Import-Certificate -FilePath "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer" -CertStoreLocation Cert:\LocalMachine\Root
```

Launch Discord with `--proxy-server=http://127.0.0.1:8765`. For persistent autostart, edit `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Discord` and add `--process-start-args "--proxy-server=http://127.0.0.1:8765"` after `--processStart Discord.exe`.

### macOS

```sh
# Install NATS
brew install nats-server nats-io/nats-tools/nats

# Install project dependencies
uv sync

# Trust mitmproxy CA
sudo security add-trusted-cert -d -p ssl -p basic \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

The macOS autoUpdater does not honor the proxy flag, so the updater must be disabled for interception to work on the main app. Add `"SKIP_HOST_UPDATE": true` to `~/Library/Application Support/discord/settings.json`, then launch:

```sh
/Applications/Discord.app/Contents/MacOS/Discord --proxy-server=http://127.0.0.1:8765
```

### Linux

NATS binaries are available on the nats-io/nats-server and nats-io/natscli GitHub releases. If Go is installed, `go install github.com/nats-io/nats-server/v2@latest` and `go install github.com/nats-io/natscli/nats@latest` also work. Distro-specific packages exist but versions vary.

```sh
# Arch Linux (via yay or paru)
yay -S nats-server natscli

# Install project dependencies (all distros)
uv sync

# Trust mitmproxy CA (Debian/Ubuntu)
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
sudo update-ca-certificates

# Trust mitmproxy CA (Fedora/RHEL)
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# Trust mitmproxy CA (Arch)
sudo trust anchor ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Launch Discord:

```sh
discord --proxy-server=http://127.0.0.1:8765
# or, for Flatpak:
flatpak run com.discordapp.Discord --proxy-server=http://127.0.0.1:8765
```

Modify the `.desktop` file under `~/.local/share/applications/` to persist the flag across launches.

### Each session (all platforms, local dev)

```sh
# Terminal 1: NATS (listens on default port 4222)
nats-server -js

# Terminal 2: mitmproxy with the addon (reads DISCORD_PROXY_NATS_URL; default nats://127.0.0.1:4222)
uv run mitmdump -s src/discord_proxy/addon.py

# Terminal 3: tail events to verify flow (nats-cli defaults to 4222)
nats sub "discord.>"
```

The `examples/` scripts hardcode `NATS_URL = "nats://127.0.0.1:4333"` to match the Docker setup. For bare local nats-server (4222), either edit the `NATS_URL` constant at the top of the script you're running or start `nats-server -js -p 4333`.

### Testing and linting

```sh
# Unit tests
uv run pytest

# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy

# Record a session for use as a replay fixture
uv run mitmdump -w capture.flow

# Replay a fixture against the addon
uv run mitmdump -r capture.flow -s src/discord_proxy/addon.py
```

All three (`pytest`, `ruff check`, `mypy`) must pass before committing. Note that `mypy` is scoped to `src/` and `tests/` (see `pyproject.toml`); `examples/` scripts are PEP 723 single-files and intentionally not type-checked as part of the project.

## Code Conventions

- Python 3.12+. Type hints required. mypy (strict, configured in pyproject.toml) must pass.
- Async for all I/O. Blocking in hook paths stalls the proxy.
- Normalization is pure: raw in, normalized out, no side effects.
- Decode failures publish `discord.meta.decode_error` and continue. The payload carries `flow_id` and `raw_b64` (the offending bytes base64-encoded); the envelope `raw` is `{}`. Never kill the addon on malformed input.
- Do not log READY or READY_SUPPLEMENTAL payloads at DEBUG. They are megabytes.
- Keep `CLAUDE.md` and `README.md` in sync with the implementation. Any change to ports, subjects, config keys, protocol behavior, project structure, or workflow commands should be reflected in both files before committing.

## Hard Constraints

The addon must not:
- Modify outgoing WebSocket frames or REST requests
- Inject synthetic gateway commands
- Rewrite the IDENTIFY payload to force JSON encoding
- Automate any user action
- Capture voice/video payloads

If a feature needs any of these, it does not belong in this project.

## Pitfalls

- Discord updates may rewrite the autostart configuration and strip the proxy flag. On Windows this affects the Run registry entry. Check after updates.
- On macOS, the autoUpdater bypasses the proxy flag entirely. `SKIP_HOST_UPDATE` in settings.json is required for proxying to work at all on the main app; if Discord updates itself despite this, re-verify the setting.
- Gateway reconnects are routine. Each new WebSocket gets a fresh `ZstdStreamDecoder`; do not share decoder state across connections.
- Do not commit `.flow` or `.jsonl` fixtures containing real message content from other users. Both extensions are gitignored by default. `examples/replay.py` writes `.jsonl` recordings of live NATS traffic; synthesize or anonymize before sharing them.
