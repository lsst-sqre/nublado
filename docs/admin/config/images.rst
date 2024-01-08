###################
Image configuration
###################

The Nublado controller image configuration serves two purposes.
It controls what images are listed and highlighted on the lab spawn form presented by JupyterHub.
It also controls which images are prepulled to all Kubernetes nodes in the cluster to speed up lab start time.

Nublado currently only supports a single image repository.
The tags in that repository must follow the rules in :sqr:`059`.

Currently, Nublado depends on the features of the sciplat-lab_ Docker image and probably will only work on images derived from that image.

.. _config-images-source:

Image source
============

The image source is configured via ``controller.config.images.source``.
Nublado supports two possible sources of images: a Docker registry, or Google Artifact Registry.
Each source takes different parameters.

``controller.config.images.source.type``
    Set to either ``docker`` or ``google`` to choose the type of source.

Using Google Artifact Repository as the image source is highly recommended if Nublado is running in a GKE cluster.

Docker registries
-----------------

For a Docker registry image source type, also set the following parameters:

``controller.config.images.source.registry``
    Host name and optional port of the Docker registry from which to fetch images.
    For Docker Hub, use ``docker.io``.

``controller.config.images.source.repository``
    The repository within that Docker registry to use as an image source.
    For example, ``lsstsqre/sciplat-lab``.

Here is an example configuration fragment with a complete source specification:

.. code-block:: yaml

   controller:
     config:
       images:
         source:
           type: "docker"
           registry: "docker.io"
           repository: "lsstsqre/sciplat-lab"

.. _config-images-gar:

Google Artifact Registry
------------------------

If using Google Artifact Registry as the image source, also set the following settings:

``controller.config.images.source.location``
    The region of the Google Artifact Registry instance.
    For example, ``us-central```.

``controller.config.images.source.projectId``
    The Google Cloud Platform project ID of the Google Artifact Registry instance.

``controller.config.images.source.repository``
    The name of the Google Artifact Repository instance.
    GAR uses slightly incompatible terminology that doesn't map one-to-one to the Docker terminology.
    The repository is the name of a collection of images, similar to the part before the slash in the Docker repository name.
    For example, ``sciplat``.

``controller.config.images.source.image``
    The name of the image within that Google Artifact Repository instance.
    For example, ``sciplat-lab``.

The Nublado controller uses `workload identity`_ to authenticate to Google Artifact Repository to list available images.
When using GAR, you must configure a Google service account with read access to this GAR instance and bind it to the Kubernetes service account ``nublado-controller`` in the ``nublado`` namespace.
Then, set the following additional configuration setting:

``controller.googleServiceAccount``
    The name of the Google service account with read access to this GAR instance.

For step-by-step instructions on how to set up Google Artifact Registry for Nublado, see :doc:`/admin/setup-gar`.
For additional information about why Google Artifact Registry is preferred, see :doc:`/admin/gar`.

.. _config-prepull:

Image prepulling and menu
=========================

Because Rubin Science Platform images are large, the Nublado controller prepulls a selection of images to each cluster node.
Those images are shown as radio button options at the top of the user HTML form for selecting what images to spawn to encourage their use.
All other available images are collected into a drop-down list with a caution that choosing from the drop-down list may result in slow lab start times.

See :sqr:`059` for the definition of release, weekly, and daily images.

What images to prepull and display as radio button selections are controlled by the following settings.

``controller.config.images.recommendedTag``
    The Docker image tag that marks the recommended image.
    This will be listed as the first entry in the radio button list on the user HTML form and will be selected by default.
    The default value is ``recommended``.

    Due to a deficiency in the Docker registry API, if you are using a Docker registry image source and the recommended image is not one of the releases, weeklies, or dailies that are prepulled as defined below, you should pin the underlying image tag as well.
    This ensures that the Nublado controller knows the version tag underlying the recommended image and can create a good human-readable name for the image.
    Do this with the ``controller.config.images.pin`` setting described below.

``controller.config.images.numReleases``
    How many release images to prepull (sorted by recency).
    The default is 1.

``controller.config.images.numWeeklies``
    How many weekly images to prepull (sorted by recency).
    The default is 2.

``controller.config.images.numDailies``
    How many daily images to prepull (sorted by recency).
    The default is 3.

``controller.config.images.pin``
    Additional images to prepull.
    This is a list that can contain any image tag.
    Those images will be prepulled and added to the user HTML form after the release, weekly, and daily images.

    As discussed above, when using the Docker image source, you should normally pin the version tag underlying the recommended image to ensure that the Nublado controller can determine its version and generate a good human-readable description.

``controller.config.images.aliasTags``
    Tags that alias other images.
    This setting doesn't affect prepulling.
    It provides additional information to the Nublado controller about which tags are moving aliases for other tags (such as additional situation-specific recommended tags).
    That information enables better formatting of the human-readable description of those tags.

The prepuller is also affected by the ``config.lab.nodeSelector`` and ``config.lab.tolerations`` settings documented in :ref:`the lab configuration <config-lab-kubernetes>`.
Images are only prepulled to nodes that are selected and tolerated by those settings, if present.

Image cycles
============

Some Rubin Science Platform environments have an XML cycle associated with each release of the user lab image.
The environment only supports one XML cycle version at a time.
Running an image that uses a different XML cycle image is unsafe and must be blocked.

In such environments, set the following configuration setting:

``controller.config.images.cycle``
    Restrict images to only those images with this XML cycle.
    This is applied as a filter to all images, including releases, weeklies, and dailies.
    The image matching ``controller.config.images.recommendedTag`` is not filtered, so make sure that it points to an image with the appropriate cycle.
    Usually the best way to do this is to have a new recommended tag for each cycle version, and update the recommended tag at the same time as the cycle number.
