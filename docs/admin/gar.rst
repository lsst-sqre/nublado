##############################
Google Artifact Registry (GAR)
##############################

When Nublado is deployed on Google Kubernetes Engine, using Google Artifact Registry (GAR) as the image registry for lab images is strongly recommended.
GAR has three significant advantages over the Docker Hub API:

#. GAR supports container streaming to Google Kubernetes Engine clusters, which significantly speeds up spawning of uncached images.
   See :ref:`gar-streaming` for more details.

#. GAR allows Nublado to retrieve the underlying hashes for every available image tag in a single API call.
   Docker Hub requires a ``HEAD`` request for every image to get the image hash
   Nublado therefore avoids obtaining the image hash except for images that it knows it will need to prepull.
   Therefore, when using the Docker Hub API, Nublado may be unable to discover when multiple tags correspond to the same image, and therefore will not be able to display as rich of a description of the image.

#. Docker Hub APIs may require authentication, which in turn requires configuring a pull secret for every lab.
   While Nublado supports this, it's additional configuration to track and manage and requires managing an external secret.
   GAR can be configured so that the GKE cluster can pull images without further authentication, and the Nublado controller can use workload identity to authenticate to the GAR API, avoiding the need for an authentication secret.

For step-by-step instructions on how to set up GAR for Nublado and configure Nublado to use GAR, see :doc:`setup-gar`.
For details on the GAR-related configuration options in Nublado, see :ref:`config-images-gar`.

.. _gar-streaming:

Container image streaming
=========================

Nublado prepulls a select set of images to every eligible node to speed up image spawning.
The configuration settings for that are documented at :ref:`config-prepull`.

When the images are pulled from the Docker Hub API, the entire image needs to be downloaded to the node before a lab using that image can be spawned.
The `sciplat-lab <https://github.com/lsst-sqre/sciplat-lab>`__ images typically used by the Rubin Science Platform are 4GB, so this can take about four minutes.

Container image streaming allows the lab to be spawned before the image is fully downloaded and also improves the image download speed, which in the case of sciplat-lab images at the IDF reduced image pull time to 30 seconds.

Enabling image streaming for GAR image repositories is therefore highly recommended.
This is done by enabling the ``containerfilesystem.googleapis.com`` API and then enabling image streaming for the cluster.

For more details, see the `Google documentation for container image streaming <https://docs.cloud.google.com/kubernetes-engine/docs/how-to/image-streaming>`__.
