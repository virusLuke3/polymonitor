"""One MoviOdds owner: ordered WS evidence, catalog and bounded archive jobs."""
from __future__ import annotations

import asyncio
import json
import os
import random
import signal
import time
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from api.clients.source_transport import SourceSession, _retry_seconds
from api.services.bookmaker_panels import moviodds, movi_history
from api.services.bookmaker_panels.movi_archive import Archive, configured_int, enabled
from api.services.bookmaker_panels.movi_stream import Stream, NAMESPACE, KEY, catalog
from data_sources import source_value
from runtime.environment import load_environment
from runtime.redis_snapshot_store import create_snapshot_store


class Owner:
    def __init__(self, store, archive):
        self.store, self.archive = store, archive
        self.sports = [s.key.split(':')[2] for s in moviodds.specs()]
        if not self.sports:
            raise ValueError('MoviOdds has no enabled sports')
        self.state = Stream(self.sports)
        self.stop = asyncio.Event()
        self.reconnect = asyncio.Event()
        self.catalog_ready = asyncio.Event()
        self.catalog_error = None
        self.rest_summary = {}
        self.started = time.time()

    async def publish(self):
        value = self.state.payload(time.time())
        value.update(catalogError=self.catalog_error, archive=self.rest_summary, startedAt=self.started)
        # Shared Redis owner lease is checked atomically with the write.
        if not await asyncio.to_thread(self.store.set, NAMESPACE, KEY, value, 60):
            raise RuntimeError('MoviOdds stream publication failed')

    async def publication(self):
        while not self.stop.is_set():
            await self.publish()
            await asyncio.sleep(5)

    async def catalogs(self):
        lookback = configured_int('POLYDATA_MOVIODDS_LOOKBACK_DAYS', 7, 1, 30)
        failures = 0
        while not self.stop.is_set():
            delay = 60
            try:
                raw = await asyncio.to_thread(movi_history.request, '/catalog', {'sport': 'all'}, time.monotonic() + 95)
                rows = catalog(raw, self.sports)
                now = time.time()
                await asyncio.to_thread(self.archive.catalog, raw, rows, now, lookback)
                self.state.set_catalog(rows, now)
                self.catalog_ready.set()
                self.catalog_error, failures = None, 0
            except Exception as exc:
                failures += 1
                self.catalog_error = type(exc).__name__
                delay = min(900, 60 * 2**min(failures - 1, 4))
                response = getattr(exc, 'response', None)
                if response is not None and response.status_code in (429, 503):
                    delay = max(delay, _retry_seconds(response.headers.get('Retry-After')))
                if response is not None and response.status_code in (401, 403):
                    delay = max(delay, 3600)
            await asyncio.sleep(delay)

    async def histories(self):
        last_prune = 0
        while not self.stop.is_set():
            rows = await asyncio.to_thread(movi_history.collect, self.archive, self.sports, self.stop.is_set)
            self.rest_summary = await asyncio.to_thread(self.archive.status)
            print(json.dumps({'owner': 'moviodds', 'archiveJobs': rows, **self.rest_summary}), flush=True)
            if time.time() - last_prune > 3600:
                await asyncio.to_thread(self.archive.prune, time.time())
                last_prune = time.time()
            await asyncio.sleep(60)

    async def receive(self, ws, queue):
        async for raw in ws:
            body = raw.encode() if isinstance(raw, str) else raw
            msg = json.loads(body)
            # Bounded queue; falling behind invalidates the stream and requires
            # a new baseline instead of quietly dropping price/removal events.
            await asyncio.wait_for(queue.put((body, msg, time.time())), timeout=10)
        raise ConnectionError('MoviOdds socket closed')

    async def consume(self, queue):
        while True:
            batch = [await queue.get()]
            while len(batch) < 100 and not queue.empty():
                batch.append(queue.get_nowait())
            # A failed durable write must not publish prices or advance clocks.
            saving = asyncio.create_task(asyncio.to_thread(self.archive.frames, batch))
            try:
                await asyncio.shield(saving)
            except asyncio.CancelledError:
                # Finish the transaction before closing/restarting this owner.
                await saving
                raise
            for _, msg, now in batch:
                self.state.apply(msg, now)
                queue.task_done()

    async def sockets(self):
        url = source_value('POLYDATA_MOVIODDS_WS_URL')
        parsed = urlsplit(url)
        if parsed.scheme != 'wss' or not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError('Configure a credential-free WSS endpoint in .env')
        key = source_value('POLYDATA_MOVIODDS_API_KEY')
        transport = SourceSession()
        transport.trust_env = False
        routes = transport.routes.get(parsed.hostname)
        if not routes:
            raise ValueError('MoviOdds WS requires an explicit .env source route (empty string permits direct)')
        failures = 0
        try:
            await self.catalog_ready.wait()
            while not self.stop.is_set():
                delay = min(30, 3 * 2**min(failures, 4))
                tasks = []
                opened = time.monotonic()
                try:
                    if not transport._due(parsed.hostname + ':rate-limit'):
                        raise ConnectionError('MoviOdds source cooldown')
                    eligible = [(i, p) for i, p in enumerate(routes[:3]) if transport._due(f'{parsed.hostname}:{i}')]
                    if not eligible:
                        raise ConnectionError('MoviOdds routes cooling down')
                    index, proxy = eligible[min(failures // 2, len(eligible) - 1)]
                    async with connect(url, proxy=proxy or None,
                            additional_headers={'X-API-Key': key} if key else None,
                            open_timeout=45, close_timeout=5, ping_interval=20, ping_timeout=10,
                            max_size=1024**2, max_queue=16) as ws:
                        self.state.begin()
                        groups = sorted({g for s in self.sports for g in moviodds.GROUPS[s]})
                        await ws.send(json.dumps({'op': 'subscribe', 'groups': groups}))
                        queue = asyncio.Queue(maxsize=256)
                        self.reconnect.clear()
                        tasks = [asyncio.create_task(self.receive(ws, queue)), asyncio.create_task(self.consume(queue)),
                                 asyncio.create_task(self.reconnect.wait())]
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        if tasks[-1] in done:
                            # Operational resubscription closes only this owner's socket.
                            raise ConnectionError('Resubscription requested')
                        for task in done:
                            task.result()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failures = 0 if time.monotonic() - opened > 60 else failures + 1
                    error = type(exc).__name__ + (': ' + str(exc)[:120] if isinstance(exc, ValueError) else '')
                    response = getattr(exc, 'response', None)
                    code = getattr(response, 'status_code', None)
                    if code in (429, 503):
                        delay = max(delay, _retry_seconds(response.headers.get('Retry-After')))
                        transport._cool(parsed.hostname + ':rate-limit', delay)
                    if code in (401, 403):
                        # Permission failures do not move to a different exit.
                        failures = 0
                        delay = 3600
                    self.state.disconnect(f'HTTP {code}' if code else error)
                    print(json.dumps({'owner': 'moviodds', 'stream': 'disconnected', 'error': error, 'retrySeconds': delay}), flush=True)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    self.state.disconnect(self.state.error or 'reconnecting')
                    await self.publish()
                await asyncio.sleep(delay + random.uniform(0, min(1, delay / 10)))
        finally:
            transport.close()

    async def run(self):
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        loop.add_signal_handler(signal.SIGUSR1, self.reconnect.set)
        tasks = [asyncio.create_task(fn()) for fn in (self.catalogs, self.histories, self.sockets, self.publication)]
        stopping = asyncio.create_task(self.stop.wait())
        try:
            done, _ = await asyncio.wait([*tasks, stopping], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in [*tasks, stopping]:
                task.cancel()
            await asyncio.gather(*tasks, stopping, return_exceptions=True)
            self.state.disconnect('collector-stopped')
            await self.publish()


def main():
    load_environment()
    if not enabled():
        raise SystemExit('MoviOdds stream is not enabled')
    archive = Archive()
    archive.initialize()
    store = create_snapshot_store(os.environ['POLYDATA_SNAPSHOT_SQLITE_PATH'])
    with store.fetch_lock(NAMESPACE, 'owner', timeout=0):
        asyncio.run(Owner(store, archive).run())


if __name__ == '__main__':
    main()
