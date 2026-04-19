# discord-proxy

A passive mitmproxy addon that decodes Discord desktop client traffic and publishes normalized events to NATS.

Scope is narrow on purpose: **decode Discord traffic, publish to NATS**. Downstream archivers, dashboards, and analytics are separate projects that subscribe to the NATS stream.

## Architecture

```
Discord client ──(TLS)──> mitmproxy + addon ──(TLS)──> Discord servers
                               │
                               └──> NATS (publish only)
```

The Discord client runs on the host and proxies through `localhost:8765`. The addon and NATS run in Docker.

## Non-goals

This proxy is for the operator's own account on their own machine and is strictly observe-only. It will not modify outgoing frames, inject gateway commands, rewrite IDENTIFY, automate user actions, or capture voice/video streams. This constraint is load-bearing for Discord ToS compliance.

## Install

Requires [Docker](https://docs.docker.com/get-docker/) with the Compose plugin.

On first run, mitmproxy generates a CA certificate at `~/.mitmproxy/`. Trust it on the host before launching Discord — the proxy cannot intercept TLS until it is.

### Trust the CA

**Windows** (elevated PowerShell):
```powershell
# Start compose once to generate the cert, then stop it
docker compose up proxy --no-deps -d && docker compose stop

Import-Certificate -FilePath "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.cer" `
  -CertStoreLocation Cert:\LocalMachine\Root
```

**macOS:**
```sh
docker compose up proxy --no-deps -d && docker compose stop
sudo security add-trusted-cert -d -p ssl -p basic \
  -k /Library/Keychains/System.keychain \
  ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Add `"SKIP_HOST_UPDATE": true` to `~/Library/Application Support/discord/settings.json` or the macOS autoUpdater will bypass the proxy.

**Linux:**
```sh
docker compose up proxy --no-deps -d && docker compose stop
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
sudo update-ca-certificates  # Debian/Ubuntu; see CLAUDE.md for other distros
```

## Running

```sh
docker compose up
```

Then launch Discord with `--proxy-server=http://127.0.0.1:8765`. See `CLAUDE.md` for per-OS autostart setup.

Tail events from the host:
```sh
nats sub --server=nats://127.0.0.1:4333 "discord.>"
```

## Event envelope

Every published event shares this shape:

```json
{
  "captured_at": "2026-04-19T12:34:56.789Z",
  "source": "gateway",
  "event_type": "MESSAGE_CREATE",
  "guild_id": "123...",
  "channel_id": "456...",
  "user_id": "789...",
  "payload": { "...": "normalized" },
  "raw": { "...": "original decoded ETF" }
}
```

`raw` is kept alongside `payload` so schema additions can be backfilled by reparsing old events.

## NATS subjects

```
discord.gateway.<event_type_lowercase>                      # flat, all events of a type
discord.guild.<guild_id>.channel.<channel_id>.<EVENT_TYPE>  # scoped guild events
discord.dm.<channel_id>.<EVENT_TYPE>                        # scoped DM events
discord.rest.<METHOD>.<route_template>                      # REST traffic (classified routes)
discord.rest.unclassified.<METHOD>.<route_template>         # REST traffic (unrecognized routes)
discord.meta.<addon_event>                                  # decode errors, etc.
```

Each gateway event is published to both the flat subject and its scoped subject. Consumers filter with wildcards.

Classified REST events match a known route; their payload carries semantic `ids` (`guild_id`, `channel_id`, etc.) and `"classified": true`. Unclassified events use a generic template where snowflake segments are replaced with `{id}` and publish under `discord.rest.unclassified.*`; `guild_id`/`channel_id`/`user_id` are null on the envelope.

REST `payload` fields: `method`, `path` (path only, no query string), `query` (query string without `?`, or `""`), `route_template`, `ids`, `classified`, `status`, `elapsed_ms`, `body`.

## Configuration

Config is loaded from `./discord-proxy.toml` (overridable with `DISCORD_PROXY_CONFIG`) and environment variable overrides:

| Key | Env var | Default |
| --- | --- | --- |
| `nats_url` | `DISCORD_PROXY_NATS_URL` | `nats://127.0.0.1:4222` |
| `log_level` | `DISCORD_PROXY_LOG_LEVEL` | `INFO` |

## Protocol notes

- Gateway is a WebSocket negotiated with `encoding=etf` and `compress=zstd-stream`. Connections that negotiate any other compression are skipped with a warning.
- ETF is decoded with `erlpack`. Atom keys come back as `erlpack.Atom` (a `str` subclass); normalization in `gateway/events.py` converts them to plain `str`.
- The gateway delivers events for every channel the user can read plus DMs over one WebSocket. No per-channel subscription exists.

## Development

For a Docker-based dev workflow with live source reloading and the NATS monitoring port exposed, copy the provided example override:

```sh
cp compose.override.example.yaml compose.override.yaml
docker compose up  # auto-merges compose.override.yaml
```

`compose.override.yaml` is gitignored. After code changes, `docker compose restart proxy` picks them up without a rebuild.

For a fully local (no Docker) workflow, requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/):

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy
```

Capturing a session for replay:

```sh
uv run mitmdump -w capture.flow
uv run mitmdump -r capture.flow -s src/discord_proxy/addon.py
```

Do not commit `.flow` or `.jsonl` fixtures containing real traffic from other users without scrubbing them first. Both extensions are gitignored by default.

## Examples

The `examples/` directory contains standalone PEP 723 scripts demonstrating how to consume the NATS stream. Each runs without touching the project venv:

```sh
uv run --script examples/subject_tree.py              # live scrollable subject tree
uv run --script examples/firehose.py                  # colored event tail
uv run --script examples/rate_meter.py                # events/sec table with sparklines
uv run --script examples/schema_sniff.py              # live inferred payload schemas
uv run --script examples/rest_classify_sniff.py       # rank unclassified REST routes
uv run --script examples/envelope_peek.py <subject>   # pretty-print one event
uv run --script examples/replay.py record out.jsonl   # save a session
uv run --script examples/replay.py play out.jsonl     # replay with original timing
```

`schema_sniff.py` can dump the inferred schemas to a file on exit for reference documentation:

```sh
uv run --script examples/schema_sniff.py --format ts --output docs/schemas.ts
uv run --script examples/schema_sniff.py --format md --output docs/schemas.md
uv run --script examples/schema_sniff.py --format json --output docs/schemas.json
```

`rest_classify_sniff.py` tails `discord.rest.unclassified.>`, ranks templates by frequency, and infers semantic ID slot names by cross-referencing path snowflakes against response body fields. Use it to grow `src/discord_proxy/rest/routes.py`:

```sh
uv run --script examples/rest_classify_sniff.py                                    # live table
uv run --script examples/rest_classify_sniff.py --output docs/rest-candidates.md   # markdown report on exit
uv run --script examples/rest_classify_sniff.py --format py --output candidates.py # paste-ready _add() calls
```
