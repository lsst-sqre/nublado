#######################
Configuration reference
#######################

Nublado is configured via the Helm chart for the ``nublado`` Phalanx application.
As with any other Phalanx application, configuration goes into :file:`values-{environment}.yaml` for a given Phalanx environment.
For more information, see the Phalanx documentation on `writing a Helm chart <https://phalanx.lsst.io/developers/write-a-helm-chart.html>`__.

Most of the configuration options are for the Nublado controller.
Only a few parameters for the other Nublado components normally need to be changed.

Because Nublado uses `Zero to JupyterHub`_ to do a lot of the work of installing JupyterHub and its supporting resources, the :file:`values.yaml` file contains a lot of settings for Zero to JupyterHub that should not need to be changed.
Those settings are not mentioned here.
Only the settings that may need to be overridden in :file:`values-{environment}.yaml` are documented.

All configuration parameters are documented using keys separated by dots (for example, ``controller.config.lab.pullSecret``).
This corresponds to YAML structure such as:

.. code-block:: yaml

   controller:
     config:
       lab:
         pullSecret: "pull-secret"

When writing your :file:`values-{environment}.yaml` file, merge common sections together.
For example, if you have multiple settings you are changing under ``controller.config``, there should be only one ``config:`` key and the settings should be combined beneath it.

.. toctree::

   controller
   images
   lab
   fileserver
   hub
