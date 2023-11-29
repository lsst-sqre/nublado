"""Source for lab component diagram."""

import os
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.gcp.compute import KubernetesEngine
from diagrams.gcp.network import LoadBalancing
from diagrams.gcp.storage import Filestore
from diagrams.k8s.clusterconfig import Quota
from diagrams.k8s.compute import Pod
from diagrams.k8s.network import NetworkPolicy, Service
from diagrams.k8s.podconfig import ConfigMap, Secret
from diagrams.k8s.storage import PV, PVC
from diagrams.onprem.client import User

os.chdir(Path(__file__).parent)

graph_attr = {
    "label": "",
    "labelloc": "bbc",
    "nodesep": "0.2",
    "pad": "0.2",
    "ranksep": "0.75",
    "splines": "splines",
}

node_attr = {
    "fontsize": "12.0",
}

with Diagram(
    "Lab detail",
    show=False,
    filename="lab",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("User")
    posix = Filestore("POSIX files")

    with Cluster("Kubernetes"):
        ingress = LoadBalancing("Ingress")
        proxy = KubernetesEngine("JupyterHub proxy")
        pv = PV("Storage")

        with Cluster("nublado-<user> namespace"):
            quota = Quota("<user>-nb")
            pod = Pod("<user>-nb")
            configmap_env = ConfigMap("<user>-nb-env")
            configmap_files = ConfigMap("<user>-nb-files")
            configmap_nss = ConfigMap("<user>-nb-nss")
            pvc = PVC("<user>-nb-storage")
            secrets = Secret("<user>-nb")
            service = Service("<user>-nb")
            netpol = NetworkPolicy("nb-<user>name")

    user >> ingress >> proxy >> service >> pod >> pvc >> pv
    pod >> posix
    [configmap_env, configmap_files, configmap_nss, secrets] - pod

    # Formatting hack.
    [netpol, quota] >> Edge(style="invis") >> pvc
