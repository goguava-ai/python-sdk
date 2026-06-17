"""Backward-compatibility shim for the old VertexAI helper names.

.. deprecated::
    Use ``guava.helpers.genai`` and the ``GenAIEmbedding`` / ``GenAIGeneration``
    class names instead. This shim will be removed in a future release.
"""

import warnings

_RENAMES = {
    "VertexAIEmbedding": "GenAIEmbedding",
    "VertexAIGeneration": "GenAIGeneration",
}
_PASSTHROUGH = {"DEFAULT_EMBEDDING_MODEL", "DEFAULT_EMBEDDING_DIM", "DEFAULT_QA_MODEL"}

__all__ = [*_RENAMES, *_PASSTHROUGH]


def __getattr__(name: str):
    from . import genai as _genai

    if name in _RENAMES:
        warnings.warn(
            f"guava.helpers.vertexai.{name} has been renamed to "
            f"guava.helpers.genai.{_RENAMES[name]}. "
            "The vertexai shim will be removed in a future release.",
            DeprecationWarning,
            stacklevel=2,
        )
        resolved = getattr(_genai, _RENAMES[name])
        globals()[name] = resolved  # cache so __getattr__ isn't hit again
        return resolved
    if name in _PASSTHROUGH:
        resolved = getattr(_genai, name)
        globals()[name] = resolved
        return resolved
    raise AttributeError(f"module 'guava.helpers.vertexai' has no attribute {name!r}")
