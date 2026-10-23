"""L3 · a thin, deterministic bridge from a JobSpec (0.3.0) onto the ``l3_service`` kernel.

This is deliberately small and side-effect-free at import time. It only does two things:

  * :func:`frozen_recipe_b64`   — recover a frozen base64 kernel-recipe blob if the spec
                                  already carries one (a string on ``sketch.recipe``).
  * :func:`recipe_apply_from_spec` — send that blob to the kernel via
    :class:`l3_client.L3Client.recipe_apply`, or raise a clear :class:`L3NotConfigured`
    explaining that a frozen base64 recipe is required.

Why the blob is optional / often absent: the JobSpec 0.3.0 ``FrozenSketch.recipe`` field is
typed ``dict`` and is documented as "kernel feature/variable list". It does *not* yet carry a
base64 cereal blob. The kernel front-end (per the L3 contract) expects ``recipe`` to be a
base64 serialisation. So the bridge is a *pass-through*: if you have already produced and
stored a blob, it is forwarded verbatim; if you only have the feature/variable dict, it is
surfaced as a clear configuration error rather than silently inventing an encoder.

No AI-provider imports. Deterministic and offline.
"""
from __future__ import annotations

from typing import Any

from l3_client import L3Client, L3NotConfigured, default_socket_path  # noqa: E402

__all__ = ["frozen_recipe_b64", "recipe_apply_from_spec", "L3NotConfigured"]


# ---- shape helpers ---------------------------------------------------------

def _get_recipe_field(spec2: Any) -> Any:
    """Return ``sketch.recipe`` from a ``JobSpec2`` instance or a spec-dump dict; None if absent."""
    sketch = None
    if isinstance(spec2, dict):
        sketch = spec2.get("sketch")
    elif hasattr(spec2, "sketch"):
        sketch = spec2.sketch

    if isinstance(sketch, dict):
        return sketch.get("recipe")
    if hasattr(sketch, "recipe"):
        return sketch.recipe
    return None


# ---- public API ------------------------------------------------------------

def frozen_recipe_b64(spec2: Any) -> str | None:
    """If the spec already carries a base64 kernel-recipe blob (a string on ``sketch.recipe``),
    return it. Otherwise (feature/variable dict, empty, or absent) return ``None``.

    We never *invent* a cereal encoder: the 0.3.0 schema stores a feature dict (or nothing)
    in ``sketch.recipe`` until a real serializer is produced upstream.
    """
    r = _get_recipe_field(spec2)
    if isinstance(r, str) and r:
        # a base64 blob is opaque to us; returning it verbatim keeps the kernel the
        # sole authority over what bytes make up a "recipe".
        return r
    return None


def recipe_apply_from_spec(
    spec2: Any,
    socket_path: str | None = None,
    text: dict | None = None,
    project: dict | None = None,
) -> dict:
    """Send the spec's frozen base64 recipe to the kernel via ``recipe.apply``.

    Parameters
    ----------
    spec2:
        A ``JobSpec2`` instance or a spec-dump dict. Must carry a base64 blob on
        ``sketch.recipe``; see :func:`frozen_recipe_b64`.
    socket_path:
        Override :data:`l3_client.DEFAULT_SOCKET_PATH` for this call only.
        Defaults to the ``SNAPORCA_L3_SOCK`` env var, else ``/tmp/snaporca-l3.sock``.
    text / project:
        Optional passthrough payloads forwarded to ``recipe.apply`` verbatim.

    Raises
    ------
    L3NotConfigured
        When no base64 blob is present on the spec — the kernel cannot be applied to
        the spec in that state and the caller must produce one first.
    L3ConnectionError / L3RpcError
        On transport or JSON-RPC protocol errors (see :mod:`l3_client`).
    """
    blob = frozen_recipe_b64(spec2)
    if blob is None:
        raise L3NotConfigured(
            "recipe.apply requires a frozen base64 kernel-recipe blob on "
            "spec2.sketch.recipe. The JobSpec 0.3.0 schema currently stores a "
            "feature/variable dict there (or nothing at all), not a base64 "
            "serialisation — the kernel front-end will not accept a feature dict. "
            "Produce a frozen base64 blob upstream and attach it to the spec before "
            "calling this bridge. See FrozenSketch.recipe in core/jobspec2.py:"
            " 49 (field) and :166 (migration default)."
        )

    path = socket_path if socket_path is not None else default_socket_path()
    client = L3Client(path)
    return client.recipe_apply(blob, text=text, project=project)
