"""Source for file server component diagram."""

from diagrams import Cluster, Edge
from diagrams.gcp.storage import Filestore
from diagrams.k8s.compute import Pod
from diagrams.k8s.storage import PV, PVC
from diagrams.onprem.client import User
from documenteer.ext.diagrams import SphinxDiagram

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

with SphinxDiagram(
    title="Administrative file server detail",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("Administrator")
    posix = Filestore("POSIX files")

    with Cluster("Kubernetes"):
        pv = PV("Storage")

        with Cluster("Nublado controller namespace"):
            pod = Pod("fsadmin")
            pvc = PVC("fsadmin-storage")

    user >> pod >> pvc >> pv
    pod >> posix
