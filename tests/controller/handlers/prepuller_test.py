"""Tests for the prepuller handlers."""

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from ...support.config import configure
from ...support.data import NubladoData


@pytest.mark.asyncio
async def test_images(client: AsyncClient, data: NubladoData) -> None:
    r = await client.get("/nublado/spawner/v1/images")
    assert r.status_code == 200
    data.assert_json_matches(r.json(), "controller/images/standard")


@pytest.mark.asyncio
async def test_prepulls(client: AsyncClient, data: NubladoData) -> None:
    r = await client.get("/nublado/spawner/v1/prepulls")
    assert r.status_code == 200
    data.assert_json_matches(r.json(), "controller/prepuller/prepulls")


@pytest.mark.asyncio
async def test_node_selector(
    client: AsyncClient, data: NubladoData, mock_kubernetes: MockKubernetesApi
) -> None:
    nodes = data.read_nodes("controller/nodes/prepuller")
    mock_kubernetes.set_nodes_for_test(nodes)

    # Some previous versions had problems blocking on shutting down and
    # restarting background services.
    async with asyncio.timeout(1):
        await configure(data, "prepuller", mock_kubernetes)

    # Get the prepuller status. We should only see the nodes that match the
    # node selector of our configuration.
    r = await client.get("/nublado/spawner/v1/prepulls")
    assert r.status_code == 200
    data.assert_json_matches(r.json(), "controller/prepuller/status")
