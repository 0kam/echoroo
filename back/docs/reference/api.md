# Echoroo Python API

Welcome to the Echoroo Python API reference page. This section provides a
comprehensive guide to all the functions available through the `echoroo.api`
module, designed to simplify the use of Echoroo objects without the need to
handle the intricacies of SQLAlchemy internals.

The API is organized into distinct submodules, each corresponding to a crucial
data object within Echoroo. Each sub-API contains functions tailored for
interactions with that specific type of object.

## Getting Started

To get started, follow the example below, which demonstrates how to use these functions:

```python
from echoroo import api

async def main():
    # Create a session
    async with api.create_session() as session:
        # Example 1: Get or create a tag
        tag = await api.tags.get_or_create(session, key="species", value="Myotis myotis")

        # Example 2: Retrieve a recording by path
        recording = await api.recordings.get_by_path(session, path="<path_to_file>")

        # Example 3: Add a tag to a recording
        recording = await api.recordings.add_tag(session, recording, tag)
```

!!! info "Async functions"

    Most functions in the Echoroo API are asynchronous. This design choice enhances
    code efficiency, particularly since many operations involve database
    transactions that can potentially slow down the program if executed
    synchronously.

On this page, you can explore all the submodules available and the functions
they provide. It's worth noting that each submodule is an instance of a BaseAPI
class, which manages an internal cache to minimize unnecessary database
queries. To access the reference for a specific submodule, such as
`api.sound_events`, please consult the corresponding class, in this case,
[`SoundEventAPI`][echoroo.api.sound_events.SoundEventAPI], to discover all the available functions.

::: echoroo.api

::: echoroo.api.users.UserAPI
    options:
        inherited_members: true

::: echoroo.api.tags.TagAPI
    options:
        inherited_members: true

::: echoroo.api.features.FeatureNameAPI
    options:
        inherited_members: true

::: echoroo.api.notes.NoteAPI
    options:
        inherited_members: true

::: echoroo.api.recordings.RecordingAPI
    options:
        inherited_members: true

::: echoroo.api.datasets.DatasetAPI
    options:
        inherited_members: true

::: echoroo.api.sound_events.SoundEventAPI
    options:
        inherited_members: true

::: echoroo.api.clips.ClipAPI
    options:
        inherited_members: true

::: echoroo.api.sound_event_annotations.SoundEventAnnotationAPI
    options:
        inherited_members: true

::: echoroo.api.clip_annotations.ClipAnnotationAPI
    options:
        inherited_members: true

::: echoroo.api.annotation_tasks.AnnotationTaskAPI
    options:
        inherited_members: true

::: echoroo.api.annotation_projects.AnnotationProjectAPI
    options:
        inherited_members: true

::: echoroo.api.sound_event_predictions.SoundEventPredictionAPI
    options:
        inherited_members: true

::: echoroo.api.clip_predictions.ClipPredictionAPI
    options:
        inherited_members: true

::: echoroo.api.model_runs.ModelRunAPI
    options:
        inherited_members: true

::: echoroo.api.user_runs.UserRunAPI
    options:
        inherited_members: true

::: echoroo.api.sound_event_evaluations.SoundEventEvaluationAPI
    options:
        inherited_members: true

::: echoroo.api.clip_evaluations.ClipEvaluationAPI
    options:
        inherited_members: true

::: echoroo.api.evaluations.EvaluationAPI
    options:
        inherited_members: true

::: echoroo.api.evaluation_sets.EvaluationSetAPI
    options:
        inherited_members: true
