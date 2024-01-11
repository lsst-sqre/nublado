############################
Wipe the JupyterHub database
############################

JupyterHub uses a PostgreSQL database to record session information, user metadata, and other state.
Normally, JupyterHub correctly handles reconciliation and schema upgrades on its own.
However, sometimes it may be worthwhile to give JupyterHub a fresh start, such as during a major upgrade or if there are signs of persistent database inconsistency.

The process for doing this is a bit different than for :doc:`stop-all-labs` or :doc:`delete-user-session` because you need to use the JupyterHub pod to make the database changes.

.. warning::

   Currently there is no graceful way of doing this.
   You will have to forcibly stop the running labs, which runs the risk of losing user data.
   Jupyter labs do autosave periodically, but any changes since the last autosave interval may be lost.
   This action should therefore be advertised in advance.

When you are ready to reset the database, take the following actions:

#. Delete the ``proxy`` ``GafaelfawrIngress`` resource under the ``nublado`` application in Argo CD.
   This will ensure that no one can start a new lab or access any existing lab.
   This is different than the process for stopping all labs since we will need the JupyterHub pod to still be running.

#. Delete all Kubernetes namespaces starting with ``nublado-``.
   Be sure to include the ``-`` so that you do not delete the ``nublado`` namespace that contains JupyterHub and the Nublado controller.
   This will forcibly terminate all of the user labs.

#. Determine the URL for the JupyterHub database.
   This is the value of the ``jupyterhub.hub.db.url`` key in either :file:`values-{environment}.yaml` or, if not set there, :file:`values.yaml` in the Phalanx ``nublado`` configuration for this environment.

#. Connect to the JupyterHub session database.
   This should be done via the ``hub`` pod, since it has the necessary credentials.

   .. prompt:: bash

      pod=$(kubectl get pods -n nublado | grep ^hub- | awk '{print $1}')
      kubectl exec -ti -n nublado "$pod" -- psql <URL>

   Replace ``<URL>`` with the URL determined in the previous step.

#. Double-check that you use a dedicated user only for the JupyterHub session database and that it doesn't own anything else in the database.
   Once you're sure of that, at the PostgreSQL prompt, drop all of the tables owned by the connecting user.

   .. code-block:: sql

      drop owned by current_user

#. Restart the ``hub`` deployment in the ``nublado`` application in Argo CD.
   You should do this shortly after running the previous command, since the running JupyterHub will be very confused by an empty database.
   JupyterHub should populate the database with its current schema on restart.

Once you are ready to allow users to start labs again, sync the ``nublado`` application in Argo CD.
This will recreate the ``proxy`` ingress and start allowing user access again.
