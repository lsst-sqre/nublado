###############################
Set up Google Artifact Registry
###############################

If Nublado is running on Google Kubernetes Engine, using Google Artifact Repository to hold its lab images is strongly recommended.
For more information about the benefits, see :doc:`gar`.

1. Create and populate a registry
=================================

#. Create a registry to hold the Nublado lab images that you will be using in some appropriate Google project.
   This does not have to be the same Google project in which Nublado is running, and the same registry can be shared by multiple GKE clusters.
   However, the registry must be in the same region as any GKE cluster that uses it.
   If you have GKE clusters in multiple regions, you will need multiple populated image registries, one for each region.

#. Push the images that you'll be using to that registry.
   Ensure the tags of the images follow the :sqr:`059` rules.

2. Configure each GKE cluster
=============================

For each GKE cluster that will use that registry, do the following:

#. Ensure workload identity is enabled in the cluster configuration.
   For details on how to do this, see the `Google workload identity documentation <https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity#enable>`__.

#. For each node pool in that cluster that is allowed to run Nublado lab pods, find the Google service account used by that node pool.
   This is shown in the details screen for the node pool under :guilabel:`Security`.

#. Create a Google service account that will be used by the Nublado controller to query the registry.
   Bind that service account to the Kubernetes ``nublado-controller`` service account in the ``nublado`` namespace.
   This is the service account used by the controller.
   For information on how to do this, see the `Google workload identity documentation <https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity#authenticating_to>`__

#. Grant the the Artifact Registry Reader role (or equivalent permissions) for the relevant registry to the node service accounts and the Nublado controller service account.
   You will need to do this in the project where the registry is located, not the project where the GKE cluster is located, if they are different.

#. Enable the ``containerfilesystem.googleapis.com`` API for the project hosting the GKE cluster.
   This enables container image streaming.

#. Turn on container image streaming in the GKE cluster configuration.

3. Configure Nublado to use GAR
===============================

Add the necessary configuration to the Phalanx ``nublado`` application to use GAR as the image source.
See :ref:`config-images-gar` for the relevant configuration settings.
