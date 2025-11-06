"""Helper functions for Python asyncio."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Literal

__all__ = ["aclosing_iter"]


class aclosing_iter[T: AsyncIterator](AbstractAsyncContextManager):  # noqa: N801
    """Automatically close async iterators that are generators.

    Python supports two ways of writing an async iterator: a true async
    iterator, and an async generator. Generators support additional async
    context, such as yielding from inside an async context manager, and
    therefore require cleanup by calling their `aclose` method once the
    generator is no longer needed. This step is done automatically by the
    async loop implementation when the generator is garbage-collected, but
    this may happen at an arbitrary point and produces pytest warnings saying
    that the `aclose` method on the generator was never called.

    This class provides a variant of `contextlib.aclosing` that can be used to
    close generators masquerading as iterators. Some Python libraries
    implement `__aiter__` by returning a generator rather than an iterator,
    which is equivalent except for this cleanup behavior. Async iterators do
    not require this explicit cleanup step because they don't support async
    context managers inside the iteration. Since the library is free to change
    from a generator to an iterator at any time, and async iterators don't
    require this cleanup and don't have `aclose` methods, the `aclose` method
    should be called only if it exists.
    """

    def __init__(self, thing: T) -> None:
        self.thing = thing

    async def __aenter__(self) -> T:
        return self.thing

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        # Only call aclose if the method is defined, which we take to mean that
        # this iterator is actually a generator.
        if getattr(self.thing, "aclose", None):
            await self.thing.aclose()  # type: ignore[attr-defined]
        return False
