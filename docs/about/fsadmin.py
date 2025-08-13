"""Source for file server component diagram."""

import os
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.gcp.storage import Filestore
from diagrams.k8s.compute import Pod
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
    "Administrative file server detail",
    show=False,
    filename="fsadmin",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("Administrator")
    posix = Filestore("POSIX files")

    with Cluster("Kubernetes"):
        pv = PV("Storage")

        with Cluster("Administrative file server namespace"):
            pod = Pod("fsadmin")
            pvc = PVC("fsadmin-storage")

    user >> pod >> pvc >> pv
    pod >> posix
