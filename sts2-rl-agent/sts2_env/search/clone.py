"""Combat graph copies that rebind callbacks, unlike copy.deepcopy.

Only simulator objects and explicitly supported Python containers are accepted.
Code and module globals remain shared; captured mutable objects, bound methods,
closure cells, and inherited slots are copied with a single identity memo.
"""

from decimal import Decimal
from enum import Enum
from functools import lru_cache
from types import CellType, FunctionType, MethodType


_ATOMIC = {int, float, bool, str, bytes, type(None), complex, range, Decimal}


@lru_cache(maxsize=None)
def _slots(cls):
    result = []
    for base in cls.__mro__:
        names = base.__dict__.get("__slots__", ())
        if isinstance(names, str):
            names = (names,)
        for name in names:
            if name in ("__dict__", "__weakref__"):
                continue
            if name.startswith("__") and not name.endswith("__"):
                name = f"_{base.__name__.lstrip('_')}{name}"
            result.append(name)
    return tuple(dict.fromkeys(result))


def clone_state(value):
    """Copy a simulator graph; reject unsupported objects instead of aliasing."""
    return _copy(value, {})


def _copy(value, memo):
    cls = type(value)
    if cls in _ATOMIC or isinstance(value, (Enum, type)):
        return value
    key = id(value)
    if key in memo:
        return memo[key]
    if cls is list:
        result = []
        memo[key] = result
        # The RNG's integer arrays and many histories have atomic elements.
        result.extend(x if type(x) in _ATOMIC else _copy(x, memo) for x in value)
    elif cls is dict:
        result = {}
        memo[key] = result
        for k, v in value.items():
            result[k if type(k) in _ATOMIC else _copy(k, memo)] = (
                v if type(v) in _ATOMIC else _copy(v, memo)
            )
    elif cls is tuple:
        items = [_copy(x, memo) for x in value]
        # A tuple can be reached recursively through a mutable child.
        if key in memo:
            return memo[key]
        result = value if all(a is b for a, b in zip(items, value)) else tuple(items)
    elif cls is frozenset:
        items = [_copy(x, memo) for x in value]
        result = value if all(a is b for a, b in zip(items, value)) else frozenset(items)
    elif cls is set:
        result = set()
        memo[key] = result
        result.update(_copy(x, memo) for x in value)
    elif cls is CellType:
        result = CellType()
        memo[key] = result
        try:
            contents = value.cell_contents
        except ValueError:  # empty closure cell
            pass
        else:
            result.cell_contents = _copy(contents, memo)
    elif cls is FunctionType:
        if not value.__closure__ and not value.__defaults__ and not value.__kwdefaults__ and not value.__dict__:
            return value
        # Allocate shared empty cells before filling them, supporting recursive
        # closures and multiple callbacks sharing one nonlocal variable.
        pending = []
        cells = []
        for cell in value.__closure__ or ():
            if id(cell) not in memo:
                memo[id(cell)] = CellType()
                pending.append(cell)
            cells.append(memo[id(cell)])
        result = FunctionType(value.__code__, value.__globals__, value.__name__,
                              None, tuple(cells) if value.__closure__ else None)
        memo[key] = result
        for cell in pending:
            try:
                contents = cell.cell_contents
            except ValueError:
                continue
            memo[id(cell)].cell_contents = _copy(contents, memo)
        result.__defaults__ = _copy(value.__defaults__, memo)
        result.__kwdefaults__ = _copy(value.__kwdefaults__, memo)
        result.__dict__.update(_copy(value.__dict__, memo))
    elif cls is MethodType:
        owner = _copy(value.__self__, memo)
        if key in memo:
            return memo[key]
        result = MethodType(_copy(value.__func__, memo), owner)
    elif cls.__module__.startswith("sts2_env."):
        result = object.__new__(cls)
        memo[key] = result
        if hasattr(value, "__dict__"):
            result.__dict__.update(_copy(value.__dict__, memo))
        for name in _slots(cls):
            if hasattr(value, name):
                object.__setattr__(result, name, _copy(getattr(value, name), memo))
    else:
        raise TypeError(f"Unsupported search state object: {cls.__module__}.{cls.__name__}")
    memo[key] = result
    return result
