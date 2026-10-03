"""A minimal read-only Kubernetes API client.

The collector makes about a dozen GET calls, so it talks to the API server
directly with httpx instead of pulling in the full kubernetes client.
"""

import os
from pathlib import Path

import httpx

SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


class KubeClient:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    @classmethod
    def in_cluster(cls, sa_dir: Path = SERVICE_ACCOUNT_DIR, timeout: float = 20.0) -> "KubeClient":
        host = os.environ["KUBERNETES_SERVICE_HOST"]
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        if ":" in host:  # IPv6 literal
            host = f"[{host}]"
        token = (sa_dir / "token").read_text().strip()
        client = httpx.Client(
            base_url=f"https://{host}:{port}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            verify=str(sa_dir / "ca.crt"),
            timeout=timeout,
        )
        return cls(client)

    def get(self, path: str) -> dict | None:
        """Return the object at ``path``, or None when it does not exist.

        A 404 is a normal answer here: it is how the collector learns that an
        optional API (MCE, HyperShift, OpenShift Virtualization) is not
        installed. Every other failure raises.
        """
        response = self._client.get(path)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def list(self, path: str) -> list[dict]:
        body = self.get(path)
        if body is None:
            return []
        return body.get("items") or []

    def close(self) -> None:
        self._client.close()
