"""Collector registry.

A collector is a class with:
  - __init__(self, technology: str, id: str, **params) taking params from technologies.yaml
  - collect(self, input_path: str | None = None) -> list[Update]

`input_path` reads a saved copy of the source instead of the network. Tests use it.
Register a new collector type with @register("type-name").
"""

from __future__ import annotations

from typing import Callable

REGISTRY: dict[str, type] = {}


def register(type_name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        REGISTRY[type_name] = cls
        return cls
    return deco


def build(technology: str, spec: dict):
    spec = dict(spec)
    type_name = spec.pop("type")
    cid = spec.pop("id")
    if type_name not in REGISTRY:
        raise KeyError(f"unknown collector type {type_name!r}. Known: {sorted(REGISTRY)}")
    return REGISTRY[type_name](technology=technology, id=cid, **spec)


# Import built-in collectors so they register.
from . import learn_page, markdown_changelog, rss, snowflake_docs  # noqa: E402,F401
