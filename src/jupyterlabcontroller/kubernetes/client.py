"""Configure Kubernetes shared clients.  Stolen from jupyterhub/kubespawner.
"""

import asyncio
from typing import Any, Dict, Set, Tuple

import kubernetes_asyncio.client  # type:ignore
from kubernetes_asyncio.client import api_client

# we assume that app initialization has happened and therefore k8s
# configuration has been loaded.

_client_cache = Dict[Tuple[Any], api_client]
client_tasks: Set[asyncio.Task] = set()


def shared_client(ClientType, *args, **kwargs):
    """Return a shared kubernetes client instance
    based on the provided arguments.

    Cache is one client per running loop per combination of input args.

    Client will be closed when the loop closes.
    """
    kwarg_key = tuple((key, kwargs[key]) for key in sorted(kwargs))
    cache_key = (asyncio.get_running_loop(), ClientType, args, kwarg_key)
    client = _client_cache.get(cache_key, None)

    if client is None:
        Client = getattr(kubernetes_asyncio.client, ClientType)
        client = Client(*args, **kwargs)

        _client_cache[cache_key] = client

        # create a task that will close the client when it is cancelled
        async def _close_client_task():
            try:
                async with client.api_client:
                    while True:
                        await asyncio.sleep(300)
            except asyncio.CancelledError:
                pass
            finally:
                _client_cache.pop(cache_key, None)

        task = asyncio.create_task(_close_client_task())
        client_tasks.add(task)
        task.add_done_callback(client_tasks.discard)

    return client
