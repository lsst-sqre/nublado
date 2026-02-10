"""Data types for interacting with Kubernetes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Annotated, Any, Protocol, Self, override

from kubernetes_asyncio.client import (
    V1Affinity,
    V1ContainerImage,
    V1LabelSelector,
    V1LabelSelectorRequirement,
    V1NodeAffinity,
    V1NodeSelector,
    V1NodeSelectorRequirement,
    V1NodeSelectorTerm,
    V1ObjectMeta,
    V1Pod,
    V1PodAffinity,
    V1PodAffinityTerm,
    V1PodAntiAffinity,
    V1PreferredSchedulingTerm,
    V1Toleration,
    V1WeightedPodAffinityTerm,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from .docker import DockerReference

__all__ = [
    "Affinity",
    "KubernetesModel",
    "KubernetesNodeImage",
    "LabelSelector",
    "LabelSelectorOperator",
    "LabelSelectorRequirement",
    "NodeAffinity",
    "NodeSelector",
    "NodeSelectorOperator",
    "NodeSelectorRequirement",
    "NodeSelectorTerm",
    "NodeToleration",
    "PodAffinity",
    "PodAffinityTerm",
    "PodChange",
    "PodPhase",
    "PreferredSchedulingTerm",
    "PropagationPolicy",
    "PullPolicy",
    "TaintEffect",
    "Toleration",
    "TolerationOperator",
    "VolumeAccessMode",
    "WatchEventType",
    "WeightedPodAffinityTerm",
]


class KubernetesModel(Protocol):
    """Protocol for Kubernetes object models.

    kubernetes-asyncio_ doesn't currently expose type information, so this
    tells mypy that all the object models we deal with will have a metadata
    attribute.
    """

    metadata: V1ObjectMeta

    def to_dict(self, *, serialize: bool = False) -> dict[str, Any]: ...


@dataclass
class KubernetesNodeImage:
    """A cached image on a Kubernetes node.

    A cached image has one or more Docker references associated with it,
    reflecting the references by which it was retrieved.

    The references will generally be in one of two formats:

    - :samp:`{registry}/{repository}@{digest}`
    - :samp:`{registry}/{repository}:{tag}`

    Most entries will have both, but if the image was pulled by digest it's
    possible only the first will be present.
    """

    references: list[str]
    """The Docker references for the image."""

    size: int
    """Size of the image in bytes."""

    @classmethod
    def from_container_image(cls, image: V1ContainerImage) -> Self:
        """Create from a Kubernetes API object.

        Parameters
        ----------
        image
            Kubernetes API object.

        Returns
        -------
        KubernetesNodeImage
            The corresponding object.
        """
        return cls(references=image.names, size=image.size_bytes)

    @property
    def digest(self) -> str | None:
        """Determine the image digest, if possible.

        Returns
        -------
        str or None
            The digest for the image if found, or `None` if not.
        """
        for reference in self.references:
            try:
                parsed_reference = DockerReference.from_str(reference)
            except ValueError:
                continue
            if parsed_reference.digest is not None:
                return parsed_reference.digest
        return None


class NodeSelectorOperator(Enum):
    """Match operations for node selectors."""

    IN = "In"
    NOT_IN = "NotIn"
    EXISTS = "Exists"
    DOES_NOT_EXIST = "DoesNotExist"
    GT = "Gt"
    LT = "Lt"


class NodeSelectorRequirement(BaseModel):
    """Individual match rule for nodes."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    key: Annotated[str, Field(title="Key", description="Label key to match")]

    operator: Annotated[
        NodeSelectorOperator,
        Field(title="Operator", description="Match operation to use"),
    ]

    values: Annotated[
        list[str],
        Field(
            title="Matching values",
            description=(
                "For ``In`` and ``NotIn``, matches any value in this list. For"
                " ``Gt`` or ``Lt``, must contain a single member interpreted"
                " as an integer. For ``Exists`` or ``DoesNotExist``, must be"
                " empty."
            ),
        ),
    ] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        match self.operator:
            case NodeSelectorOperator.IN | NodeSelectorOperator.NOT_IN:
                if len(self.values) < 1:
                    raise ValueError("In and NotIn require a list of values")
            case NodeSelectorOperator.GT | NodeSelectorOperator.LT:
                if len(self.values) != 1:
                    raise ValueError("Gt and Lt take a single value")

                # Ensure the value converts to an integer.
                int(self.values[0])
            case (
                NodeSelectorOperator.EXISTS
                | NodeSelectorOperator.DOES_NOT_EXIST
            ):
                if self.values:
                    raise ValueError("Exists or DoesNotExist take no values")
        return self

    def to_kubernetes(self) -> V1NodeSelectorRequirement:
        """Convert to the corresponding Kubernetes model."""
        return V1NodeSelectorRequirement(
            key=self.key, operator=self.operator.value, values=self.values
        )


class NodeSelectorTerm(BaseModel):
    """Term to match nodes."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    match_expressions: Annotated[
        list[NodeSelectorRequirement],
        Field(
            title="Rules for node labels",
            description="Matching rules applied to node labels",
        ),
    ] = []

    match_fields: Annotated[
        list[NodeSelectorRequirement],
        Field(
            title="Rules for node fields",
            description="Matching rules applied to node fields",
        ),
    ] = []

    def to_kubernetes(self) -> V1NodeSelectorTerm:
        """Convert to the corresponding Kubernetes model."""
        expressions = [e.to_kubernetes() for e in self.match_expressions]
        fields = [e.to_kubernetes() for e in self.match_fields]
        return V1NodeSelectorTerm(
            match_expressions=expressions or None,
            match_fields=fields or None,
        )


class PreferredSchedulingTerm(BaseModel):
    """Scheduling term with a weight, used to find preferred nodes."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    preference: Annotated[
        NodeSelectorTerm,
        Field(title="Node selector", description="Selector term for a node"),
    ]

    weight: Annotated[
        int,
        Field(
            title="Weight",
            description="Weight to assign to nodes matching this term",
        ),
    ]

    def to_kubernetes(self) -> V1PreferredSchedulingTerm:
        """Convert to the corresponding Kubernetes model."""
        return V1PreferredSchedulingTerm(
            preference=self.preference.to_kubernetes(), weight=self.weight
        )


class NodeSelector(BaseModel):
    """Matching terms for nodes."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    node_selector_terms: Annotated[
        list[NodeSelectorTerm],
        Field(title="Terms", description="Matching terms for nodes"),
    ] = []

    def to_kubernetes(self) -> V1NodeSelector:
        """Convert to the corresponding Kubernetes model."""
        return V1NodeSelector(
            node_selector_terms=[
                t.to_kubernetes() for t in self.node_selector_terms
            ]
        )


class NodeAffinity(BaseModel):
    """Node affinity rules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    preferred: Annotated[
        list[PreferredSchedulingTerm],
        Field(
            title="Scheduling terms",
            description=(
                "Preference rules used for scheduling and ignored afterwards"
            ),
            alias="preferredDuringSchedulingIgnoredDuringExecution",
        ),
    ] = []

    required: Annotated[
        NodeSelector | None,
        Field(
            title="Node selectors",
            description="Required node selection rules",
            alias="requiredDuringSchedulingIgnoredDuringExecution",
        ),
    ] = None

    def to_kubernetes(self) -> V1NodeAffinity:
        """Convert to the corresponding Kubernetes model."""
        preferred = None
        if self.preferred:
            preferred = [t.to_kubernetes() for t in self.preferred]
        required = self.required.to_kubernetes() if self.required else None
        return V1NodeAffinity(
            preferred_during_scheduling_ignored_during_execution=preferred,
            required_during_scheduling_ignored_during_execution=required,
        )


class LabelSelectorOperator(Enum):
    """Match operations for label selectors."""

    IN = "In"
    NOT_IN = "NotIn"
    EXISTS = "Exists"
    DOES_NOT_EXIST = "DoesNotExist"


class LabelSelectorRequirement(BaseModel):
    """Single rule for label matching."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    key: Annotated[str, Field(title="Key", description="Label key to match")]

    operator: Annotated[
        LabelSelectorOperator,
        Field(title="Operator", description="Label match operator"),
    ]

    values: Annotated[
        list[str],
        Field(
            title="Matching values",
            description=(
                "For ``In`` and ``NotIn``, matches any value in this list. For"
                " ``Exists`` or ``DoesNotExist``, must be empty."
            ),
        ),
    ] = []

    @model_validator(mode="after")
    def _validate(self) -> Self:
        match self.operator:
            case LabelSelectorOperator.IN | LabelSelectorOperator.NOT_IN:
                if len(self.values) < 1:
                    raise ValueError("In and NotIn require a list of values")
            case (
                LabelSelectorOperator.EXISTS
                | LabelSelectorOperator.DOES_NOT_EXIST
            ):
                if self.values:
                    raise ValueError("Exists or DoesNotExist take no values")
        return self

    def to_kubernetes(self) -> V1LabelSelectorRequirement:
        """Convert to the corresponding Kubernetes model."""
        return V1LabelSelectorRequirement(
            key=self.key, operator=self.operator.value, values=self.values
        )


class LabelSelector(BaseModel):
    """Rule for matching labels of pods or namespaces.

    All provided expressions must match. (In other words, they are combined
    with and.)
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    match_expressions: Annotated[
        list[LabelSelectorRequirement],
        Field(
            title="Label match expressions",
            description="Rules for matching labels",
        ),
    ] = []

    match_labels: Annotated[
        dict[str, str],
        Field(
            title="Exact label matches",
            description="Label keys and values that must be set",
        ),
    ] = {}

    def to_kubernetes(self) -> V1LabelSelector:
        """Convert to the corresponding Kubernetes model."""
        match_expressions = [e.to_kubernetes() for e in self.match_expressions]
        return V1LabelSelector(
            match_expressions=match_expressions or None,
            match_labels=self.match_labels or None,
        )


class PodAffinityTerm(BaseModel):
    """Pod matching term for pod affinity."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    label_selector: Annotated[
        LabelSelector | None,
        Field(
            title="Pod label match", description="Match rules for pod labels"
        ),
    ] = None

    namespace_selector: Annotated[
        LabelSelector | None,
        Field(
            title="Namespace label match",
            description="Match rules for namespace labels",
        ),
    ] = None

    namespaces: Annotated[
        list[str],
        Field(
            title="Matching namespaces",
            description=(
                "List of namespaces to which this term applies. The term will"
                " apply to the union of this list of namespaces and any"
                " namespaces that match ``namespaceSelector``, if given. If"
                " both are empty, only the pod's namespace is matched."
            ),
        ),
    ] = []

    topology_key: Annotated[
        str,
        Field(
            title="Node topology label",
            description=(
                "Name of the node label that should match between nodes to"
                " consider two pods to be scheduled on adjacent nodes, which"
                " in turn is the definition of an affinity (and the opposite"
                " of an anti-affinity)."
            ),
        ),
    ]

    def to_kubernetes(self) -> V1PodAffinityTerm:
        """Convert to the corresponding Kubernetes model."""
        label_selector = None
        if self.label_selector:
            label_selector = self.label_selector.to_kubernetes()
        namespace_selector = None
        if self.namespace_selector:
            namespace_selector = self.namespace_selector.to_kubernetes()
        return V1PodAffinityTerm(
            label_selector=label_selector,
            namespace_selector=namespace_selector,
            namespaces=self.namespaces or None,
            topology_key=self.topology_key,
        )


class WeightedPodAffinityTerm(BaseModel):
    """Pod matching term for pod affinity with an associated weight."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    pod_affinity_term: Annotated[
        PodAffinityTerm,
        Field(title="Matching term", description="Pod affinity matching term"),
    ]

    weight: Annotated[
        int,
        Field(
            title="Associated weight",
            description="Weight to associate with pods matching this term",
            ge=1,
            le=100,
        ),
    ]

    def to_kubernetes(self) -> V1WeightedPodAffinityTerm:
        """Convert to the corresponding Kubernetes model."""
        return V1WeightedPodAffinityTerm(
            pod_affinity_term=self.pod_affinity_term.to_kubernetes(),
            weight=self.weight,
        )


class PodAffinity(BaseModel):
    """Pod affinity rules."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    preferred: Annotated[
        list[WeightedPodAffinityTerm],
        Field(
            title="Scheduling terms",
            description=(
                "Preference rules used for scheduling and ignored afterwards"
            ),
            alias="preferredDuringSchedulingIgnoredDuringExecution",
        ),
    ] = []

    required: Annotated[
        list[PodAffinityTerm],
        Field(
            title="Node selectors",
            description="Required node selection rules",
            alias="requiredDuringSchedulingIgnoredDuringExecution",
        ),
    ] = []

    def to_kubernetes(self) -> V1PodAffinity:
        """Convert to the corresponding Kubernetes model."""
        preferred = None
        if self.preferred:
            preferred = [t.to_kubernetes() for t in self.preferred]
        required = None
        if self.required:
            required = [t.to_kubernetes() for t in self.required]
        return V1PodAntiAffinity(
            preferred_during_scheduling_ignored_during_execution=preferred,
            required_during_scheduling_ignored_during_execution=required,
        )


class PodAntiAffinity(PodAffinity):
    """Pod anti-affinity rules.

    Notes
    -----
    This model is structurally identical to `PodAffinity`, but it has to
    convert to a different Kubernetes model.
    """

    @override
    def to_kubernetes(self) -> V1PodAntiAffinity:
        """Convert to the corresponding Kubernetes model."""
        preferred = None
        if self.preferred:
            preferred = [t.to_kubernetes() for t in self.preferred]
        required = None
        if self.required:
            required = [t.to_kubernetes() for t in self.required]
        return V1PodAntiAffinity(
            preferred_during_scheduling_ignored_during_execution=preferred,
            required_during_scheduling_ignored_during_execution=required,
        )


class Affinity(BaseModel):
    """Pod affinity rules."""

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    node_affinity: Annotated[
        NodeAffinity | None,
        Field(
            title="Node affinity rules",
        ),
    ] = None

    pod_affinity: Annotated[
        PodAffinity | None, Field(title="Pod affinity rules")
    ] = None

    pod_anti_affinity: Annotated[
        PodAntiAffinity | None, Field(title="Pod anti-affinity rules")
    ] = None

    def to_kubernetes(self) -> V1Affinity:
        """Convert to the corresponding Kubernetes model."""
        node_affinity = None
        if self.node_affinity:
            node_affinity = self.node_affinity.to_kubernetes()
        pod_affinity = None
        if self.pod_affinity:
            pod_affinity = self.pod_affinity.to_kubernetes()
        pod_anti_affinity = None
        if self.pod_anti_affinity:
            pod_anti_affinity = self.pod_anti_affinity.to_kubernetes()
        return V1Affinity(
            node_affinity=node_affinity,
            pod_affinity=pod_affinity,
            pod_anti_affinity=pod_anti_affinity,
        )


class PodPhase(StrEnum):
    """One of the valid phases reported in the status section of a Pod."""

    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    UNKNOWN = "Unknown"


@dataclass
class PodChange:
    """Represents a change (not creation or deletion) of a pod."""

    phase: PodPhase
    """New phase of the pod."""

    pod: V1Pod
    """Full object for the pod that changed."""


class PropagationPolicy(Enum):
    """Possible values for the ``propagationPolicy`` parameter to delete."""

    FOREGROUND = "Foreground"
    BACKGROUND = "Background"
    ORPHAN = "Orphan"


class PullPolicy(Enum):
    """Pull policy for Docker images in Kubernetes."""

    ALWAYS = "Always"
    IF_NOT_PRESENT = "IfNotPresent"
    NEVER = "Never"


@dataclass
class NodeToleration:
    """Whether a single node is tolerated.

    Used to report the results of evaluating any tolerations against any node
    taints.
    """

    eligible: bool
    """Whether the node is tolerated."""

    comment: str | None = None
    """If the node is not tolerated, why not."""


class TaintEffect(Enum):
    """Possible effects of a pod toleration."""

    NO_SCHEDULE = "NoSchedule"
    PREFER_NO_SCHEDULE = "PreferNoSchedule"
    NO_EXECUTE = "NoExecute"


class TolerationOperator(Enum):
    """Possible operators for a toleration."""

    EQUAL = "Equal"
    EXISTS = "Exists"


class Toleration(BaseModel):
    """Represents a single pod toleration rule.

    Toleration rules describe what Kubernetes node taints a pod will tolerate,
    meaning that the pod can still be scheduled on that node even though the
    node is marked as tained.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, extra="forbid", populate_by_name=True
    )

    effect: Annotated[
        TaintEffect | None,
        Field(
            title="Taint effect",
            description=(
                "Taint effect to match. If ``None``, match all taint effects."
            ),
        ),
    ] = None

    key: Annotated[
        str | None,
        Field(
            title="Taint key",
            description=(
                "Taint key to match. If ``None``, ``operator`` must be"
                " ``Exists``, and this combination is used to match all"
                " taints."
            ),
        ),
    ] = None

    operator: Annotated[
        TolerationOperator,
        Field(
            title="Match operator",
            description=(
                "``Exists`` is equivalent to a wildcard for value and matches"
                " all possible taints of a given catgory."
            ),
        ),
    ] = TolerationOperator.EQUAL

    toleration_seconds: Annotated[
        int | None,
        Field(
            title="Duration of toleration",
            description=(
                "Defines the length of time a ``NoExecute`` taint is tolerated"
                " and is ignored for other taint effects. The pod will be"
                " evicted this number of seconds after the taint is added,"
                " rather than immediately (the default with no toleration)."
                " ``None`` says to tolerate the taint forever."
            ),
        ),
    ] = None

    value: Annotated[
        str | None,
        Field(
            title="Taint value",
            description=(
                "Taint value to match. Must be ``None`` if the operator is"
                " ``Exists``."
            ),
        ),
    ] = None

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.operator == TolerationOperator.EXISTS:
            if self.value:
                raise ValueError("Toleration value not supported with Exists")
        else:
            if not self.key:
                raise ValueError("Toleration key must be specified")
            if not self.value:
                raise ValueError("Toleration value must be specified")
        return self

    def to_kubernetes(self) -> V1Toleration:
        """Convert to the corresponding Kubernetes resource."""
        return V1Toleration(
            effect=self.effect.value if self.effect else None,
            key=self.key,
            operator=self.operator.value,
            toleration_seconds=self.toleration_seconds,
            value=self.value,
        )


class VolumeAccessMode(StrEnum):
    """Access mode for a persistent volume.

    The access modes ``ReadWriteOnce`` and ``ReadWriteOncePod`` are valid
    access modes in Kubernetes but are intentionally not listed here because
    they cannot work with user labs or file servers and therefore should be
    rejected by configuration parsing. This should change in the future if
    access modes are used in other contexts where those access modes may make
    sense.
    """

    READ_ONLY_MANY = "ReadOnlyMany"
    READ_WRITE_MANY = "ReadWriteMany"


class WatchEventType(Enum):
    """Possible values of the ``type`` field of Kubernetes watch events."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
