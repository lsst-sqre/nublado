"""Tests for the prepuller handlers."""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient
from safir.testing.kubernetes import MockKubernetesApi

from ...support.config import configure
from ...support.data import (
    read_input_node_json,
    read_output_json,
)


@pytest.mark.asyncio
async def test_images(client: AsyncClient) -> None:
    r = await client.get("/nublado/spawner/v1/images")
    assert r.status_code == 200
    assert r.json() == read_output_json("standard", "images")


@pytest.mark.asyncio
async def test_prepulls(client: AsyncClient) -> None:
    r = await client.get("/nublado/spawner/v1/prepulls")
    assert r.status_code == 200
    assert r.json() == read_output_json("standard", "prepulls")


@pytest.mark.asyncio
async def test_node_selector(
    client: AsyncClient, mock_kubernetes: MockKubernetesApi
) -> None:
    nodes = read_input_node_json("prepuller", "nodes")
    mock_kubernetes.set_nodes_for_test(nodes)
    async with asyncio.timeout(1):
        await configure("prepuller", mock_kubernetes)

    # Wait for the the prepuller and then get its status. We should only see
    # the nodes that match the node selector of our configuration.
    r = await client.get("/nublado/spawner/v1/prepulls")
    assert r.status_code == 200
    assert r.json() == read_output_json("prepuller", "status")
