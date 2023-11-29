"""Source for file server component diagram."""

import os
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.gcp.storage import Filestore
from diagrams.k8s.compute import Job, Pod
from diagrams.k8s.network import Ingress, Service
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
    "User file server detail",
    show=False,
    filename="fileserver",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("User")
    posix = Filestore("POSIX files")

    with Cluster("Kubernetes"):
        pv = PV("Storage")

        with Cluster("File server namespace"):
            ingress = Ingress("<user>-fs")
            service = Service("<user>-fs")
            job = Job("<user>-fs")
            pod = Pod("<user>-fs")
            pvc = PVC("<user>-fs-storage")

    user >> ingress >> service >> pod >> pvc >> pv
    pod >> posix
    job >> Edge(style="dashed") >> pod
