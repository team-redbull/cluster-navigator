"""Whether each cluster's OpenShift console answers.

The one place the server calls out to clusters. In the background, every
`CONSOLE_CHECK_INTERVAL_SECONDS`, it sends a HEAD request to every console URL
the collectors reported, all at once (asyncio, at most `CONCURRENCY` in
flight), so one sweep takes about as long as the slowest console, not the sum
of them.

A console is up when it answers with anything below 500. A 5xx (the router's
"Application is not available" when the console pods are gone), a timeout or
a connection error means down. Certificates are not checked: on-site router
CAs are not in the pod's trust store, and a HEAD request carries nothing secret.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable

import httpx

logger = logging.getLogger("navigator.server.console")

CONCURRENCY = 50


class ConsoleChecker:
    def __init__(self, *, timeout: float = 5.0, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            verify=False,
            follow_redirects=True,
            timeout=timeout,
            limits=httpx.Limits(max_connections=CONCURRENCY),
        )
        self._slots = asyncio.Semaphore(CONCURRENCY)
        # Console URL -> whether it answered on the last sweep. A URL that has
        # not been checked yet is missing, and counts as up.
        self.up: dict[str, bool] = {}

    async def check(self, url: str) -> bool:
        async with self._slots:
            try:
                response = await self._client.head(url)
            # Not only httpx.HTTPError: a malformed URL from one collector must
            # fail its own check, not the whole sweep.
            except Exception as exc:  # noqa: BLE001
                logger.debug("console %s did not answer: %s", url, exc)
                return False
            return response.status_code < 500

    async def sweep(self, urls: Iterable[str]) -> dict[str, bool]:
        """Check every console concurrently. Replaces the previous results."""
        urls = sorted(set(urls))
        results = await asyncio.gather(*(self.check(url) for url in urls))
        self.up = dict(zip(urls, results, strict=True))
        return self.up

    async def run(
        self,
        urls: Callable[[], Awaitable[Iterable[str]]],
        interval: float,
        on_sweep: Callable[[], None],
    ) -> None:
        """Sweep forever, `interval` seconds apart. Cancel the task to stop."""
        while True:
            try:
                before = self.up
                for url, up in (await self.sweep(await urls())).items():
                    # Log changes only, not every check.
                    if before.get(url, True) != up:
                        logger.info("console %s is %s", url, "up again" if up else "down")
                on_sweep()
            except Exception:  # noqa: BLE001 - a bad sweep must not stop the next one
                logger.exception("console check failed")
            await asyncio.sleep(interval)

    async def close(self) -> None:
        await self._client.aclose()
