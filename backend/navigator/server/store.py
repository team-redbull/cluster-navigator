"""Persistence: the latest report from each cluster."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from navigator.models import ClusterReport

REPORTS = "reports"
TTL_INDEX = "receivedAt_ttl"


@dataclass(frozen=True)
class StoredReport:
    report: ClusterReport
    received_at: datetime


class Store(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def ping(self) -> bool: ...
    async def upsert_report(self, report: ClusterReport, received_at: datetime) -> None: ...
    async def get_report(self, cluster_id: str) -> StoredReport | None: ...
    async def list_reports(self) -> list[StoredReport]: ...


class MemoryStore:
    """Keeps everything in the process. For tests and throwaway local runs."""

    def __init__(self) -> None:
        self._reports: dict[str, StoredReport] = {}

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def upsert_report(self, report: ClusterReport, received_at: datetime) -> None:
        # A reinstalled cluster comes back with a new ID under the same name.
        for cluster_id, stored in list(self._reports.items()):
            if cluster_id != report.cluster_id and _same_cluster(stored.report, report):
                del self._reports[cluster_id]
        self._reports[report.cluster_id] = StoredReport(report=report, received_at=received_at)

    async def get_report(self, cluster_id: str) -> StoredReport | None:
        return self._reports.get(cluster_id)

    async def list_reports(self) -> list[StoredReport]:
        return list(self._reports.values())


def _same_cluster(a: ClusterReport, b: ClusterReport) -> bool:
    return a.name == b.name and (a.base_domain or "") == (b.base_domain or "")


class MongoStore:
    def __init__(self, uri: str, db_name: str, report_ttl_days: int) -> None:
        from pymongo import AsyncMongoClient

        self._client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)
        self._db = self._client[db_name]
        self._ttl_seconds = report_ttl_days * 86400

    async def init(self) -> None:
        from pymongo.errors import OperationFailure

        reports = self._db[REPORTS]
        try:
            await reports.create_index("receivedAt", name=TTL_INDEX, expireAfterSeconds=self._ttl_seconds)
        except OperationFailure:
            # The index exists with a different TTL: change it in place.
            await self._db.command(
                "collMod", REPORTS, index={"name": TTL_INDEX, "expireAfterSeconds": self._ttl_seconds}
            )
        await reports.create_index([("name", 1), ("baseDomain", 1)])

    async def close(self) -> None:
        await self._client.close()

    async def ping(self) -> bool:
        try:
            await self._db.command("ping")
        except Exception:  # noqa: BLE001 - any failure means "not reachable"
            return False
        return True

    async def upsert_report(self, report: ClusterReport, received_at: datetime) -> None:
        reports = self._db[REPORTS]
        await reports.delete_many(
            {"name": report.name, "baseDomain": report.base_domain or "", "_id": {"$ne": report.cluster_id}}
        )
        await reports.replace_one(
            {"_id": report.cluster_id},
            {
                "name": report.name,
                "baseDomain": report.base_domain or "",
                "receivedAt": received_at,
                "report": report.model_dump(mode="json", by_alias=True),
            },
            upsert=True,
        )

    @staticmethod
    def _stored(doc: dict) -> StoredReport:
        received_at = doc["receivedAt"]
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        return StoredReport(report=ClusterReport.model_validate(doc["report"]), received_at=received_at)

    async def get_report(self, cluster_id: str) -> StoredReport | None:
        doc = await self._db[REPORTS].find_one({"_id": cluster_id})
        return self._stored(doc) if doc else None

    async def list_reports(self) -> list[StoredReport]:
        return [self._stored(doc) async for doc in self._db[REPORTS].find({})]
