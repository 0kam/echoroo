"""Search session endpoints — compat façade over the ``sessions/`` package.

Handles listing, getting, updating, deleting, and re-running search sessions,
as well as streaming reference audio and exporting session annotations as CSV.

W3-1: the former single ``sessions.py`` module (1458 LOC) was split into a
package of cohesive sub-modules. This ``__init__`` re-exports every public and
``_underscore`` symbol so the original import path
``echoroo.api.v1.search.sessions`` keeps working unchanged — both for the
``/web-api/v1`` BFF (``echoroo.api.web_v1.projects._search``) which resolves the
handlers via call-time attribute lookup, and for tests that patch/setattr on the
façade. Mirrors the ``workers/ml_tasks.py`` → ``workers/ml/`` precedent.

Sub-modules:
- crud.py         : list / get / delete / update / rerun handlers
- media.py        : ``stream_reference_audio`` (unmounted reference-audio stream)
- exports.py      : CSV export handlers + their helper chain
- distribution.py : similarity / time distribution + sampling handlers
- _shared.py      : ``_get_query_vectors_from_session`` (used by exports + distribution)

W2-4 PR-B: ``router`` carries ZERO routes; ``search/__init__.py`` still includes
it (harmless empty include), so the empty ``APIRouter`` below is intentional.
"""

from fastapi import APIRouter

from echoroo.api.v1.search.sessions._shared import _get_query_vectors_from_session
from echoroo.api.v1.search.sessions.crud import (
    delete_search_session,
    get_search_session,
    list_search_sessions,
    rerun_search_session,
    update_search_session,
)
from echoroo.api.v1.search.sessions.distribution import (
    get_session_similarity_distribution,
    get_session_time_distribution,
    sample_session_similarity_range,
)
from echoroo.api.v1.search.sessions.exports import (
    _EXPORT_CSV_HEADER,
    _build_species_labels,
    _compute_similarity_aggregates,
    _fetch_session_recordings,
    _resolve_locale_common_names,
    _write_recordings_csv,
    export_search_session_csv,
    export_search_session_recordings_csv,
)
from echoroo.api.v1.search.sessions.media import stream_reference_audio

# W2-4 PR-B: intentionally empty; search/__init__.py still includes it.
router = APIRouter()

__all__ = [
    "router",
    # crud
    "list_search_sessions",
    "get_search_session",
    "delete_search_session",
    "update_search_session",
    "rerun_search_session",
    # media
    "stream_reference_audio",
    # exports
    "_build_species_labels",
    "_fetch_session_recordings",
    "_resolve_locale_common_names",
    "_compute_similarity_aggregates",
    "_EXPORT_CSV_HEADER",
    "_write_recordings_csv",
    "export_search_session_recordings_csv",
    "export_search_session_csv",
    # distribution
    "get_session_similarity_distribution",
    "get_session_time_distribution",
    "sample_session_similarity_range",
    # shared
    "_get_query_vectors_from_session",
]
