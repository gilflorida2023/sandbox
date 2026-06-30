"""Workflow registry — import once to register all workflow types."""

_registry = {}


def register(name):
    """Decorator: register a Pipeline subclass under *name*."""
    def wrapper(cls):
        _registry[name] = cls
        return cls
    return wrapper


def get_workflow(name):
    """Return an instantiated workflow by name."""
    if name not in _registry:
        available = ", ".join(_registry)
        raise ValueError(f"Unknown workflow '{name}'. Available: {available}")
    cls = _registry[name]
    return cls()


def list_workflows():
    """Return dict of {name: description}."""
    return {name: cls.description for name, cls in _registry.items()}


# Import to trigger registration
from . import code_review  # noqa: F401, E402
from . import context_load  # noqa: F401, E402
from . import ingest_knowledge  # noqa: F401, E402
