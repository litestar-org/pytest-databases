from __future__ import annotations

import hashlib
import inspect
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from functools import partial
from typing import TYPE_CHECKING, Callable, TypeVar, cast, overload

import anyio
from typing_extensions import ParamSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from types import TracebackType

T = TypeVar("T")
P = ParamSpec("P")


class _ContextManagerWrapper:
    def __init__(self, cm: AbstractContextManager[T]) -> None:
        self._cm = cm

    async def __aenter__(self) -> T:
        return self._cm.__enter__()  # type: ignore[return-value]

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return self._cm.__exit__(exc_type, exc_val, exc_tb)


@overload
async def maybe_async(obj: Awaitable[T]) -> T: ...


@overload
async def maybe_async(obj: T) -> T: ...


async def maybe_async(obj: Awaitable[T] | T) -> T:
    return cast(T, await obj) if inspect.isawaitable(obj) else cast(T, obj)


def maybe_async_cm(obj: AbstractContextManager[T] | AbstractAsyncContextManager[T]) -> AbstractAsyncContextManager[T]:
    if isinstance(obj, AbstractContextManager):
        return cast(AbstractAsyncContextManager[T], _ContextManagerWrapper(obj))
    return obj


def wrap_sync(fn: Callable[P, T]) -> Callable[P, Awaitable[T]]:
    if inspect.iscoroutinefunction(fn):
        return fn

    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))

    return wrapped


def simple_string_hash(string_to_hash: str) -> str:
    """Generates a short hash based on a string.

    Args:
      string_to_hash: The string to hash.

    Returns:
      A short hash string.
    """

    string_bytes = string_to_hash.encode("utf-8")
    hasher = hashlib.sha256()
    hasher.update(string_bytes)
    digest = hasher.digest()
    hex_string = digest.hex()
    return hex_string[:12]
