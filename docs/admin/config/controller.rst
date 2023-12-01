################################
General controller configuration
################################

Controller image
================

None of these settings need to be changed if you are using the current release of the Nublado controller.
They are primarily used when testing new Nublado releases.

``controller.image.repository``
    Docker image repository to use.
    The default is the GitHub Artifact Repository releases maintained by Rubin Observatory.

``controller.image.pullPolicy``
    Pull policy for the controller image.
    The default is ``IfNotPresent``.
    Change to ``Always`` if you are iterating on new controller versions with the same tag, such as a Jira ticket branch.

``controller.image.tag``
    Tag of the controller to deploy.
    By default, this is the current release of Nublado as defined in :file:`Chart.yaml` in the Nublado application chart.

Kubernetes
==========

``controller.resources``
    Resource limits and requests for the Nublado controller pod.
    The defaults are chosen based on observed metrics from the Nublado controller running on Google Kubernetes Engine with a light user load.

None of the following are set by default.
They can be used to add additional Kubernetes configuration to the controller pod if, for example, you want it to run on specific nodes or tag it with annotations that have some external meaning for your environment.

``controller.affinity``
    Affinity rules for the Nublado controller pod.

``controller.ingress.annotations``
    Additional annotations to add to the Kubernetes ``Ingress`` for the Nublado controller pod.

``controller.nodeSelector``
    Node selector rules for the Nubaldo controller pod.

``controller.podAnnotations``
    Additional annotations to add to the Nublado controller pod.

``controller.tolerations``
    Toleration rules for the Nublado controller pod.

Logging and notifications
=========================

``controller.config.logLevel``
    Log level for the Nublado controller.
    The default log level is ``INFO``.
    Choose from one of the `Python logging levels <https://docs.python.org/3/library/logging.html#logging-levels>`__.

``controller.slackAlerts``
    Change this setting to true if you want Nublado to report errors to a Slack channel via a Slack incoming webhook.
    If set to true (the default is false), you will need to provide the URL of a suitable Slack incoming webhook as a Nublado secret using the normal Phalanx secrets system.

Path prefix
===========

``controller.config.pathPrefix``
    The path prefix to use for the controller API.
    The default is ``/nublado``.
    You probably do not want to change this unless you are trying to run multiple instances of Nublado in the same Phalanx environment for some reason.
