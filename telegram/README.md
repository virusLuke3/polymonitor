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
POLYDATA_TELEGRAM_CHANNEL_WEATHER=@your_weather_channel
POLYDATA_TELEGRAM_CHANNEL_MONITOR=@your_main_channel
POLYDATA_TELEGRAM_THREAD_NEWS=12
POLYDATA_TELEGRAM_THREAD_INTEL=14
POLYDATA_TELEGRAM_THREAD_ALPHA=10
POLYDATA_TELEGRAM_THREAD_MACRO=8
```

`latest-content` publishes to the News topic. Market-scoped `related-news`
publishes one compact summary to the Intel topic so the News topic stays focused
on global headlines.

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

To publish the same payload when the live website/API fetches a supported panel,
enable the API-side bridge on the machine running `polydata-api.service`:

```bash
POLYDATA_TELEGRAM_PUBLISH_ON_API_FETCH=true
```

The API returns normally while a background thread sends Telegram messages.
`data/telegram_state.json` deduplicates messages so repeated page refreshes do
not repost the same update.
