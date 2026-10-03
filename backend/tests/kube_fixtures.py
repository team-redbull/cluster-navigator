"""A fake cluster API: a dict of path -> object, served through httpx."""

import httpx

from navigator.collector.kube import KubeClient


def node(name: str, ip: str, *, roles=("worker",), cpu="16", memory="65536000Ki", ready=True) -> dict:
    return {
        "metadata": {"name": name, "labels": {f"node-role.kubernetes.io/{r}": "" for r in roles}},
        "status": {
            # Deliberately Hostname first: address order must not matter.
            "addresses": [{"type": "Hostname", "address": name}, {"type": "InternalIP", "address": ip}],
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
            "nodeInfo": {"kubeletVersion": "v1.29.10", "osImage": "Red Hat Enterprise Linux CoreOS 416"},
            "capacity": {"cpu": cpu, "memory": memory, "ephemeral-storage": "125Gi", "pods": "250"},
            "allocatable": {"pods": "250"},
        },
    }


def standalone(name: str = "ocp4-prod-core-site1", domain: str = "example.com") -> dict[str, dict]:
    return {
        "/apis/config.openshift.io/v1/clusterversions/version": {
            "spec": {"clusterID": "11111111-2222-3333-4444-555555555555"},
            "status": {
                "desired": {"version": "4.17.1"},
                "history": [
                    {"state": "Partial", "version": "4.17.1"},
                    {"state": "Completed", "version": "4.16.21"},
                ],
            },
        },
        "/apis/config.openshift.io/v1/infrastructures/cluster": {
            "status": {
                "controlPlaneTopology": "HighlyAvailable",
                "apiServerURL": f"https://api.{name}.{domain}:6443",
                "platformStatus": {"type": "None"},
            }
        },
        "/apis/config.openshift.io/v1/dnses/cluster": {"spec": {"baseDomain": f"{name}.{domain}"}},
        "/apis/config.openshift.io/v1/ingresses/cluster": {"spec": {"domain": f"apps.{name}.{domain}"}},
        "/apis/config.openshift.io/v1/consoles/cluster": {
            "status": {"consoleURL": f"https://console-openshift-console.apps.{name}.{domain}"}
        },
        "/apis/config.openshift.io/v1/oauths/cluster": {
            "spec": {"identityProviders": [{"name": "ldap", "type": "LDAP"}, {"name": "htpasswd"}]}
        },
        "/version": {"gitVersion": "v1.29.10+abc"},
        "/api/v1/nodes": {
            "items": [
                node("worker-0", "192.10.5.21"),
                node("master-0", "192.10.5.11", roles=("master", "control-plane")),
            ]
        },
        "/apis/storage.k8s.io/v1/storageclasses": {
            "items": [
                {
                    "metadata": {
                        "name": "ceph-rbd",
                        "annotations": {"storageclass.kubernetes.io/is-default-class": "true"},
                    },
                    "provisioner": "openshift-storage.rbd.csi.ceph.com",
                },
                {"metadata": {"name": "cephfs"}, "provisioner": "openshift-storage.cephfs.csi.ceph.com"},
            ]
        },
    }


def hosted(name: str = "ocp4-prod-tomer-site1-a") -> dict[str, dict]:
    api = standalone(name)
    api["/apis/config.openshift.io/v1/infrastructures/cluster"]["status"]["controlPlaneTopology"] = "External"
    api["/apis/config.openshift.io/v1/oauths/cluster"] = {"spec": {}}
    return api


def mce(name: str = "ocp4-prod-mce-site1-a") -> dict[str, dict]:
    api = standalone(name)
    api["/apis/multicluster.openshift.io/v1/multiclusterengines"] = {
        "items": [{"metadata": {"name": "multiclusterengine"}}]
    }
    api["/apis/hypershift.openshift.io/v1beta1/hostedclusters"] = {
        "items": [
            {
                "metadata": {"name": "ocp4-prod-tomer-site1-a", "namespace": "clusters"},
                "spec": {
                    "platform": {"type": "Agent"},
                    "configuration": {"oauth": {"identityProviders": [{"name": "corp-ldap"}]}},
                },
                "status": {"version": {"history": [{"version": "4.16.18", "state": "Completed"}]}},
            }
        ]
    }
    api["/apis/hypershift.openshift.io/v1beta1/nodepools"] = {
        "items": [
            {"metadata": {"namespace": "clusters"}, "spec": {"clusterName": "ocp4-prod-tomer-site1-a", "replicas": 3}},
            {"metadata": {"namespace": "clusters"}, "spec": {"clusterName": "ocp4-prod-tomer-site1-a", "replicas": 2}},
        ]
    }
    return api


def kube_client(api: dict[str, dict], *, forbidden: tuple[str, ...] = ()) -> KubeClient:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in forbidden:
            return httpx.Response(403, json={"message": "forbidden"})
        if path in api:
            return httpx.Response(200, json=api[path])
        return httpx.Response(404, json={"message": "not found"})

    return KubeClient(httpx.Client(transport=httpx.MockTransport(handler), base_url="https://kube"))
