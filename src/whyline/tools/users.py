"""Who uses which thing. Credentials, servers, skills and packs ask here before
they are removed; each kind of user registers a provider that lists its uses."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Use:
    thing: str  # "credential", "server", "skill", "pack"
    name: str
    user: str  # for example "agent research-digest"


_providers: dict[str, Callable[[], list[Use]]] = {}


def register(kind: str, provider: Callable[[], list[Use]]) -> None:
    """Register (or replace) the provider for one kind of user."""
    _providers[kind] = provider


def unregister(kind: str) -> None:
    _providers.pop(kind, None)


def of(thing: str, name: str) -> list[str]:
    """Every user of ``thing`` called ``name``, sorted and without repeats."""
    found: set[str] = set()
    for provider in list(_providers.values()):
        for use in provider():
            if use.thing == thing and use.name == name:
                found.add(use.user)
    return sorted(found)
