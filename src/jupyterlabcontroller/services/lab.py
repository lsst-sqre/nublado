"""Service to manage user lab environments."""

from __future__ import annotations

from base64 import b64encode
from functools import partial

from safir.slack.webhook import SlackWebhookClient
from structlog.stdlib import BoundLogger

from ..config import LabConfig
from ..exceptions import MissingSecretError
from ..models.domain.docker import DockerReference
from ..models.domain.gafaelfawr import GafaelfawrUser
from ..models.domain.rspimage import RSPImage
from ..models.v1.lab import LabSpecification, LabStatus, UserLabState
from ..storage.kubernetes.lab import LabStorage
from ..storage.metadata import MetadataStorage
from .builder.lab import LabBuilder
from .image import ImageService
from .size import SizeManager
from .state import LabStateManager

__all__ = ["LabManager"]


class LabManager:
    def __init__(
        self,
        *,
        instance_url: str,
        lab_state: LabStateManager,
        lab_builder: LabBuilder,
        size_manager: SizeManager,
        image_service: ImageService,
        metadata_storage: MetadataStorage,
        lab_storage: LabStorage,
        lab_config: LabConfig,
        slack_client: SlackWebhookClient | None = None,
        logger: BoundLogger,
    ) -> None:
        self.instance_url = instance_url
        self._lab_state = lab_state
        self._builder = lab_builder
        self._size_manager = size_manager
        self._image_service = image_service
        self._metadata = metadata_storage
        self._storage = lab_storage
        self._config = lab_config
        self._slack_client = slack_client
        self._logger = logger

    async def create_lab(
        self, user: GafaelfawrUser, lab: LabSpecification
    ) -> None:
        """Schedules creation of user lab objects/resources.

        Parameters
        ----------
        user
            User for whom the lab is being created.
        lab
            Specification for lab to spawn.

        Raises
        ------
        InvalidDockerReferenceError
            Raised if the Docker image reference in the lab specification is
            invalid.
        LabExistsError
            Raised if this user already has a lab.
        """
        selection = lab.options.image_list or lab.options.image_dropdown
        if selection:
            reference = DockerReference.from_str(selection)
            image = await self._image_service.image_for_reference(reference)
        elif lab.options.image_class:
            image_class = lab.options.image_class
            image = self._image_service.image_for_class(image_class)
        elif lab.options.image_tag:
            tag = lab.options.image_tag
            image = await self._image_service.image_for_tag_name(tag)

        # Check to see if the lab already exists. If so, but it is in a failed
        # state, delete it first.
        status = await self._lab_state.get_lab_status(user.username)
        delete_first = status == LabStatus.FAILED

        # Start the spawning process. This also checks for conflicts and
        # raises an exception if the lab already exists and is not in a failed
        # state.
        #
        # A LabManager is per-request, so the management of the background
        # task that does the lab spawning (which outlasts the request that
        # kicks it off) is handed off to LabStateManager here.
        resources = self._size_manager.resources(lab.options.size)
        await self._lab_state.start_lab(
            username=user.username,
            state=UserLabState.from_request(user, lab, resources),
            spawner=partial(
                self._spawn_lab, user, lab, image, delete_first=delete_first
            ),
            start_progress=35,
            end_progress=75,
        )

    async def _spawn_lab(
        self,
        user: GafaelfawrUser,
        lab: LabSpecification,
        image: RSPImage,
        *,
        delete_first: bool,
    ) -> str:
        """Do the work of creating a user's lab.

        This method is responsible for creating the Kubernetes objects and
        telling Kubernetes to start the user's pod. It does not wait for the
        pod to finish starting. It is run within a background task managed by
        `~jupyterlabcontroller.services.state.LabStateManager`, which then
        waits for the lab to start and updates internal state as appropriate.

        Parameters
        ----------
        user
            Identity information for the user spawning the lab.
        lab
            Specification for the lab environment to create.
        image
            Docker image to run as the lab.
        delete_first
            Whether there is an existing lab that needs to be deleted first.

        Returns
        -------
        str
            Cluster-internal URL at which the lab will be listening once it
            has finished starting.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingSecretError
            Raised if a secret does not exist.
        """
        username = user.username

        # Delete an existing failed lab first if needed.
        if delete_first:
            self._logger.info("Deleting existing failed lab")
            await self._lab_state.publish_event(
                username, f"Deleting existing failed lab for {username}", 2
            )
            await self._delete_lab_and_namespace(username, 5, 20)

        # Retrieve the secrets that will be used to construct the lab secret.
        # Generate a set of names first so that we retrieve each secret only
        # once.
        self._logger.info("Retrieving secret data")
        pull_secret = None
        try:
            secret_data = await self._gather_secret_data(user)
            if self._config.pull_secret:
                pull_secret = await self._storage.read_secret(
                    self._config.pull_secret, self._metadata.namespace
                )
        except MissingSecretError as e:
            e.user = username
            raise

        # Build the objects that make up the user's lab.
        objects = self._builder.build_lab(
            user=user,
            lab=lab,
            image=image,
            secrets=secret_data,
            pull_secret=pull_secret,
        )

        # Create the lab objects in Kubernetes.
        self._logger.info("Creating new lab")
        await self._storage.create(objects)
        await self._lab_state.publish_pod_creation(
            username, "Created Kubernetes objects for user lab", 30
        )

        # Return the URL where the lab will be listening after it starts.
        return self._builder.build_internal_url(user.username, lab.env)

    async def delete_lab(self, username: str) -> None:
        """Delete the lab environment for the given user.

        Parameters
        ----------
        username
            Username whose environment should be deleted.

        Raises
        ------
        KubernetesError
            Raised if a Kubernetes error prevented lab deletion.
        UnknownUserError
            Raised if no lab currently exists for this user.
        """
        callback = partial(self._delete_lab_and_namespace, username, 25, 100)
        await self._lab_state.stop_lab(username, callback)

    async def _delete_lab_and_namespace(
        self, username: str, start_progress: int, end_progress: int
    ) -> None:
        """Delete the user's lab and namespace.

        Currently, this just deletes the namespace and lets that delete the
        pod. This results in an ungraceful shutdown, so in the future it will
        be changed to gracefully shut down the pod first and then delete the
        namespace.

        Parameters
        ----------
        username
            Username of lab to delete.
        start_progress
            Initial progress percentage.
        end_progress
            Final progress percentage.
        """
        pod = f"{username}-nb"
        namespace = self._builder.namespace_for_user(username)

        message = "Shutting down Kubernetes pod"
        await self._lab_state.publish_event(username, message, start_progress)
        await self._storage.delete_pod(pod, namespace)

        message = "Deleting user namespace"
        progress = start_progress + int((end_progress - start_progress) / 2)
        await self._lab_state.publish_event(username, message, progress)
        await self._storage.delete_namespace(namespace)
        message = f"Lab for {username} deleted"
        await self._lab_state.publish_event(username, message, end_progress)
        self._logger.info("Lab deleted")

    async def _gather_secret_data(
        self, user: GafaelfawrUser
    ) -> dict[str, str]:
        """Gather the key/value pair secret data used by the lab.

        Read the secrets specified in the lab configuration, extract the keys
        and values requested by the configuration, and assemble a dictionary
        of secrets that the lab should receive.

        Parameters
        ----------
        user
            Authenticated Gafaelfawr user.

        Returns
        -------
        dict of str
            Secret data for the lab.

        Raises
        ------
        KubernetesError
            Raised if there is some failure in a Kubernetes API call.
        MissingSecretError
            Raised if a secret does not exist.
        """
        secret_names = {s.secret_name for s in self._config.secrets}
        secrets = {
            n: await self._storage.read_secret(n, self._metadata.namespace)
            for n in sorted(secret_names)
        }

        # Now, construct the data for the user's lab secret.
        data = {}
        for spec in self._config.secrets:
            key = spec.secret_key
            if key not in secrets[spec.secret_name].data:
                namespace = self._metadata.namespace
                raise MissingSecretError(spec.secret_name, namespace, key)
            if key in data:
                # Conflict with another secret. Should be impossible since the
                # validator on our configuration enforces no conflicts.
                raise RuntimeError(f"Duplicate secret key {key}")
            data[key] = secrets[spec.secret_name].data[key]

        # Add the user's token and return the results.
        data["token"] = b64encode(user.token.encode()).decode()
        return data
