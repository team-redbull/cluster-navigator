from pathlib import Path

from navigator.models import DnsConfig


def parse_resolv_conf(content: str) -> DnsConfig:
    servers: list[str] = []
    search: list[str] = []
    for raw in content.splitlines():
        parts = raw.split("#", 1)[0].split()
        if len(parts) < 2:
            continue
        if parts[0] == "nameserver":
            servers.append(parts[1])
        elif parts[0] in ("search", "domain"):
            search.extend(parts[1:])
    return DnsConfig(servers=servers, search_domains=search)


def read_resolv_conf(path: Path = Path("/etc/resolv.conf")) -> DnsConfig:
    """Read the pod's resolver config.

    The CronJob runs with ``dnsPolicy: Default``, which gives the pod the
    node's own /etc/resolv.conf. That is how the collector reports the DNS
    servers the nodes use without a privileged pod or a hostPath mount.
    """
    return parse_resolv_conf(path.read_text())
