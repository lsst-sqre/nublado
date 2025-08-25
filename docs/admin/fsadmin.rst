##############################################
The file system administration pod environment
##############################################

It is occasionally necessary for administrators to be able to look at
user filesystems with administrative privilege.
Sometimes this is because a user's files are owned by the wrong UID and the user cannot write, but most often it is used to investigate whether the user really has used up all of their space and offer suggestions for what could be deleted.
It is also handy when malfeasance is suspected.

Since manually running up a privileged container with the right filesystems mounted, installing necessary tools, and so forth is a cumbersome process, nublado provides a route (at ``/nublado/fsadmin/v1/service``) that creates the container.
That route also allows checking the status of the fsadmin environment, and deleting the fsadmin namespace and pod.

The fsadmin pod behaves a lot like a user fileserver.
However, fsadmin is much more dangerous, since the user is root within the pod and with respect to all the mounted filesystems.

There is no Web-accessible interface to the container: the user must use ``kubectl exec -n nublado fsadmin -- /bin/bash -l`` (assuming the default configuration settings) in order to get a shell.
This is by design.
We restrict the ingress routes to create, delete, or query the container to users with an admin token.
Requiring ``kubectl`` privileges in addition is another way to help secure this extremely potent interface.

fsadmin lifecycle API
=====================

The interface is extremely simple:

#. ``GET`` to ``/nublado/fsadmin/v1/service`` provides fsadmin status.
   If the administrative pod exists in the same namespace as the controller, and the pod is in ``Running`` state, ``GET`` returns an HTTP 200 code. The HTTP body will be JSON with one field, ``start_time``, whose value will be a textual representation of a UTC ISO 8601 datestamp showing the time the pod went into ``Running`` state.
   Otherwise ``GET`` returns 404 if either of the above conditions are not met.
   It returns 5xx if some other error occurs.

#. ``POST`` to ``/nublado/fsadmin/v1/service`` will create the pod (and any necessary PVCs) in the controller's namespace if they do not exist.
   If they do already exist, ``POST`` is ineffective; notably, it does not delete and recreate an existing fsadmin instance.
   The ``POST`` body must be ``{ "start": true }``.
   ``POST`` returns an HTTP 200 code if it succeeds, or 5xx if some error occurs. The HTTP body on success will be the same as ``GET``, containing the time the pod went into ``Running`` state.

#. ``DELETE`` to ``/nublado/fsadmin/v1/service`` will remove the administrative pod and any associated PVCs from the controller namespace if it they exist.
   If the resources do not exist, ``DELETE`` silently succeeds.
   ``DELETE`` returns an HTTP 204 code if it succeeds, or 5xx if some error occurs.
