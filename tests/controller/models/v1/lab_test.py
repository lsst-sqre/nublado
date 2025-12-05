"""Tests for lab spawning models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nublado.controller.constants import DROPDOWN_SENTINEL_VALUE
from nublado.controller.models.v1.lab import (
    ImageClass,
    LabRequestOptions,
    LabResources,
    LabSize,
    ResourceQuantity,
)


def test_resource_quantity() -> None:
    quantity = ResourceQuantity.model_validate({"cpu": 0.4, "memory": "1Gi"})
    assert quantity.memory == 1024 * 1024 * 1024

    with pytest.raises(ValidationError):
        ResourceQuantity.model_validate({"cpu": 1.0, "memory": "24D"})


def test_lab_request_options() -> None:
    """Test LabRequestOptions.

    This class has complex validation logic so that it can handle raw form
    submissions in the structure used by JupyterHub.
    """
    options = LabRequestOptions.model_validate(
        {
            "image_list": "lighthouse.ceres/library/sketchbook:latest_daily",
            "size": "medium",
        }
    )
    assert options.model_dump(exclude_none=True) == {
        "image_list": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.MEDIUM,
        "enable_debug": False,
        "reset_user_env": False,
    }

    options = LabRequestOptions.model_validate(
        {
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "size": ["small"],
            "enable_debug": ["true"],
        }
    )
    assert options.model_dump(exclude_none=True) == {
        "image_dropdown": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.SMALL,
        "enable_debug": True,
        "reset_user_env": False,
    }

    # If the list is set to the sentinel value, it should be ignored.
    options = LabRequestOptions.model_validate(
        {
            "image_list": [DROPDOWN_SENTINEL_VALUE],
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "size": ["large"],
            "enable_debug": ["false"],
            "reset_user_env": ["true"],
        }
    )
    assert options.model_dump(exclude_none=True) == {
        "image_dropdown": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.LARGE,
        "enable_debug": False,
        "reset_user_env": True,
    }

    # If both list and dropdown are set, list should be used by preference and
    # dropdown ignored.
    options = LabRequestOptions.model_validate(
        {
            "image_list": "lighthouse.ceres/library/sketchbook:w_2077_43",
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "size": LabSize.MEDIUM,
        }
    )
    assert options.model_dump(exclude_none=True) == {
        "image_list": "lighthouse.ceres/library/sketchbook:w_2077_43",
        "size": LabSize.MEDIUM,
        "enable_debug": False,
        "reset_user_env": False,
    }

    # None and [] should be ignored, and DROPDOWN_SENTINEL_VALUE should still
    # be ignored even if it's not in a list.
    options = LabRequestOptions.model_validate(
        {
            "image_list": DROPDOWN_SENTINEL_VALUE,
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "image_class": None,
            "image_tag": [],
            "size": ["large"],
            "enable_debug": ["false"],
            "reset_user_env": "true",
        }
    )
    assert options.model_dump(exclude_none=True) == {
        "image_dropdown": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.LARGE,
        "enable_debug": False,
        "reset_user_env": True,
    }

    # Check image_class and image_tag, and also check title-cased sizes.
    options = LabRequestOptions.model_validate(
        {"image_class": "recommended", "size": "Large", "enable_debug": True}
    )
    assert options.model_dump(exclude_none=True) == {
        "image_class": ImageClass.RECOMMENDED,
        "size": LabSize.LARGE,
        "enable_debug": True,
        "reset_user_env": False,
    }
    options = LabRequestOptions.model_validate(
        {"image_tag": "latest_daily", "size": ["Large"]}
    )
    assert options.model_dump(exclude_none=True) == {
        "image_tag": "latest_daily",
        "size": LabSize.LARGE,
        "enable_debug": False,
        "reset_user_env": False,
    }

    # List of length longer than 1.
    with pytest.raises(ValidationError):
        LabRequestOptions.model_validate(
            {
                "image_list": [
                    "lighthouse.ceres/library/sketchbook:w_2077_43",
                    "lighthouse.ceres/library/sketchbook:latest_daily",
                ],
                "size": "medium",
            }
        )

    # No images to spawn.
    with pytest.raises(ValidationError):
        LabRequestOptions.model_validate({"size": "medium"})

    # Images provided in multiple ways.
    with pytest.raises(ValidationError):
        LabRequestOptions.model_validate(
            {
                "image_list": "lighthouse.ceres/library/sketchbook:w_2077_43",
                "image_class": "recommended",
                "size": "medium",
            }
        )
    with pytest.raises(ValidationError):
        LabRequestOptions.model_validate(
            {
                "image_dropdown": [
                    "lighthouse.ceres/library/sketchbook:w_2077_43"
                ],
                "image_tag": "latest_weekly",
                "size": "medium",
            }
        )
    with pytest.raises(ValidationError):
        LabRequestOptions.model_validate(
            {
                "image_class": "recommended",
                "image_tag": "latest_weekly",
                "size": "medium",
            }
        )

    # Invalid boolean.
    with pytest.raises(ValidationError):
        LabRequestOptions.model_validate(
            {
                "image_tag": "latest_weekly",
                "size": "medium",
                "enable_debug": "on",
            }
        )


def test_cpu_resource_validation() -> None:
    with pytest.raises(ValueError, match=r"requests\.cpu must be less than"):
        # Ignore type checking here because even though the
        # ResourceQuantity.memory field must eventually get parsed into an int,
        # its validator can accept anything.
        LabResources(
            requests=ResourceQuantity(cpu=1.1, memory="1Gi"),
            limits=ResourceQuantity(cpu=1, memory="1Gi"),
        )


def test_memory_resource_validation() -> None:
    with pytest.raises(
        ValueError, match=r"requests\.memory must be less than"
    ):
        # Ignore type checking here because even though the
        # ResourceQuantity.memory field must eventually get parsed into an int,
        # its validator can accept anything.
        LabResources(
            requests=ResourceQuantity(cpu=1, memory="1.1Gi"),
            limits=ResourceQuantity(cpu=1, memory="1Gi"),
        )
