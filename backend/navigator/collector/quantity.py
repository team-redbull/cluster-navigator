"""Kubernetes resource quantities ("64", "500m", "263856Ki") as plain numbers."""

_BINARY = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50}
_DECIMAL = {"k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12, "P": 10**15}


def parse_quantity(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = value.strip()
    if not text:
        return 0.0
    for suffix, factor in _BINARY.items():
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * factor
    if text.endswith("m"):
        return float(text[:-1]) / 1000
    for suffix, factor in _DECIMAL.items():
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * factor
    return float(text)


def to_gi(value: str | int | float | None) -> float:
    return round(parse_quantity(value) / 2**30, 1)
