####################
Internal Nublado API
####################

The Nublado controller and the command-line tools are built as a Docker image intended for deployment in a Kubernetes cluster using Phalanx_ and is not supported as an installed Python module.
This documentation therefore exists only to assist developers and code analysis and does not define a supported API.

.. automodapi:: nublado.constants
   :include-all-objects:

.. automodapi:: nublado.controller.background
   :include-all-objects:

.. automodapi:: nublado.controller.config
   :include-all-objects:

.. automodapi:: nublado.controller.constants
   :include-all-objects:

.. automodapi:: nublado.controller.dependencies.config
   :include-all-objects:

.. automodapi:: nublado.controller.dependencies.context
   :include-all-objects:

.. automodapi:: nublado.controller.dependencies.user
   :include-all-objects:

.. automodapi:: nublado.controller.events
   :include-all-objects:

.. automodapi:: nublado.controller.exceptions
   :include-all-objects:

.. automodapi:: nublado.controller.factory
   :include-all-objects:

.. automodapi:: nublado.controller.main
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.docker
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.fileserver
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.fsadmin
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.gafaelfawr
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.image
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.kubernetes
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.lab
   :include-all-objects:

.. automodapi:: nublado.controller.models.domain.volumes
   :include-all-objects:

.. automodapi:: nublado.controller.models.index
   :include-all-objects:

.. automodapi:: nublado.controller.models.v1.fileserver
   :include-all-objects:

.. automodapi:: nublado.controller.models.v1.fsadmin
   :include-all-objects:

.. automodapi:: nublado.controller.models.v1.lab
   :include-all-objects:

.. automodapi:: nublado.controller.models.v1.prepuller
   :include-all-objects:

.. automodapi:: nublado.controller.services.builder.fileserver
   :include-all-objects:

.. automodapi:: nublado.controller.services.builder.fsadmin
   :include-all-objects:

.. automodapi:: nublado.controller.services.builder.lab
   :include-all-objects:

.. automodapi:: nublado.controller.services.builder.prepuller
   :include-all-objects:

.. automodapi:: nublado.controller.services.builder.volumes
   :include-all-objects:

.. automodapi:: nublado.controller.services.fileserver
   :include-all-objects:

.. automodapi:: nublado.controller.services.fsadmin
   :include-all-objects:

.. automodapi:: nublado.controller.services.image
   :include-all-objects:

.. automodapi:: nublado.controller.services.lab
   :include-all-objects:

.. automodapi:: nublado.controller.services.prepuller
   :include-all-objects:

.. automodapi:: nublado.controller.services.source.base
   :include-all-objects:

.. automodapi:: nublado.controller.services.source.docker
   :include-all-objects:

.. automodapi:: nublado.controller.services.source.gar
   :include-all-objects:

.. automodapi:: nublado.controller.storage.docker
   :include-all-objects:

.. automodapi:: nublado.controller.storage.gar
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.creator
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.custom
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.deleter
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.fileserver
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.fsadmin
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.ingress
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.lab
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.namespace
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.node
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.pod
   :include-all-objects:

.. automodapi:: nublado.controller.storage.kubernetes.watcher
   :include-all-objects:

.. automodapi:: nublado.controller.storage.metadata
   :include-all-objects:

.. automodapi:: nublado.controller.templates
   :include-all-objects:

.. automodapi:: nublado.controller.timeout
   :include-all-objects:

.. automodapi:: nublado.controller.units
   :include-all-objects:

.. automodapi:: nublado.controller
   :include-all-objects:

.. automodapi:: nublado.inithome.provisioner
   :include-all-objects:

.. automodapi:: nublado.landingpage.exceptions
   :include-all-objects:

.. automodapi:: nublado.landingpage.provisioner
   :include-all-objects:

.. automodapi:: nublado.models.images
   :include-all-objects:

.. automodapi:: nublado.purger.config
   :include-all-objects:

.. automodapi:: nublado.purger.constants
   :include-all-objects:

.. automodapi:: nublado.purger.exceptions
   :include-all-objects:

.. automodapi:: nublado.purger.models.plan
   :include-all-objects:

.. automodapi:: nublado.purger.models.v1.policy
   :include-all-objects:

.. automodapi:: nublado.purger.purger
   :include-all-objects:

.. automodapi:: nublado.startup.constants
   :include-all-objects:

.. automodapi:: nublado.startup.exceptions
   :include-all-objects:

.. automodapi:: nublado.startup.services.credentials
   :include-all-objects:

.. automodapi:: nublado.startup.services.dask
   :include-all-objects:

.. automodapi:: nublado.startup.services.environment
   :include-all-objects:

.. automodapi:: nublado.startup.services.homedir
   :include-all-objects:

.. automodapi:: nublado.startup.services.preparer
   :include-all-objects:

.. automodapi:: nublado.startup.storage.command
   :include-all-objects:

.. automodapi:: nublado.startup.utils
   :include-all-objects:
