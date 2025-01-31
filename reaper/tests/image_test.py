"""Tests for image comparison and sorting."""

from rsp_reaper.storage.dockerhub import DockerHubClient


def test_image_sort(dockerhub_client: DockerHubClient) -> None:
    """Test image comparison and sorting."""
    dockerhub_client.categorize()
    cat = dockerhub_client.categorized_images
    rels = list(cat.rsp["release"].values())
    assert rels == sorted(rels, reverse=True)


def test_image_counts(dockerhub_client: DockerHubClient) -> None:
    """Test whether categorization gets the right item counts."""
    dockerhub_client.categorize()
    cat = dockerhub_client.categorized_images
    counts = {
        "release": 31,
        "weekly": 204,
        "daily": 734,
        "release_candidate": 59,
        "experimental": 49,
        "unknown": 0,
    }
    for category, count in counts.items():
        assert len(cat.rsp[category]) == count
    assert len(cat.untagged) == 0
