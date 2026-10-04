"""Entry point for the CronJob: collect once, push once, exit.

Environment:
  NAVIGATOR_URL                  Base URL of the Cluster Navigator server.
  INGEST_TOKEN / INGEST_TOKEN_FILE   Bearer token for the ingest endpoint.
  SEGMENTS_MANAGER_URL           Base URL of Segments Manager, where this cluster's
                                 segments are looked up. Empty: no segments reported.
  CLUSTER_TYPE                   auto (default), generic, click, mce or kubevirt.
  CLUSTER_NAME                   Overrides the detected cluster name.
  CLUSTER_NETWORK                The network this cluster belongs to. Empty: none.
  TLS_CA_FILE                    CA bundle used to verify the server's and
                                 Segments Manager's certificates.
  TLS_INSECURE_SKIP_VERIFY       true to skip TLS verification (not for production).
  DRY_RUN                        true to print the report instead of sending it.
"""

import json
import logging
import os
import sys
from pathlib import Path

import httpx

from navigator.collector.collect import Collector
from navigator.collector.kube import KubeClient
from navigator.collector.push import push

logger = logging.getLogger("navigator.collector")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _token() -> str:
    token_file = os.environ.get("INGEST_TOKEN_FILE")
    if token_file:
        return Path(token_file).read_text().strip()
    return os.environ.get("INGEST_TOKEN", "").strip()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dry_run = _truthy(os.environ.get("DRY_RUN"))
    url = os.environ.get("NAVIGATOR_URL", "").strip()
    token = _token()
    if not dry_run and (not url or not token):
        logger.error("NAVIGATOR_URL and INGEST_TOKEN (or INGEST_TOKEN_FILE) are required")
        return 2

    verify: bool | str = True
    if _truthy(os.environ.get("TLS_INSECURE_SKIP_VERIFY")):
        verify = False
    elif os.environ.get("TLS_CA_FILE"):
        verify = os.environ["TLS_CA_FILE"]

    kube = KubeClient.in_cluster()
    segments_client = httpx.Client(verify=verify, timeout=15.0)
    try:
        report = Collector(
            kube,
            type_override=os.environ.get("CLUSTER_TYPE"),
            name_override=os.environ.get("CLUSTER_NAME"),
            network=os.environ.get("CLUSTER_NETWORK"),
            segments_manager_url=os.environ.get("SEGMENTS_MANAGER_URL", "").strip() or None,
            segments_client=segments_client,
        ).collect()
    finally:
        segments_client.close()
        kube.close()

    logger.info(
        "collected %s (%s): type=%s via %s, %d nodes, %d segments, %d step errors",
        report.name, report.cluster_id, report.type.value, report.detection.source,
        len(report.nodes), len(report.segments), len(report.errors),
    )
    if dry_run:
        print(json.dumps(report.model_dump(mode="json", by_alias=True), indent=2))
        return 0

    push(report, url=url, token=token, verify=verify)
    logger.info("report delivered to %s", url)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        logger.exception("collector run failed")
        sys.exit(1)
