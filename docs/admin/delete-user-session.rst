################################
Delete a JupyterHub user session
################################

For each user with a running lab, there are three separate records of the existence of that lab: an entry in the JupyterHub session database, routes for that user in the JupyterHub proxy server, and state for that user in the Nublado controller.
The proxy server routes are maintained by JupyterHub and the Nublado controller state is periodically refreshed from Kubernetes.
In both cases, the data is stored only in memory.
The JupyterHub database entry, however, is persistent.

JupyterHub should maintain that entry by periodically, and on startup, asking the Nublado controller whether the user's lab is still running.
This appears to be working correctly now with the Nublado controller, but prior to its deployment we sometimes saw the JupyterHub entry get out of sync with the state of the lab in Kubernetes.
When this happens, it's possible for JupyterHub to think the user already has a lab and refuse to let them create or delete it.

Should this happen, the solution is to remove the record from the JupyterHub session database by doing the following:

#. Delete the user's lab namespace (:samp:`nublado-{username}`) if it exists, ensuring the user truly does not have a running lab.

#. Determine the URL for the JupyterHub database.
   This is the value of the ``jupyterhub.hub.db.url`` key in either :file:`values-{environment}.yaml` or, if not set there, :file:`values.yaml` in the Phalanx ``nublado`` configuration for this environment.

#. Connect to the JupyterHub session database.
   This should be done via the ``hub`` pod, since it has the necessary credentials.

   .. prompt:: bash

      pod=$(kubectl get pods -n nublado | grep ^hub- | awk '{print $1}')
      kubectl exec -ti -n nublado "$pod" -- psql <URL>

   Replace ``<URL>`` with the URL determined in the previous step.

#. At the PostgreSQL prompt, remove the entry for this user in the ``users`` table:

   .. code-block:: sql

      delete from users where name='<username>'

   Replace ``<username>`` with the user's username.

#. If this still doesn't fix the problem, you may also have to remove the user from the ``spawners`` table.
   To do this, run ``select * from spawners``, find the entry with the appropriate username in it, and delete that row.
