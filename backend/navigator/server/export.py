"""The cluster list as a CSV file."""

import csv
import io

from navigator.server.views import ClusterCard

# A spreadsheet runs a cell that starts with one of these as a formula. Names
# and addresses come from the collectors, so such a cell is made plain text.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: str | None) -> str:
    text = value or ""
    return "'" + text if text.startswith(_FORMULA_START) else text


def clusters_csv(cards: list[ClusterCard], *, include_mce: bool) -> str:
    """One row per cluster. The MCE column exists only for callers who may see it."""
    out = io.StringIO()
    writer = csv.writer(out)
    header = ["name", "version", "segment", "router_lb"]
    if include_mce:
        header.append("mce")
    writer.writerow(header)
    for card in cards:
        row = [
            _cell(card.name),
            _cell(card.openshift_version),
            _cell("; ".join(card.segments)),
            _cell("; ".join(card.router_lb)),
        ]
        if include_mce:
            row.append(_cell(card.mce))
        writer.writerow(row)
    return out.getvalue()
