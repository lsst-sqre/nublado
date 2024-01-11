##########################
Stop all running user labs
##########################

There are some situations where you may wish to stop all running user labs and prevent any users from spawning labs.
Examples include major Nublado upgrades, ensuring no labs are still running ancient lab images, or Kubernetes cluster maintenance.

.. warning::

   Currently there is no graceful way of doing this.
   You will have to forcibly stop the running labs, which runs the risk of losing user data.
   Jupyter labs do autosave periodically, but any changes since the last autosave interval may be lost.
   This action should therefore be advertised in advance.

When you are ready to stop all user labs, take the following actions:

#. Delete the ``hub`` deployment under the ``nublado`` application in Argo CD.
   This will ensure that no one can start a new lab.

#. Delete all Kubernetes namespaces starting with ``nublado-``.
   Be sure to include the ``-`` so that you do not delete the ``nublado`` namespace that contains JupyterHub and the Nublado controller.

This will forcibly terminate all of the user labs.

Once you are ready to allow users to start labs again, sync the ``nublado`` application in Argo CD.
This will recreate the ``hub`` deployment and start JupyterHub again.

This process will leave records behind of supposedly-running labs in the JupyterHub database.
JupyterHub should test all of those labs on startup and discover that they are no longer running and clean up automatically.
However, if you wish, you can manually delete them.
See :doc:`delete-user-session` for how to delete individual entries, and :doc:`wipe-database` for how to wipe the full JupyterHub database (generally only appropriate before a major upgrade).
