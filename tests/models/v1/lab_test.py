"""Tests for lab spawning models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jupyterlabcontroller.constants import DROPDOWN_SENTINEL_VALUE
from jupyterlabcontroller.models.v1.lab import ImageClass, LabSize, UserOptions


def test_user_options() -> None:
    """Test UserOptions, primarily all the ways to provide lab references."""
    options = UserOptions.parse_obj(
        {
            "image_list": "lighthouse.ceres/library/sketchbook:latest_daily",
            "size": "medium",
        }
    )
    assert options.dict(exclude_none=True) == {
        "image_list": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.MEDIUM,
        "enable_debug": False,
        "reset_user_env": False,
    }

    options = UserOptions.parse_obj(
        {
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "size": ["small"],
            "enable_debug": ["true"],
        }
    )
    assert options.dict(exclude_none=True) == {
        "image_dropdown": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.SMALL,
        "enable_debug": True,
        "reset_user_env": False,
    }

    # If the list is set to the sentinel value, it should be ignored.
    options = UserOptions.parse_obj(
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
    assert options.dict(exclude_none=True) == {
        "image_dropdown": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.LARGE,
        "enable_debug": False,
        "reset_user_env": True,
    }

    # If both list and dropdown are set, list should be used by preference and
    # dropdown ignored.
    options = UserOptions.parse_obj(
        {
            "image_list": "lighthouse.ceres/library/sketchbook:w_2077_43",
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "size": "medium",
        }
    )
    assert options.dict(exclude_none=True) == {
        "image_list": "lighthouse.ceres/library/sketchbook:w_2077_43",
        "size": LabSize.MEDIUM,
        "enable_debug": False,
        "reset_user_env": False,
    }

    # None and [] should be ignored, and DROPDOWN_SENTINEL_VALUE should still
    # be ignored even if it's not in a list.
    options = UserOptions.parse_obj(
        {
            "image_list": DROPDOWN_SENTINEL_VALUE,
            "image_dropdown": [
                "lighthouse.ceres/library/sketchbook:latest_daily"
            ],
            "image_class": None,
            "image_tag": [],
            "size": ["large"],
            "enable_debug": ["false"],
            "reset_user_env": ["true"],
        }
    )
    assert options.dict(exclude_none=True) == {
        "image_dropdown": "lighthouse.ceres/library/sketchbook:latest_daily",
        "size": LabSize.LARGE,
        "enable_debug": False,
        "reset_user_env": True,
    }

    # Check image_class and image_tag.
    options = UserOptions.parse_obj(
        {"image_class": "recommended", "size": "large", "enable_debug": True}
    )
    assert options.dict(exclude_none=True) == {
        "image_class": ImageClass.RECOMMENDED,
        "size": LabSize.LARGE,
        "enable_debug": True,
        "reset_user_env": False,
    }
    options = UserOptions.parse_obj(
        {"image_tag": "latest_daily", "size": LabSize.LARGE}
    )
    assert options.dict(exclude_none=True) == {
        "image_tag": "latest_daily",
        "size": LabSize.LARGE,
        "enable_debug": False,
        "reset_user_env": False,
    }

    # List of length longer than 1.
    with pytest.raises(ValidationError):
        UserOptions.parse_obj(
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
        UserOptions.parse_obj({"size": "medium"})

    # Images provided in multiple ways.
    with pytest.raises(ValidationError):
        UserOptions.parse_obj(
            {
                "image_list": "lighthouse.ceres/library/sketchbook:w_2077_43",
                "image_class": "recommended",
                "size": "medium",
            }
        )
    with pytest.raises(ValidationError):
        UserOptions.parse_obj(
            {
                "image_dropdown": [
                    "lighthouse.ceres/library/sketchbook:w_2077_43"
                ],
                "image_tag": "latest_weekly",
                "size": "medium",
            }
        )
    with pytest.raises(ValidationError):
        UserOptions.parse_obj(
            {
                "image_class": "recommended",
                "image_tag": "latest_weekly",
                "size": "medium",
            }
        )

    # Invalid boolean.
    with pytest.raises(ValidationError):
        UserOptions.parse_obj(
            {
                "image_tag": "latest_weekly",
                "size": "medium",
                "enable_debug": "on",
            }
        )
