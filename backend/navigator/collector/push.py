"""Sends a report to the server's ingest endpoint."""

import logging
import time

import httpx

from navigator.models import ClusterReport

logger = logging.getLogger(__name__)

INGEST_PATH = "/api/v1/ingest/reports"


class PushError(RuntimeError):
    pass


def push(
    report: ClusterReport,
    *,
    url: str,
    token: str,
    verify: bool | str = True,
    attempts: int = 3,
    backoff: float = 5.0,
    client: httpx.Client | None = None,
) -> None:
    """POST the report, retrying when the server could not be reached.

    A 4xx means the server understood and refused (bad token, bad payload).
    Retrying will not change that, so it fails straight away.
    """
    owned = client is None
    client = client or httpx.Client(verify=verify, timeout=30.0)
    endpoint = url.rstrip("/") + INGEST_PATH
    body = report.model_dump(mode="json", by_alias=True)
    try:
        last_error = "no attempt made"
        for attempt in range(1, attempts + 1):
            try:
                response = client.post(endpoint, json=body, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 300:
                    return
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                if 400 <= response.status_code < 500:
                    raise PushError(f"server refused the report: {last_error}")
            logger.warning("push attempt %d/%d failed: %s", attempt, attempts, last_error)
            if attempt < attempts:
                time.sleep(backoff * attempt)
        raise PushError(f"could not deliver the report after {attempts} attempts: {last_error}")
    finally:
        if owned:
            client.close()
