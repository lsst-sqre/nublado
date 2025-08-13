"""Source for architecture component diagram."""

import os
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.gcp.compute import KubernetesEngine
from diagrams.gcp.network import LoadBalancing
from diagrams.gcp.storage import Filestore
from diagrams.k8s.compute import ReplicaSet
from diagrams.k8s.podconfig import Secret
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
    "Nublado architecture",
    show=False,
    filename="architecture",
    outformat="png",
    graph_attr=graph_attr,
    node_attr=node_attr,
):
    user = User("User")
    posix = Filestore("POSIX files")

    with Cluster("Kubernetes"):
        gafaelfawr = KubernetesEngine("Gafaelfawr")

        with Cluster("JupyterHub"):
            ingress = LoadBalancing("Ingress")
            jupyterproxy = KubernetesEngine("Proxy")
            jupyterhub = KubernetesEngine("Hub")
            jupyterhub_token = Secret("JupyterHub token")

        with Cluster("Controller"):
            controller = KubernetesEngine("Web service")
            image_puller = ReplicaSet("Image prepuller")
            lab_secrets = Secret("Lab secrets")

        with Cluster("User lab"):
            user_lab = KubernetesEngine("")

        with Cluster("User file server"):
            fileserver_ingress = LoadBalancing("Ingress")
            user_fileserver = KubernetesEngine("Pod")

        with Cluster("Administrative file server"):
            admin_fileserver = KubernetesEngine("Pod")

    user >> ingress >> jupyterproxy >> jupyterhub
    jupyterproxy >> user_lab >> posix
    ingress >> gafaelfawr
    jupyterhub << jupyterhub_token
    jupyterhub >> controller << lab_secrets
    gafaelfawr << controller
    controller >> image_puller
    controller >> Edge(style="dashed") >> user_lab
    controller >> Edge(style="dashed") >> [fileserver_ingress, user_fileserver]
    controller >> Edge(stule="dashed") >> admin_fileserver
    admin_fileserver >> posix
    user >> fileserver_ingress >> user_fileserver >> posix
    fileserver_ingress >> gafaelfawr
