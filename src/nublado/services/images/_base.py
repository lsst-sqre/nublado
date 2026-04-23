"""Shared API for images managers."""

from abc import ABCMeta, abstractmethod

from ...models.images import ImageFilterPolicy, ImageSource

__all__ = ["ImagesManager"]


class ImagesManager[T: ImageSource](metaclass=ABCMeta):
    """Base class defining the shared API for images managers.

    There are separate implementations of the images manager API for each
    image source. This class provides the common API.
    """

    @abstractmethod
    async def list_tags(self, config: T) -> set[str]:
        """List the available image tags in the repository.

        Parameters
        ----------
        config
            Configuration for the repository.

        Returns
        -------
        set of str
            Set of image tags.
        """

    @abstractmethod
    async def prune_images(
        self, config: T, policy: ImageFilterPolicy, *, dry_run: bool = True
    ) -> list[str]:
        """Prune the images excluded by a filter policy.

        The images that are not accepted by the filter policy will be deleted,
        at least to the extent that is possible in the target image registry.

        Parameters
        ----------
        config
            Configuration for the repository.
        policy
            Image filter policy describing what images to retain.
        dry_run
            If `True`, do not delete the images, only return which images
            would be deleted.

        Returns
        -------
        list of str
            Tags of deleted images, or images that would be deleted if
            ``dry_run`` is `True`, in standard sorted order.
        """
