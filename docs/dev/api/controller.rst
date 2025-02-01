###############################
Internal Nublado controller API
###############################

The Nublado controller is built as a Docker image intended for deployment in a Kubernetes cluster using Phalanx_ and is not supported as an installed Python module.
This documentation therefore exists only to assist developers and code analysis and does not define a supported API.

.. automodapi:: controller
   :include-all-objects:

.. automodapi:: controller.background
   :include-all-objects:

.. automodapi:: controller.config
   :include-all-objects:

.. automodapi:: controller.constants
   :include-all-objects:

.. automodapi:: controller.dependencies.config

.. automodapi:: controller.dependencies.context

.. automodapi:: controller.dependencies.user
   :include-all-objects:

.. automodapi:: controller.events
   :include-all-objects:

.. automodapi:: controller.exceptions
   :include-all-objects:

.. automodapi:: controller.factory
   :include-all-objects:

.. automodapi:: controller.main
   :include-all-objects:

.. automodapi:: controller.models.domain.docker
   :include-all-objects:

.. automodapi:: controller.models.domain.fileserver
   :include-all-objects:

.. automodapi:: controller.models.domain.gafaelfawr
   :include-all-objects:

.. automodapi:: controller.models.domain.image
   :include-all-objects:

.. automodapi:: controller.models.domain.kubernetes
   :include-all-objects:

.. automodapi:: controller.models.domain.lab
   :include-all-objects:

.. automodapi:: controller.models.domain.rspimage
   :include-all-objects:

.. automodapi:: controller.models.domain.rsptag
   :include-all-objects:

.. automodapi:: controller.models.domain.volumes
   :include-all-objects:

.. automodapi:: controller.models.index
   :include-all-objects:

.. automodapi:: controller.models.v1.fileserver
   :include-all-objects:

.. automodapi:: controller.models.v1.lab
   :include-all-objects:

.. automodapi:: controller.models.v1.prepuller
   :include-all-objects:

.. automodapi:: controller.services.builder.fileserver
   :include-all-objects:

.. automodapi:: controller.services.builder.lab
   :include-all-objects:

.. automodapi:: controller.services.builder.prepuller
   :include-all-objects:

.. automodapi:: controller.services.builder.volumes
   :include-all-objects:

.. automodapi:: controller.services.fileserver
   :include-all-objects:

.. automodapi:: controller.services.image
   :include-all-objects:

.. automodapi:: controller.services.lab
   :include-all-objects:

.. automodapi:: controller.services.prepuller
   :include-all-objects:

.. automodapi:: controller.services.source.base
   :include-all-objects:

.. automodapi:: controller.services.source.docker
   :include-all-objects:

.. automodapi:: controller.services.source.gar
   :include-all-objects:

.. automodapi:: controller.storage.docker
   :include-all-objects:

.. automodapi:: controller.storage.gafaelfawr
   :include-all-objects:

.. automodapi:: controller.storage.gar
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.creator
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.custom
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.deleter
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.fileserver
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.ingress
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.lab
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.namespace
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.node
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.pod
   :include-all-objects:

.. automodapi:: controller.storage.kubernetes.watcher
   :include-all-objects:

.. automodapi:: controller.storage.metadata
   :include-all-objects:

.. automodapi:: controller.templates
   :include-all-objects:

.. automodapi:: controller.timeout
   :include-all-objects:

.. automodapi:: controller.units
   :include-all-objects:
