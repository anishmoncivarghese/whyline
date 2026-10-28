"""Python 3.11 refuses a dataclass field whose default is unhashable
(dict, list, set, or a mappingproxy, which only became hashable in 3.12).
Agents write on 3.13, so this check catches it there before a release."""

import dataclasses
import importlib
import pkgutil
from types import MappingProxyType

import whyline

_UNSAFE = (dict, list, set, MappingProxyType)


def _modules():
    for info in pkgutil.walk_packages(whyline.__path__, "whyline."):
        if info.name.endswith("__main__"):
            continue
        try:
            yield importlib.import_module(info.name)
        except ImportError:
            continue


def test_no_dataclass_field_has_an_unhashable_default():
    bad = []
    for module in _modules():
        for value in vars(module).values():
            if not (dataclasses.is_dataclass(value) and isinstance(value, type)):
                continue
            if value.__module__ != module.__name__:
                continue
            for f in dataclasses.fields(value):
                if isinstance(f.default, _UNSAFE):
                    bad.append(f"{value.__module__}.{value.__qualname__}.{f.name}")
    assert bad == []
