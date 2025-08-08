#######################
The fsadmin environment
#######################

It is occasionally necessary for administrators to be able to look at user filesystems from a root perspective.
Sometimes this is because a user's files are owned by the wrong UID and the user cannot write, but most often it is used to investigate whether the user really has used up all of their space and offer suggestions for what could be deleted.
It is also handy when malfeasance is suspected.

Since manually creating a namespace, running up a privileged container with the right filesystems mounted, installing necessary tools, and so forth is a cumbersome process, nublado provides a route (at ``/nublado/fsadmin/v1/service``) that creates the container.
That route also allows checking the status of the fsadmin environment, and deleting the fsadmin namespace and pod.

The fsadmin namespace and pod behave a lot like a user fileserver.
However, fsadmin is much more dangerous, since the user is root within the pod and with respect to all the mounted filesystems.

There is no Web-accessible interface to the container: the user still has to use ``kubectl exec -n fsadmin fsadmin -- /bin/bash -l`` (assuming the default configuration settings) in order to get a shell.
This is by design.
We restrict the ingress routes to create or delete the container to users with an admin token, and additionally requiring ``kubectl`` privileges is another way to help secure this extremely potent interface.

fsadmin lifecycle API
=====================

The interface is extremely simple:

#. ``POST`` to ``/nublado/fsadmin/v1/service`` will create the namespace and pod (and any necessary PVCs) if they do not exist.
   If they do already exist, ``POST`` is ineffective; notably, it does not delete and recreate an existing fsadmin instance.
   The ``POST`` body is not used.
   We recommend an empty JSON body, ``{}``, as the ``POST`` contents.
   ``POST`` returns an HTTP 204 code if it succeeds, or 5xx if some error occurs.

#. ``DELETE`` to ``/nublado/fsadmin/v1/service`` will remove the namespace and pod if they exist.
   If they do not exist, ``DELETE`` silently succeeds; deleting a nonexistent fsadmin instance is allowed.
   ``DELETE`` returns an HTTP 204 code if it succeeds, or 5xx if some error occurs.

#. ``GET`` to ``/nublado/fsadmin/v1/service`` provides fsadmin status.
   If the namespace and pod both exist, and the pod is in ``Running`` state, ``GET`` returns an HTTP 200 code.
   Otherwise ``GET`` returns 404, or 5xx if some other error occurs.

