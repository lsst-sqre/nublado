"""Handlers for the app's root, ``/``."""

from fastapi import APIRouter, Depends
from safir.metadata import Metadata, get_metadata
from safir.slack.webhook import SlackRouteErrorHandler

from ..config import Config
from ..dependencies.config import config_dependency
from ..models.index import Index

internal_router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount at the root of the application URL space."""

external_router = APIRouter(route_class=SlackRouteErrorHandler)
"""Router to mount into the application."""

__all__ = ["external_router", "internal_router"]


@external_router.get(
    "",
    response_model=Index,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_index(
    config: Config = Depends(config_dependency),
) -> Index:
    metadata = get_metadata(
        package_name="controller", application_name=config.name
    )
    return Index(metadata=metadata)


@internal_router.get(
    "/",
    description=(
        "Return metadata about the running application. Can also be used as"
        " a health check. This route is not exposed outside the cluster and"
        " therefore cannot be used by external clients."
    ),
    include_in_schema=False,
    response_model=Metadata,
    response_model_exclude_none=True,
    summary="Application metadata (internal)",
)
async def get_internal_index(
    config: Config = Depends(config_dependency),
) -> Metadata:
    return get_metadata(
        package_name="controller", application_name=config.name
    )
