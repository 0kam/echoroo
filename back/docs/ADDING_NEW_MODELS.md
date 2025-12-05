# Adding New Models Guide

新しい機械学習モデルをWhombat/EchorooのML推論システムに統合するための完全ガイド。

## クイックスタートチェックリスト

新しいモデルを追加する際の手順：

- [ ] 1. モデルの要件を定義（サンプルレート、セグメント長、埋め込み次元）
- [ ] 2. モデルパッケージのインストールと動作確認
- [ ] 3. `ModelLoader`サブクラスの実装
- [ ] 4. `InferenceEngine`サブクラスの実装
- [ ] 5. 定数とメタデータの定義
- [ ] 6. `ModelRegistry`への登録
- [ ] 7. ユニットテストの作成
- [ ] 8. 統合テストの実行
- [ ] 9. ドキュメントの更新
- [ ] 10. パフォーマンステストの実施

## ステップバイステップガイド

### ステップ 1: モデル仕様の定義

まず、モデルの技術仕様を明確にします。

**必要な情報:**
- サンプルレート（例: 48000 Hz）
- セグメント長（例: 3.0秒）
- 埋め込み次元（例: 1024）
- 分類サポートの有無
- 種リスト（分類をサポートする場合）

**例: MyBirdモデル**
```
Name: mybird
Version: 1.0
Sample Rate: 32000 Hz
Segment Duration: 5.0 seconds
Embedding Dimension: 768
Supports Classification: Yes
Number of Species: 3500
```

### ステップ 2: ファイル構造の作成

新しいモデル用のモジュールを作成：

```
back/src/whombat/ml/
└── mybird/
    ├── __init__.py          # モジュールの初期化とレジストリ登録
    ├── constants.py         # モデル定数
    ├── loader.py            # ModelLoaderの実装
    ├── inference.py         # InferenceEngineの実装
    └── metadata.py          # (オプション) メタデータフィルタ
```

### ステップ 3: 定数の定義

`constants.py`を作成：

```python
"""MyBird model constants."""

# Model identification
MODEL_NAME = "mybird"
MYBIRD_VERSION = "1.0"

# Audio requirements
SAMPLE_RATE = 32000  # Hz
SEGMENT_DURATION = 5.0  # seconds
SEGMENT_SAMPLES = int(SAMPLE_RATE * SEGMENT_DURATION)  # 160000

# Model output
EMBEDDING_DIM = 768
NUM_SPECIES = 3500

# Processing defaults
DEFAULT_CONFIDENCE_THRESHOLD = 0.1
DEFAULT_TOP_K = 10
```

### ステップ 4: ModelLoaderの実装

`loader.py`を作成：

```python
"""MyBird model loader module."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from whombat.ml.base import ModelLoader, ModelSpecification
from whombat.ml.mybird.constants import (
    MYBIRD_VERSION,
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
)

logger = logging.getLogger(__name__)


class MyBirdLoader(ModelLoader):
    """Loader for MyBird model.

    This class provides a thread-safe mechanism to initialize the MyBird
    model with lazy loading.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory containing model files. If None, downloads automatically.
    """

    def __init__(self, model_dir: Path | None = None) -> None:
        super().__init__(model_dir)
        self._species_list: list[str] | None = None

    @property
    def specification(self) -> ModelSpecification:
        """Get the MyBird model specification."""
        return ModelSpecification(
            name="mybird",
            version=MYBIRD_VERSION,
            sample_rate=SAMPLE_RATE,
            segment_duration=SEGMENT_DURATION,
            embedding_dim=EMBEDDING_DIM,
            supports_classification=True,
            species_list=self._species_list,
        )

    def _load_model(self) -> Any:
        """Load the MyBird model into memory.

        Returns
        -------
        Any
            The loaded mybird model instance.

        Raises
        ------
        ImportError
            If the mybird package is not installed.
        RuntimeError
            If model loading fails.
        """
        try:
            import mybird  # Replace with actual package name
        except ImportError as e:
            raise ImportError(
                "mybird package is required for MyBird model loading. "
                "Install it with: pip install mybird"
            ) from e

        try:
            # Load model (adjust based on actual API)
            if self.model_dir:
                model = mybird.load_model(self.model_dir)
            else:
                model = mybird.load_default_model()

            # Cache species list
            self._species_list = list(model.get_species_list())

            logger.debug(
                f"MyBird model initialized with "
                f"sample_rate={SAMPLE_RATE}Hz, "
                f"embedding_dim={EMBEDDING_DIM}, "
                f"n_species={len(self._species_list)}"
            )

            return model

        except Exception as e:
            raise RuntimeError(f"Failed to load MyBird model: {e}") from e
```

### ステップ 5: InferenceEngineの実装

`inference.py`を作成：

```python
"""MyBird inference engine."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from whombat.ml.audio import validate_audio_segment
from whombat.ml.base import InferenceEngine, InferenceResult
from whombat.ml.mybird.constants import (
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
)

if TYPE_CHECKING:
    from whombat.ml.mybird.loader import MyBirdLoader

logger = logging.getLogger(__name__)


class MyBirdInference(InferenceEngine):
    """Run MyBird inference on audio files.

    Parameters
    ----------
    loader : MyBirdLoader
        A loaded MyBird model loader instance.
    confidence_threshold : float, optional
        Minimum confidence score for predictions. Default is 0.1.
    top_k : int, optional
        Maximum number of top predictions to return. Default is 10.
    """

    def __init__(
        self,
        loader: MyBirdLoader,
        confidence_threshold: float = 0.1,
        top_k: int = 10,
    ) -> None:
        super().__init__(loader)
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k

    @property
    def confidence_threshold(self) -> float:
        """Get the current confidence threshold."""
        return self._confidence_threshold

    @confidence_threshold.setter
    def confidence_threshold(self, value: float) -> None:
        """Set the confidence threshold."""
        if not 0 <= value <= 1:
            raise ValueError(f"threshold must be in [0, 1], got {value}")
        self._confidence_threshold = value

    @property
    def top_k(self) -> int:
        """Get the current top-k setting."""
        return self._top_k

    @top_k.setter
    def top_k(self, value: int) -> None:
        """Set the top-k value."""
        if value < 1:
            raise ValueError(f"top_k must be >= 1, got {value}")
        self._top_k = value

    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float = 0.0,
    ) -> InferenceResult:
        """Run inference on a single segment.

        Parameters
        ----------
        audio : NDArray[np.float32]
            Audio data at 32kHz, shape (160000,).
        start_time : float, optional
            Start time of the segment. Default is 0.0.

        Returns
        -------
        InferenceResult
            Inference result with embedding and predictions.
        """
        # Validate audio
        audio = validate_audio_segment(
            audio,
            expected_samples=SEGMENT_SAMPLES,
            sample_rate=SAMPLE_RATE,
            model_name="MyBird",
        )

        # Get embedding
        embedding = self._model.get_embedding(audio)

        # Ensure correct shape and dtype
        embedding = np.asarray(embedding, dtype=np.float32)
        if embedding.shape != (EMBEDDING_DIM,):
            embedding = embedding.flatten()[:EMBEDDING_DIM]

        # Get predictions
        predictions_list = []
        if self.specification.supports_classification:
            probs = self._model.predict(audio)
            species_list = self._model.get_species_list()

            # Get top-k predictions
            top_indices = np.argsort(probs)[-self._top_k:][::-1]
            for idx in top_indices:
                conf = float(probs[idx])
                if conf >= self._confidence_threshold:
                    species = species_list[idx]
                    predictions_list.append((species, conf))

        return InferenceResult(
            start_time=start_time,
            end_time=start_time + SEGMENT_DURATION,
            embedding=embedding,
            predictions=predictions_list,
        )

    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        """Run batch inference on multiple segments.

        Parameters
        ----------
        segments : list[NDArray[np.float32]]
            List of audio segments.
        start_times : list[float]
            List of start times.

        Returns
        -------
        list[InferenceResult]
            List of inference results.
        """
        if len(segments) != len(start_times):
            raise ValueError(
                f"segments and start_times must have same length, "
                f"got {len(segments)} and {len(start_times)}"
            )

        if not segments:
            return []

        # Option 1: Process individually
        results = []
        for segment, start_time in zip(segments, start_times):
            result = self.predict_segment(segment, start_time)
            results.append(result)

        # Option 2: Use model's batch processing if available
        # embeddings = self._model.get_embeddings_batch(segments)
        # predictions = self._model.predict_batch(segments)
        # ... build results

        return results

    def predict_file(
        self,
        path: Path,
        overlap: float = 0.0,
    ) -> list[InferenceResult]:
        """Run inference on an entire audio file.

        This method can be overridden if the model has efficient
        file processing. Otherwise, the base class implementation
        using AudioPreprocessor will be used.

        Parameters
        ----------
        path : Path
            Path to audio file.
        overlap : float, optional
            Overlap between segments in seconds. Default is 0.0.

        Returns
        -------
        list[InferenceResult]
            List of inference results.
        """
        # Option 1: Use base class implementation (recommended)
        return super().predict_file(path, overlap)

        # Option 2: Override with model-specific file processing
        # if self._model.has_file_processing:
        #     return self._process_file_native(path, overlap)
        # else:
        #     return super().predict_file(path, overlap)
```

### ステップ 6: モジュール初期化とレジストリ登録

`__init__.py`を作成：

```python
"""MyBird model integration for Whombat.

This module provides functionality to load and use the MyBird model
for bird species identification from audio recordings.

Model specifications:
- Input: 5 second audio at 32kHz (160,000 samples)
- Output: 768-dim embedding + species classification
"""

from whombat.ml.mybird.constants import (
    MYBIRD_VERSION,
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
)
from whombat.ml.mybird.inference import MyBirdInference
from whombat.ml.mybird.loader import MyBirdLoader
from whombat.ml.registry import ModelRegistry

__all__ = [
    # Constants
    "MYBIRD_VERSION",
    "EMBEDDING_DIM",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    # Classes
    "MyBirdInference",
    "MyBirdLoader",
]

# Register MyBird with the model registry
ModelRegistry.register(
    name="mybird",
    loader_class=MyBirdLoader,
    engine_class=MyBirdInference,
    filter_class=None,  # Add filter if implemented
    description="MyBird V1.0 bird species identification model",
)
```

### ステップ 7: モデルの有効化

`back/src/whombat/ml/__init__.py`に新しいモデルをインポート：

```python
# Import model modules to trigger registration
from whombat.ml import birdnet as birdnet  # noqa: F401
from whombat.ml import mybird as mybird  # noqa: F401  # ADD THIS LINE

__all__ = [
    # ... existing exports
    "mybird",  # ADD THIS LINE
]
```

### ステップ 8: テストの作成

`back/tests/test_ml/test_mybird.py`を作成：

```python
"""Tests for MyBird model integration."""

import numpy as np
import pytest

from whombat.ml.mybird import (
    MyBirdInference,
    MyBirdLoader,
    SAMPLE_RATE,
    SEGMENT_SAMPLES,
)


class TestMyBirdLoader:
    """Tests for MyBirdLoader."""

    def test_loader_initialization(self):
        """Test that loader can be initialized."""
        loader = MyBirdLoader()
        assert not loader.is_loaded
        assert loader.specification.name == "mybird"

    def test_loader_load(self):
        """Test that loader can load model."""
        pytest.importorskip("mybird")  # Skip if package not installed

        loader = MyBirdLoader()
        loader.load()
        assert loader.is_loaded
        assert loader.get_model() is not None

    def test_specification(self):
        """Test model specification."""
        loader = MyBirdLoader()
        spec = loader.specification

        assert spec.name == "mybird"
        assert spec.sample_rate == SAMPLE_RATE
        assert spec.segment_samples == SEGMENT_SAMPLES


class TestMyBirdInference:
    """Tests for MyBirdInference."""

    @pytest.fixture
    def loader(self):
        """Create and load a MyBird loader."""
        pytest.importorskip("mybird")
        loader = MyBirdLoader()
        loader.load()
        return loader

    @pytest.fixture
    def engine(self, loader):
        """Create a MyBird inference engine."""
        return MyBirdInference(loader)

    def test_predict_segment(self, engine):
        """Test single segment prediction."""
        audio = np.random.randn(SEGMENT_SAMPLES).astype(np.float32)
        result = engine.predict_segment(audio, start_time=0.0)

        assert result.start_time == 0.0
        assert result.end_time > 0.0
        assert result.embedding.shape == (768,)
        assert result.embedding.dtype == np.float32

    def test_predict_batch(self, engine):
        """Test batch prediction."""
        segments = [
            np.random.randn(SEGMENT_SAMPLES).astype(np.float32)
            for _ in range(3)
        ]
        start_times = [0.0, 5.0, 10.0]

        results = engine.predict_batch(segments, start_times)

        assert len(results) == 3
        assert all(r.embedding.shape == (768,) for r in results)

    def test_confidence_threshold(self, engine):
        """Test confidence threshold setting."""
        engine.confidence_threshold = 0.5
        assert engine.confidence_threshold == 0.5

        with pytest.raises(ValueError):
            engine.confidence_threshold = 1.5

    def test_top_k(self, engine):
        """Test top-k setting."""
        engine.top_k = 5
        assert engine.top_k == 5

        with pytest.raises(ValueError):
            engine.top_k = 0
```

### ステップ 9: 統合テスト

モデルがInferenceWorkerで動作することを確認：

```python
"""Integration test for MyBird with InferenceWorker."""

import pytest
from pathlib import Path

from whombat.ml.worker import InferenceWorker
from whombat.ml.registry import ModelRegistry


def test_mybird_with_worker(tmp_path, db_session):
    """Test MyBird integration with InferenceWorker."""
    pytest.importorskip("mybird")

    # Check model is registered
    assert "mybird" in ModelRegistry.available_models()

    # Create worker
    worker = InferenceWorker(
        audio_dir=tmp_path,
        model_dir=None,
    )

    # Worker should be able to load MyBird
    from whombat.schemas import InferenceConfig
    config = InferenceConfig(
        model_name="mybird",
        model_version="1.0",
        confidence_threshold=0.1,
    )

    engine = worker._ensure_model_loaded(config)
    assert engine is not None
    assert engine.specification.name == "mybird"
```

### ステップ 10: ドキュメントの更新

#### ML_MODELS.mdに追加

```markdown
## MyBird V1.0

MyBirdは、新しい高精度な鳥類分類モデルです。

### スペック
- 入力: 5秒 @ 32kHz (160,000 samples)
- 埋め込み: 768次元
- 出力: 3,500種の鳥類分類
- パッケージバージョン: 1.0+

### インストール

```bash
pip install mybird
```

### 使用例

```python
from whombat.ml.mybird import MyBirdLoader, MyBirdInference

# Load model
loader = MyBirdLoader()
loader.load()

# Create inference engine
inference = MyBirdInference(loader, confidence_threshold=0.25)

# Process audio
results = inference.predict_file("/path/to/audio.wav")
```
```

## 命名規則とベストプラクティス

### ファイル命名規則

```
モジュール名: whombat.ml.<model_name>
クラス名: <ModelName>Loader, <ModelName>Inference
定数ファイル: constants.py
テストファイル: test_<model_name>.py
```

### コーディングスタイル

1. **型ヒント**: すべての公開メソッドに型ヒントを追加
2. **Docstrings**: Numpyスタイルのdocstringsを使用
3. **ロギング**: 適切なログレベルで情報をログ
4. **エラーハンドリング**: 明確なエラーメッセージで例外を発生

### 性能の考慮事項

1. **バッチ処理**: 可能な限りバッチ推論を実装
2. **メモリ管理**: 大きなモデルの場合、lazy loadingを使用
3. **GPU対応**: GPUサポートがある場合、適切に活用
4. **キャッシング**: 頻繁にアクセスするデータをキャッシュ

## よくある落とし穴と解決策

### 1. NumPy dtype の不一致

**問題:**
```python
embedding = model.get_embedding(audio)  # Returns float64
```

**解決策:**
```python
embedding = np.asarray(embedding, dtype=np.float32)
```

### 2. 音声形状の検証忘れ

**問題:**
```python
# No validation, may crash on wrong input
result = model.predict(audio)
```

**解決策:**
```python
from whombat.ml.audio import validate_audio_segment

audio = validate_audio_segment(
    audio,
    expected_samples=SEGMENT_SAMPLES,
    sample_rate=SAMPLE_RATE,
    model_name="MyBird",
)
```

### 3. スレッドセーフティの欠如

**問題:**
```python
def _load_model(self):
    if not self._loaded:  # Race condition!
        self._model = load()
        self._loaded = True
```

**解決策:**
```python
# Base class already handles this with double-checked locking
# Just implement _load_model()
def _load_model(self):
    return load()  # Called within lock
```

### 4. 予測形式の不一致

**問題:**
```python
# Returning wrong format
predictions = [("species", 0.95, "extra_field")]  # Wrong!
```

**解決策:**
```python
# Must be list of (label, confidence) tuples
predictions = [("species", 0.95)]  # Correct
```

### 5. モデル登録忘れ

**問題:**
```python
# __init__.py doesn't register the model
# Worker can't find it!
```

**解決策:**
```python
# Always register in __init__.py
ModelRegistry.register(
    name="mybird",
    loader_class=MyBirdLoader,
    engine_class=MyBirdInference,
)
```

## パフォーマンステスト

新しいモデルのパフォーマンスをテスト：

```python
"""Performance benchmark for MyBird."""

import time
import numpy as np
from whombat.ml.mybird import MyBirdLoader, MyBirdInference

# Load model
loader = MyBirdLoader()
loader.load()
engine = MyBirdInference(loader)

# Benchmark single segment
audio = np.random.randn(160000).astype(np.float32)
start = time.time()
for _ in range(100):
    result = engine.predict_segment(audio)
elapsed = time.time() - start
print(f"Average time per segment: {elapsed / 100 * 1000:.2f}ms")

# Benchmark batch
segments = [audio for _ in range(32)]
start_times = [i * 5.0 for i in range(32)]
start = time.time()
results = engine.predict_batch(segments, start_times)
elapsed = time.time() - start
print(f"Batch time: {elapsed:.2f}s ({len(segments) / elapsed:.2f} segments/s)")
```

## ワーカーとの統合

### InferenceConfigの更新

モデルがワーカーで利用可能になるように、設定スキーマを確認：

```python
# back/src/whombat/schemas/inference.py

class InferenceConfig(BaseModel):
    """Configuration for inference jobs."""

    model_name: str = Field(
        description="Name of the model to use",
        # Add your model to examples
        examples=["birdnet", "mybird"],
    )
    model_version: str = Field(
        description="Version of the model",
    )
    # ... other fields
```

### ワーカーでのモデル選択

ワーカーは自動的にレジストリを使用してモデルをロード：

```python
# In InferenceWorker._ensure_model_loaded()
if config.model_name == "mybird":
    return self._ensure_mybird_loaded(config)
```

必要に応じて`worker.py`に専用のローダーメソッドを追加。

## トラブルシューティング

### モデルが見つからない

```python
>>> from whombat.ml.registry import ModelRegistry
>>> ModelRegistry.available_models()
[]  # Empty! Model not registered
```

**解決策:** `whombat.ml.__init__.py`にモデルをインポート

### Import エラー

```bash
ImportError: cannot import name 'MyBirdLoader'
```

**解決策:**
1. `__init__.py`にクラスをエクスポート
2. 循環インポートを確認
3. パッケージを再インストール

### メモリリーク

**症状:** ワーカーのメモリ使用量が増加し続ける

**解決策:**
1. モデルのアンロードを実装
2. バッチサイズを減らす
3. ガベージコレクションを明示的に実行

## 例: 完全な実装（シンプルなモデル）

最小限の実装例：

```python
# constants.py
MODEL_NAME = "simple"
VERSION = "1.0"
SAMPLE_RATE = 16000
SEGMENT_DURATION = 1.0
EMBEDDING_DIM = 128

# loader.py
from whombat.ml.base import ModelLoader, ModelSpecification

class SimpleLoader(ModelLoader):
    @property
    def specification(self):
        return ModelSpecification(
            name="simple",
            version="1.0",
            sample_rate=16000,
            segment_duration=1.0,
            embedding_dim=128,
            supports_classification=False,
        )

    def _load_model(self):
        # Return a simple model (could be a dict, object, etc.)
        return {"loaded": True}

# inference.py
from whombat.ml.base import InferenceEngine, InferenceResult
import numpy as np

class SimpleInference(InferenceEngine):
    def predict_segment(self, audio, start_time):
        # Simple embedding: just compute mean and std
        embedding = np.random.randn(128).astype(np.float32)

        return InferenceResult(
            start_time=start_time,
            end_time=start_time + 1.0,
            embedding=embedding,
            predictions=[],  # No classification
        )

    def predict_batch(self, segments, start_times):
        return [
            self.predict_segment(seg, t)
            for seg, t in zip(segments, start_times)
        ]

# __init__.py
from whombat.ml.registry import ModelRegistry
from .loader import SimpleLoader
from .inference import SimpleInference

ModelRegistry.register(
    name="simple",
    loader_class=SimpleLoader,
    engine_class=SimpleInference,
)
```

## 次のステップ

1. **カスタムフィルタの実装**: `PredictionFilter`を継承してモデル固有のフィルタを作成
2. **メタデータサポート**: 録音のメタデータを使用した高度なフィルタリング
3. **GPU最適化**: TensorFlowやPyTorchのGPU機能を活用
4. **バッチ処理の最適化**: モデル固有のバッチ処理APIを使用
5. **キャッシング戦略**: 埋め込みや中間結果のキャッシング

## 参考資料

- [ML Architecture Overview](./ML_ARCHITECTURE_OVERVIEW.md)
- [whombat.ml.base module documentation](../src/whombat/ml/base.py)
- [BirdNET implementation](../src/whombat/ml/birdnet/)
- [Prediction Filters](../src/whombat/ml/filters/)
