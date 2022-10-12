"""Models for jupyterlab-controller."""

from typing import List

from pydantic import BaseModel


class Node(BaseModel):
    name: str
    eligible: bool = True
    comment: str
    cached: List[str] = []


class Image(BaseModel):
    url: str
    name: str
    tag: str
    hash: str = ""
    prepulled: bool = False
    nodes: List[Node] = []
    missing: List[Node] = []
