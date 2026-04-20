"""Shared API for images managers."""

from abc import ABCMeta, abstractmethod

from ...models.images import ImageSource

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
            List of image tags.
        """
