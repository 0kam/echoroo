"""W1-4: custom-model inference runs carry run_type=custom.

``CustomModelService.create_detection_run`` must stamp the first-class
``run_type`` discriminator so custom-SVM inference rows are classified as
``custom`` (and stay out of the detection/embedding status panels).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus, DetectionRunType
from echoroo.services.custom_model import CustomModelService


@pytest.mark.asyncio
async def test_create_detection_run_sets_custom_run_type() -> None:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    service = CustomModelService(db)

    model = MagicMock()
    model.id = uuid4()
    model.embedding_model_name = "perch"

    run = await service.create_detection_run(
        project_id=uuid4(),
        dataset_id=uuid4(),
        model=model,
        threshold=0.5,
    )

    assert isinstance(run, DetectionRun)
    assert run.run_type == DetectionRunType.CUSTOM
    assert run.model_name == "custom_svm"
    assert run.status == DetectionRunStatus.PENDING
    db.add.assert_called_once_with(run)
    db.commit.assert_awaited_once()
