######################
Forcing node selection
######################

You may want to force user labs and fileservers to run on particular nodes.
A particular use case is when you are running on a Kubernetes cluster that supports autoscaling, and you would prefer that:

* User labs be the only workload on a particular set of nodes, so they are easily separated from the rest of the Phalanx machinery.
* These nodes be optimized for resource usage rather than distribution, so scaling is less painful because the pods to be disrupted are gathered rather than widely spread.

Taints and Tolerations
======================

In order to ensure that lab workload is the only workload on given nodes, you would assign those nodes particular taint keys and values, and then arrange for the controller or fileserver configuration to tolerate those taints.
We conventionally use the key ``nublado.lsst.io/permitted`` with a value (which is ignored) of ``true`` and an effect of ``NoExecute``.
The corresponding toleration in the configuration restates the key and effect, and uses the operator ``Exists`` (which is why the value does not matter).
Note that you should repeat this in the configuration for both the controller and the fileserver.

Node Selection
==============

However, this is only half the job.
Having told kubernetes that only user labs and fileservers can execute on tained nodes, we now want to ensure that they go there.

There are two ways to do this.
One is with the ``nodeSelector`` configuration item.
This is the preferred method.
It is much simpler than using ``Affinity`` and, more important, the prepuller understands ``nodeSelector`` and if you use that method, the prepuller will only pull to nodes that can be selected for Lab workloads.

If you use ``Affinity`` the workload will still end up being scheduled onto the right nodes, and those nodes will still have prepulled images, but the prepuller will pull to other nodes as well.

Assuming that you can use a simple ``nodeSelector`` label, which you probably can, do that.
If, for instance, you have a node pool all of whose members are labelled with ``node_pool`` equal to ``user-lab-pool``, then you should have ``nodeSelector: { node_pool: "user-lab-pool" }`` in your fileserver and controller configuration.
