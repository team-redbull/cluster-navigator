"""Who may see what. This is the single place access is defined.

Two things are controlled, both on the server so that data a user may not see
never leaves it:

* **cluster types**: which of Generic / Click Cluster / MCE / KubeVirt a role
  can list and open.
* **audiences**: every section of a cluster's expanded view is tagged with an
  audience ("public", "admin", ...). A role sees the sections whose audience
  it holds.

One rule follows from the first: a caller who may not open MCE clusters is
not told which MCE a hosted cluster runs under, since that would name a
cluster they may not see. See ``Principal.can_see_parent_mce``.

A role is granted through membership of a directory group. Adding a new kind
of user is configuration, not code: define the role in ``ROLES``, tag the
sections it should see with a new audience in ``sections.py``, and list its
groups in ``<ROLE>_GROUPS``.

    ROLES='{"storage": {"clusterTypes": ["*"], "audiences": ["public", "storage"]}}'
    STORAGE_GROUPS='["storage-team"]'
"""

import os
from dataclasses import dataclass, field

from navigator.models import ClusterType
from navigator.server.settings import Settings, json_list

PUBLIC = "public"
ADMIN = "admin"
ANY = "*"


@dataclass(frozen=True)
class Role:
    name: str
    cluster_types: frozenset[ClusterType]
    audiences: frozenset[str]
    groups: frozenset[str] = frozenset()
    # An anonymous role applies to everyone, signed in or not.
    anonymous: bool = False


@dataclass(frozen=True)
class Principal:
    """The caller, reduced to what they are allowed to see."""

    username: str | None = None
    roles: tuple[str, ...] = ()
    cluster_types: frozenset[ClusterType] = frozenset()
    audiences: frozenset[str] = frozenset()
    via: str = "anonymous"  # anonymous | session | token
    groups: frozenset[str] = field(default_factory=frozenset)

    @property
    def authenticated(self) -> bool:
        return self.via != "anonymous"

    def can_see_type(self, cluster_type: ClusterType) -> bool:
        return cluster_type in self.cluster_types

    @property
    def can_see_parent_mce(self) -> bool:
        """Whether a hosted cluster's parent MCE may be named to this caller."""
        return self.can_see_type(ClusterType.MCE)

    def can_see_audience(self, audience: str) -> bool:
        return ANY in self.audiences or audience in self.audiences


def _cluster_types(values: list[str]) -> frozenset[ClusterType]:
    if ANY in values:
        return frozenset(ClusterType)
    return frozenset(ClusterType(v) for v in values)


def load_roles(settings: Settings, environ: dict[str, str] | None = None) -> dict[str, Role]:
    environ = os.environ if environ is None else environ
    definitions: dict[str, dict] = {
        "client": {
            "anonymous": True,
            "clusterTypes": [ClusterType.GENERIC.value, ClusterType.CLICK.value],
            "audiences": [PUBLIC],
        },
        "admin": {
            "clusterTypes": [ANY],
            "audiences": [ANY],
            "groups": settings.admin_groups,
        },
    }
    for name, override in settings.json_setting("roles").items():
        definitions[name] = {**definitions.get(name, {}), **override}

    roles: dict[str, Role] = {}
    for name, definition in definitions.items():
        groups = definition.get("groups") or []
        env_groups = environ.get(f"{name.upper()}_GROUPS")
        if env_groups is not None and name != "admin":
            groups = json_list(env_groups, f"{name.upper()}_GROUPS")
        roles[name] = Role(
            name=name,
            cluster_types=_cluster_types(definition.get("clusterTypes") or []),
            audiences=frozenset(definition.get("audiences") or [PUBLIC]),
            groups=frozenset(groups),
            anonymous=bool(definition.get("anonymous", False)),
        )
    return roles


def all_groups(roles: dict[str, Role]) -> frozenset[str]:
    """Every group that grants some role. These are the only ones worth looking up."""
    return frozenset().union(*(role.groups for role in roles.values())) if roles else frozenset()


def resolve(
    roles: dict[str, Role],
    *,
    username: str | None = None,
    groups: frozenset[str] = frozenset(),
    granted: tuple[str, ...] = (),
    via: str = "anonymous",
) -> Principal:
    """Work out a caller's access from their groups, plus any roles granted directly."""
    held = [
        role
        for role in roles.values()
        if role.anonymous or role.name in granted or (role.groups & groups)
    ]
    return Principal(
        username=username,
        roles=tuple(sorted(role.name for role in held)),
        cluster_types=frozenset().union(*(role.cluster_types for role in held)) if held else frozenset(),
        audiences=frozenset().union(*(role.audiences for role in held)) if held else frozenset(),
        via=via,
        groups=groups,
    )
