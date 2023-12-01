########################
JupyterHub configuration
########################

The JupyterHub service is installed using `Zero to JupyterHub`_ as a sub-chart, so there are a lot of settings in the :file:`values.yaml` file for the ``nublado`` application that should not need to be changed.
Documented here are the settings that may need to be changed for different Phalanx environments.

Settings that start with ``jupyterhub`` are Zero to JupyterHub configuration settings and are passed to the sub-chart.
Settings with other prefixes are Phalanx-specific.

.. _config-hub-db:

Database
========

By default, JupyterHub uses the internal PostgreSQL server deployed by Phalanx to store its session database.
However, use of that database server is not recommended for anything other than testing.
Production deployments should instead provide an infrastructure database and configure JupyterHub to use it.

``hub.internalDatabase``
    Set this to false when using an infrastructure database.
    The default is true, indicating that the Phalanx-internal database service should be used.

``jupyterhub.hub.db.url``
    Set this to the URL of the PostgreSQL database that should be used for the session database.
    The default is to use the Phalanx-internal database service.
    Use the value ``postgresql://nublado@cloud-sql-proxy.nublado/nublado`` when using Cloud SQL (see :ref:`config-hub-cloudsql`).

.. _config-hub-cloudsql:

Cloud SQL
---------

When running a Phalanx environment on Google Kubernetes Engine, using Cloud SQL for the Nublado JupyterHub session database is strongly recommended.

When using Cloud SQL, Nublado always uses workload identity via the Cloud SQL Auth Proxy to gain access to the database.
Configuring Cloud SQL therefore requires creating a Google service account with the ``cloudsql.client`` role and binding it to the Kubernetes service account ``cloud-sql-proxy`` in the ``nublado`` namespace of the Phalanx environment.
Then, set the following configuration settings:

``cloudsql.enabled``
    Set this to true when using Cloud SQL.

``cloudsql.instanceConnectionName``
    Database instance connection name that is hosting the JupyterHub session database.
    This is shown in the GCP console after you have created the Cloud SQL database.

``cloudsql.serviceAccount``
    Name of the Google service account configured as described above.
    This service account must have an IAM binding to the Kubernetes service account ``cloud-sql-proxy`` in the ``nublado`` namespace of the Phalanx environment.
    See `workload identity`_ for more information.

Also set ``jupyterhub.hub.db.url`` to ``postgresql://nublado@cloud-sql-proxy.nublado/nublado`` as described in :ref:`config-hub-db`.
The last portion of that URL (``nublado``) names the Cloud SQL database used for the session database.
Naming that database ``nublado`` is recommended, but it can be named anything you choose as long as the URL is consistent.
Using a separate database solely for the JupyterHub session database is strongly recommended.

See the `Google documentation <https://cloud.google.com/sql/docs/postgres/connect-overview>`__ for more information about Cloud SQL and the Cloud SQL Auth Proxy.

The following additional settings are supported for configuring how the Cloud SQL Auth Proxy pod is deployed in Kubernetes.
You will not normally need to set them.

``cloudsql.affinity``
    Affinity rules for the Cloud SQL Auth Proxy pod.

``cloudsql.nodeSelector``
    Node selector rules for the Cloud SQL Auth Proxy pod.

``cloudsql.podAnnotations``
    Additional annotations to add to the Cloud SQL Auth Proxy pod.

``cloudsql.resources``
    Resource limits and requests for the Cloud SQL Auth Proxy pod.
    The defaults are chosen based on observed metrics from the JupyterHub running on Google Kubernetes Engine with a light user load.

``cloudsql.tolerations``
    Toleration rules for the Cloud SQL Auth Proxy pod.

The following additional settings control what version of the Cloud SQL Auth Proxy is used.
By default, the latest stable relesae is used.
You will not normally need to change any of these settings.

``cloudsql.image.repository``
    Docker repository from which to get the Cloud SQL Auth Proxy image.

``cloudsql.image.pullPolicy``
    Pull policy for the Cloud SQL Auth Proxy image.
    The default is ``IfNotPresent``.

``cloudsql.image.tag``
    Tag of the Cloud SQL Auth Proxy image.

Automatic lab shutdown
======================

JupyterHub supports automatically shutting down labs after either a period of idle time or after a maximum age.
This is controlled by the following settings.

``jupyterhub.cull.enabled``
    Set to false if you want to disable shutting down labs automatically.

``jupyterhub.cull.timeout``
    Idle timeout in seconds.
    If a lab has been idle for longer than this length of time, it will be automatically shut down.
    The default is 2592000 (30 days).

``jupyterhub.cull.maxAge``
    Maximum age of a lab in seconds.
    Any lab that has been running for longer than this period of time will be automatically shut down whether it is active or not.
    The default is 5184000 (60 days).

Path prefix
===========

``jupyterhub.hub.baseUrl``
    The path prefix to use for the user interface to JupyterHub.
    The default is ``/nb``.
    You probably do not want to change this unless you are trying to run multiple instances of Nublado in the same Phalanx environment for some reason.

Image
=====

``jupyterhub.hub.image.name``
    Docker repository for the JupyterHub image to use.
    The default is to use the custom JupyterHub image built by Nublado.

``jupyterhub.hub.image.tag``
    Tag of the JupyterHub image to use.
    You may need to override this setting when testing unreleased images.

    Due to limitations in Helm's handling of sub-charts, this version, unlike the version of other components such as the controller, does not automatically default to the ``appVersion`` of the ``nublado`` chart.
    It therefore must be updated in :file:`values.yaml` whenever a new version of Nublado is released.
    This is normally done as part of the :ref:`release process <regular-release>`.

Timeouts
========

``hub.timeout.startup``
    How long to wait in seconds for the JupyterLab process to start responding to network requests after the lab pod has started.
    Empirically, this sometimes takes longer than 60 seconds for sciplat-lab_ images for reasons that we do not currently understand.
    The default is 90 seconds.

Phalanx internals
=================

``secrets.templateSecrets``
    Set this to true if the Phalanx environment has been converted to the new secrets management system.
    See `the Phalanx documentation <https://phalanx.lsst.io/admin/migrating-secrets.html>`__ for more information.
