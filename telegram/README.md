# Telegram

This directory is the Telegram processing layer for polyData.

- `topics/`: group/forum topic publishing. It reads runtime panel API snapshots,
  formats them into Telegram messages, deduplicates already-sent updates, and
  sends them through the Telegram Bot API.
- `bot/`: reserved for the interactive user-called bot, similar in spirit to
  GMGN/AVE bots. Command handlers and query routing should live here.

The old root module entrypoints remain as compatibility shims, but new code
should import from `telegram.topics.*`.

## First Run

Create the Telegram channels/groups manually, add your bot as an admin, then
set:

```bash
POLYDATA_TELEGRAM_BOT_TOKEN=123:abc
POLYDATA_TELEGRAM_REMOTE_API_BASE=https://<your-api-host>/wm-api
POLYDATA_TELEGRAM_CHANNEL_NEWS=-1001234567890
POLYDATA_TELEGRAM_CHANNEL_INTEL=-1001234567890
POLYDATA_TELEGRAM_CHANNEL_ALPHA=-1001234567890
POLYDATA_TELEGRAM_CHANNEL_MACRO=-1001234567890
POLYDATA_TELEGRAM_CHANNEL_NBA=@your_nba_channel
POLYDATA_TELEGRAM_CHANNEL_WORLDCUP=-1001234567890
POLYDATA_TELEGRAM_CHANNEL_WEATHER=@your_weather_channel
POLYDATA_TELEGRAM_CHANNEL_MONITOR=@your_main_channel
POLYDATA_TELEGRAM_THREAD_NEWS=12
POLYDATA_TELEGRAM_THREAD_INTEL=14
POLYDATA_TELEGRAM_THREAD_ALPHA=10
POLYDATA_TELEGRAM_THREAD_MACRO=8
POLYDATA_TELEGRAM_THREAD_WORLDCUP=16
```

`latest-content` publishes global headlines to News. Scheduled Intel posts come
from Geo Sanctions Shock, Policy Progress, and the original Intel feeds.
The publisher checks market-specific Related News against one leading contract
per event from the macro monitor, up to six contracts per rotation. It sends
the matched public articles with their original publication time and relation.
`worldcup-intel` publishes a compact Signals / News /
Weather summary to the World Cup topic and links to
`https://www.polymonitor.club/?workspace=worldcup`.

Dry run:

```bash
python -m telegram.topics.publisher --once --dry-run
```

The publisher probes configured API candidates with `/health` and uses the
first healthy one. For the current split setup, the remote GCP API usually
looks like `http://<gcp-host>/wm-api`; local development API is only a fallback.

Prime state without sending the current backlog:

```bash
python -m telegram.topics.publisher --once --prime
```

Run continuously:

```bash
python -m telegram.topics.publisher --watch
```

Publishing belongs to the standalone publisher above; reading a website/API panel never sends Telegram messages.

## Panel delivery catalog

`topics/catalog.py` accounts for every frontend Panel and every server runtime
Panel. Each entry has exactly one delivery mode:

- `specialized`: a product-specific formatter and topic;
- `generic`: a redacted, concise semantic-change summary;
- `aggregate`: already represented by another Telegram feed;
- `market-scoped`: needs a selected market or a dedicated alert event;
- `browser-only`: no independent server snapshot exists;
- `non-pushable`: high-frequency visual data that should not become messages.

The watch loop checks 13 primary sources plus six original generic sources per
cycle, rotating through the 42 that lack another delivery path. Retained stale
and warming snapshots wait for usable data. The send state records the
Telegram message ID, server date and source when returned by the Bot API.
The normal schedule and the explicit all-panels audit fetch up to four
snapshots concurrently, with up to 10 seconds of read timeout per request:

```bash
python -m telegram.topics.publisher --once --target all-panels --dry-run
```

This command prints candidates and does not call Telegram or mutate dedupe
state. Result JSON reports these as `previewed`; the legacy `sent` field also
counts printed dry-run previews for backward compatibility, and must be read
together with `dry_run=true`. Before enabling recurring `all-panels` delivery, prime the current
snapshot so existing records are not posted as a backlog:

```bash
python -m telegram.topics.publisher --once --target all-panels --prime
```

The first non-dry `all-panels` run also primes automatically. The catalog
version is recorded only after all expected runtime and non-runtime snapshots
were fetched; a partial run primes the returned candidates but remains
unprimed, so recovered sources are safely absorbed on the next run. Publisher
heartbeat/result JSON exposes formatter counts for specialized, generic,
empty, aggregate, market-scoped, browser-only, non-pushable, unsupported and
format-error outcomes.
