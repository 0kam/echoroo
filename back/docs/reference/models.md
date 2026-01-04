# Database Models

Welcome to the comprehensive database models reference for **Echoroo**! Here, you'll
discover an organized collection of all the database models defined within the
Echoroo framework. Our categorization mirrors the structure outlined in
[`soundevent`](https://mbsantiago.github.io/soundevent/data_schemas/).

The models within **Echoroo** share an analogical relationship with those in
`soundevent` and are essentially a **SQLAlchemy** port. While the core concepts remain
consistent, it's essential to note that some minor differences do exist.

## Data Descriptors

### Users

::: echoroo.models.User
    options:
        heading_level: 4
        members: None

### Tags

::: echoroo.models.Tag
    options:
        heading_level: 4
        members: None

### Features

::: echoroo.models.FeatureName
    options:
        members: None
        heading_level: 4

### Notes

::: echoroo.models.Note
    options:
        heading_level: 4
        members: None

## Audio Content

### Recordings

::: echoroo.models.Recording
    options:
        heading_level: 4
        members: None

::: echoroo.models.RecordingTag
    options:
        heading_level: 4
        members: None

::: echoroo.models.RecordingNote
    options:
        heading_level: 4
        members: None

::: echoroo.models.RecordingFeature
    options:
        heading_level: 4
        members: None

::: echoroo.models.RecordingOwner
    options:
        heading_level: 4
        members: None

### Datasets

::: echoroo.models.Dataset
    options:
        heading_level: 4
        members: None

::: echoroo.models.DatasetRecording
    options:
        heading_level: 4
        members: None

## Acoustic Objects

### Sound Events

::: echoroo.models.SoundEvent
    options:
        heading_level: 4
        members: None

::: echoroo.models.SoundEventFeature
    options:
        heading_level: 4
        members: None

### Clips

::: echoroo.models.Clip
    options:
        heading_level: 4
        members: None

::: echoroo.models.ClipFeature
    options:
        heading_level: 4
        members: None

## Annotation

### Sound Event Annotation

::: echoroo.models.SoundEventAnnotation
    options:
        heading_level: 4
        members: None

::: echoroo.models.SoundEventAnnotationTag
    options:
        heading_level: 4
        members: None

::: echoroo.models.SoundEventAnnotationNote
    options:
        heading_level: 4
        members: None

### Clip Annotation

::: echoroo.models.ClipAnnotation
    options:
        heading_level: 4
        members: None

::: echoroo.models.ClipAnnotationTag
    options:
        heading_level: 4
        members: None

::: echoroo.models.ClipAnnotationNote
    options:
        heading_level: 4
        members: None

### Annotation Task

::: echoroo.models.AnnotationTask
    options:
        heading_level: 4
        members: None

::: echoroo.models.AnnotationStatusBadge
    options:
        heading_level: 4
        members: None

### Annotation Project

::: echoroo.models.AnnotationProject
    options:
        heading_level: 4
        members: None

::: echoroo.models.AnnotationProjectTag
    options:
        heading_level: 4
        members: None

## Prediction

### Sound Event Prediction

::: echoroo.models.SoundEventPrediction
    options:
        heading_level: 4
        members: None

::: echoroo.models.SoundEventPredictionTag
    options:
        heading_level: 4
        members: None

### Clip Prediction

::: echoroo.models.ClipPrediction
    options:
        heading_level: 4
        members: None

::: echoroo.models.ClipPredictionTag
    options:
        heading_level: 4
        members: None

### Model Run

::: echoroo.models.ModelRun
    options:
        heading_level: 4
        members: None

### User Run

::: echoroo.models.UserRun
    options:
        heading_level: 4
        members: None

## Evaluation

### Sound Event Evaluation

::: echoroo.models.SoundEventEvaluation
    options:
        heading_level: 4
        members: None

::: echoroo.models.SoundEventEvaluationMetric
    options:
        heading_level: 4
        members: None

### Clip Evaluation

::: echoroo.models.ClipEvaluation
    options:
        heading_level: 4
        members: None

::: echoroo.models.ClipEvaluationMetric
    options:
        heading_level: 4
        members: None

### Evaluation

::: echoroo.models.Evaluation
    options:
        heading_level: 4
        members: None

::: echoroo.models.EvaluationMetric
    options:
        heading_level: 4
        members: None

### Evaluation Set

::: echoroo.models.EvaluationSet
    options:
        heading_level: 4
        members: None

::: echoroo.models.EvaluationSetTag
    options:
        heading_level: 4
        members: None

::: echoroo.models.EvaluationSetAnnotation
    options:
        heading_level: 4
        members: None
