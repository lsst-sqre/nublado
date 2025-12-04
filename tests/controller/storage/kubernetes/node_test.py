"""Tests for the Kubernetes node storage layer."""

from __future__ import annotations

import pytest
import structlog
from kubernetes_asyncio.client import ApiClient, V1Node, V1NodeSpec, V1Taint
from safir.testing.kubernetes import MockKubernetesApi

from nublado.controller.models.domain.kubernetes import (
    TaintEffect,
    Toleration,
    TolerationOperator,
)
from nublado.controller.storage.kubernetes.node import NodeStorage


@pytest.mark.asyncio
async def test_is_tolerated(mock_kubernetes: MockKubernetesApi) -> None:
    node = V1Node()
    logger = structlog.get_logger(__name__)
    storage = NodeStorage(ApiClient(), logger)

    assert storage.is_tolerated(node, []).eligible
    node.spec = V1NodeSpec()
    assert storage.is_tolerated(node, []).eligible
    node.spec.taints = []
    assert storage.is_tolerated(node, []).eligible

    # PreferNoSchedule taints are ignored.
    node.spec.taints = [V1Taint(effect="PreferNoSchedule", key="foo")]
    assert storage.is_tolerated(node, []).eligible

    node.spec.taints = [V1Taint(effect="NoSchedule", key="foo")]
    tolerated = storage.is_tolerated(node, [])
    assert not tolerated.eligible
    assert tolerated.comment == "Node is tainted (NoSchedule, foo)"
    assert storage.is_tolerated(
        node, [Toleration(operator=TolerationOperator.EXISTS)]
    ).eligible
    assert storage.is_tolerated(
        node, [Toleration(operator=TolerationOperator.EXISTS, key="foo")]
    ).eligible
    assert not storage.is_tolerated(
        node, [Toleration(operator=TolerationOperator.EXISTS, key="bar")]
    ).eligible
    assert storage.is_tolerated(
        node,
        [
            Toleration(
                effect=TaintEffect.NO_SCHEDULE,
                operator=TolerationOperator.EXISTS,
                key="foo",
            )
        ],
    ).eligible
    assert not storage.is_tolerated(
        node,
        [
            Toleration(
                effect=TaintEffect.NO_EXECUTE,
                operator=TolerationOperator.EXISTS,
                key="foo",
            )
        ],
    ).eligible

    node.spec.taints = [V1Taint(effect="NoSchedule", key="foo", value="bar")]
    assert storage.is_tolerated(
        node, [Toleration(operator=TolerationOperator.EXISTS)]
    ).eligible
    assert storage.is_tolerated(
        node, [Toleration(operator=TolerationOperator.EXISTS, key="foo")]
    ).eligible
    assert storage.is_tolerated(
        node, [Toleration(key="foo", value="bar")]
    ).eligible
    tolerated = storage.is_tolerated(
        node, [Toleration(key="bar", value="bar")]
    )
    assert not tolerated.eligible
    assert tolerated.comment == "Node is tainted (NoSchedule, foo = bar)"
    assert not storage.is_tolerated(
        node, [Toleration(key="foo", value="barbar")]
    ).eligible

    # Tolerations with toleration_seconds set are ignored for NoExecute taints
    # but honored for other types of taints.
    node.spec.taints = [V1Taint(effect="NoExecute", key="foo", value="bar")]
    toleration = Toleration(key="foo", value="bar", toleration_seconds=5)
    assert not storage.is_tolerated(node, [toleration]).eligible
    node.spec.taints = [V1Taint(effect="NoSchedule", key="foo", value="bar")]
    assert storage.is_tolerated(node, [toleration]).eligible

    # For multiple taints, all of the taints have to be tolerated.
    node.spec.taints = [
        V1Taint(effect="NoSchedule", key="foo", value="bar"),
        V1Taint(effect="NoExecute", key="foo", value="other"),
    ]
    tolerated = storage.is_tolerated(
        node, [Toleration(key="foo", value="bar")]
    )
    assert not tolerated.eligible
    assert tolerated.comment == "Node is tainted (NoExecute, foo = other)"
    assert storage.is_tolerated(
        node,
        [
            Toleration(key="foo", value="bar"),
            Toleration(key="foo", value="other"),
        ],
    ).eligible
    assert not storage.is_tolerated(
        node,
        [
            Toleration(key="foo", value="bar"),
            Toleration(key="foo", value="baz"),
        ],
    ).eligible
    assert storage.is_tolerated(
        node, [Toleration(key="foo", operator=TolerationOperator.EXISTS)]
    ).eligible
    assert not storage.is_tolerated(
        node,
        [
            Toleration(
                effect=TaintEffect.NO_SCHEDULE,
                key="foo",
                operator=TolerationOperator.EXISTS,
            )
        ],
    ).eligible
    assert storage.is_tolerated(
        node,
        [
            Toleration(
                effect=TaintEffect.NO_SCHEDULE,
                key="foo",
                operator=TolerationOperator.EXISTS,
            ),
            Toleration(
                effect=TaintEffect.NO_EXECUTE,
                key="foo",
                operator=TolerationOperator.EXISTS,
            ),
        ],
    ).eligible
