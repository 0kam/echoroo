# ML Architecture Overview

## プロジェクト概要

EchorooのML推論システムは、複数の音響解析モデル（BirdNET V2.4、Perch V2など）を統合し、音声データから種の識別と音響埋め込みを抽出するための拡張可能なアーキテクチャを提供します。

### 主な改善点

- **モデル非依存設計**: 抽象化により複数のMLモデルをサポート
- **スレッドセーフな遅延読み込み**: モデルは必要になるまでロードされない
- **プラガブルフィルタリング**: 予測結果に対して柔軟なフィルタリングを適用可能
- **統一されたインターフェース**: すべてのモデルが同じAPIを使用
- **NumPy依存関係の解決**: soundevent (numpy<2.0) との互換性を維持

## アーキテクチャコンポーネント

```
┌─────────────────────────────────────────────────────────────┐
│                     ML Architecture                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │ ModelLoader  │      │  Inference   │                    │
│  │    (ABC)     │──────│   Engine     │                    │
│  └──────────────┘      │    (ABC)     │                    │
│    │          │        └──────────────┘                    │
│    │          │              │            │                 │
│ ┌──┴──┐   ┌──┴──┐     ┌──┴──┐    ┌─┴──┐               │
│ │Bird-│   │Perch│     │Bird-│    │Perch               │
│ │NET  │   │ V2  │     │NET  │    │ V2                 │
│ │LD   │   │ LD  │     │Inf  │    │Inf                │
│ └─────┘   └─────┘     └─────┘    └────┘               │
│                                                              │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │  Prediction  │      │   Filter     │                    │
│  │   Filter     │◄─────│   Context    │                    │
│  │    (ABC)     │      └──────────────┘                    │
│  └──────────────┘                                           │
│         │                                                   │
│  ┌──────▼──────┐      ┌──────────────┐                    │
│  │  Occurrence │      │ PassThrough  │                    │
│  │   Filter    │      │   Filter     │                    │
│  └─────────────┘      └──────────────┘                    │
│                                                              │
│  ┌──────────────────────────────────────┐                  │
│  │         ModelRegistry                │                  │
│  │  - register(name, loader, engine)    │                  │
│  │  - get_loader_class(name)            │                  │
│  │  - get_engine_class(name)            │                  │
│  └──────────────────────────────────────┘                  │
│                                                              │
│  ┌──────────────────────────────────────┐                  │
│  │       InferenceWorker                │                  │
│  │  - Background job processing         │                  │
│  │  - Uses registry for model loading   │                  │
│  └──────────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

### 1. ModelLoader (基底クラス)

モデルのロードとライフサイクル管理を担当。

**主な機能:**
- スレッドセーフな遅延読み込み（double-checked locking）
- モデルのロード/アンロード
- モデル仕様の提供

**実装例:**
```python
from echoroo.ml.base import ModelLoader, ModelSpecification

class MyModelLoader(ModelLoader):
    @property
    def specification(self) -> ModelSpecification:
        return ModelSpecification(
            name="my_model",
            version="1.0",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=512,
            supports_classification=True,
            species_list=["species_a", "species_b"],
        )

    def _load_model(self):
        # Import model library
        import my_model_lib
        # Load and return model
        return my_model_lib.load()
```

### 2. InferenceEngine (基底クラス)

モデルを使用した推論を実行。

**主な機能:**
- 単一セグメントの推論
- バッチ推論
- ファイル全体の処理（AudioPreprocessorを使用）

**実装例:**
```python
from echoroo.ml.base import InferenceEngine, InferenceResult
import numpy as np

class MyInferenceEngine(InferenceEngine):
    def predict_segment(
        self,
        audio: NDArray[np.float32],
        start_time: float
    ) -> InferenceResult:
        # Run model inference
        embedding = self._model.get_embedding(audio)
        predictions = self._model.predict(audio)

        return InferenceResult(
            start_time=start_time,
            end_time=start_time + self.specification.segment_duration,
            embedding=embedding,
            predictions=predictions,  # [(label, confidence), ...]
        )

    def predict_batch(
        self,
        segments: list[NDArray[np.float32]],
        start_times: list[float],
    ) -> list[InferenceResult]:
        # Batch processing for efficiency
        return [
            self.predict_segment(seg, t)
            for seg, t in zip(segments, start_times)
        ]
```

### 3. PredictionFilter (基底クラス)

予測結果のフィルタリングを提供。

**主な機能:**
- 位置/時間ベースのフィルタリング
- 種の出現確率に基づくフィルタリング
- モデル非依存の設計

**実装例:**
```python
from echoroo.ml.filters import PredictionFilter, FilterContext

# Create filter context from recording metadata
context = FilterContext(
    latitude=35.6762,
    longitude=139.6503,
    date=date(2024, 5, 15),
)

# Use occurrence filter
filter = EBirdOccurrenceFilter("/path/to/species_presence.npz")
predictions = [("species_a", 0.95), ("species_b", 0.82)]
filtered = filter.filter_predictions(predictions, context)
```

### 4. ModelRegistry (シングルトン)

モデルの動的な登録と検出を提供。

**主な機能:**
- モデルの登録
- 名前によるモデルコンポーネントの取得
- 利用可能なモデルのリスト化

**使用例:**
```python
from echoroo.ml.registry import ModelRegistry

# Register model (typically in model's __init__.py)
ModelRegistry.register(
    name="birdnet",
    loader_class=BirdNETLoader,
    engine_class=BirdNETInference,
    filter_class=BirdNETMetadataFilter,
    description="BirdNET V2.4 bird species identification",
)

# Get model components by name
loader_cls = ModelRegistry.get_loader_class("birdnet")
engine_cls = ModelRegistry.get_engine_class("birdnet")
```

### 5. InferenceWorker (オーケストレーター)

バックグラウンドでMLジョブを処理。

**主な機能:**
- データベースからジョブをポーリング
- モデルのロードと推論の実行
- 結果（埋め込み、予測）の保存
- フィルタリングの適用

## データフロー

```
Audio File
    │
    ▼
┌─────────────────┐
│ AudioPreprocessor│
│ - Load audio     │
│ - Resample       │
│ - Segment        │
│ - Normalize      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ InferenceEngine │
│ - predict_file() │
│ - predict_batch()│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ InferenceResult │
│ - embedding     │
│ - predictions   │
│ - start_time    │
│ - end_time      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ PredictionFilter│
│ - Apply context │
│ - Filter species│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Database      │
│ - ClipEmbedding │
│ - ClipPrediction│
└─────────────────┘
```

## デザインパターン

### 1. Abstract Base Class (ABC) Pattern

すべてのコアコンポーネント（ModelLoader, InferenceEngine, PredictionFilter）は抽象基底クラスとして実装され、一貫したインターフェースを提供。

**利点:**
- 型安全性
- 実装の強制
- ドキュメント化された契約

### 2. Factory Pattern (Registry)

ModelRegistryはファクトリパターンを使用し、名前によるモデルコンポーネントの動的インスタンス化を可能にする。

**利点:**
- 実行時のモデル選択
- 新しいモデルの簡単な追加
- コアコードの変更不要

### 3. Lazy Loading Pattern

モデルは初めて使用されるときにのみロードされる（thread-safe double-checked locking）。

**利点:**
- 起動時間の短縮
- メモリ使用量の削減
- オンデマンドリソース割り当て

### 4. Strategy Pattern (Filters)

異なるフィルタリング戦略（PassThrough, Occurrence）を交換可能にする。

**利点:**
- 実行時のフィルタリング動作の変更
- テストの容易化
- 拡張性

## テクノロジースタック

### BirdNET & Perch統合

**パッケージ:** `birdnet>=0.2.10`

**サポートモデル:**
- **BirdNET V2.4**: 鳥類の種識別と音響埋め込み
  - 1024次元埋め込み
  - 6,522種の分類
  - 最適化された推論パイプライン

- **Perch V2**: Google Researchの汎用音響埋め込みモデル
  - 1024次元埋め込み
  - より一般的な音響特性を捉える
  - BirdNETと同じAPIで利用可能

**主な特徴:**
- TensorFlowベース（ProtoBuf形式のモデル）
- GPU加速サポート（CUDA）
- 自動モデルダウンロード
- 統一されたAPI

**使用例:**
```python
import birdnet

# Load BirdNET V2.4
model = birdnet.load('acoustic', '2.4', 'tf')

# Load Perch V2
model = birdnet.load('perch', 'v2', 'tf')

# 両方のモデルで同じAPIを使用
result = model.encode("/path/to/audio.wav")
embeddings = result.embeddings  # (n_files, n_segments, 1024)

result = model.predict("/path/to/audio.wav", top_k=5)
species_probs = result.species_probs
```

### NumPy互換性

**要件:** `numpy<2.0`

**理由:**
- soundeventパッケージとの互換性維持
- birdnetパッケージとの互換性確保

**対応:**
```toml
# pyproject.toml
dependencies = [
    "numpy>=1.24,<2.0",
    "birdnet>=0.2.10",
]
```

## 主要な設計決定

### 1. モデル非依存アーキテクチャ

**決定:** 抽象基底クラスを使用して、すべてのモデルに統一されたインターフェースを提供

**理由:**
- 新しいモデルの追加が容易
- コアコードの変更なしにモデルを切り替え可能
- テストの容易化

**トレードオフ:**
- 初期開発の複雑さが増加
- すべてのモデルが共通のパターンに従う必要がある

### 2. 統一されたbirdnetライブラリへの移行

**決定:** Perchのサポートをperch-hopliteからbirdnetライブラリに統合

**理由:**
- NumPy依存関係の競合を解決（birdnetはnumpy<2.0を使用）
- BirdNETとPerchの両方を同じライブラリで管理可能
- GPU加速サポート（TensorFlow + ProtoBuf）
- メンテナンス負荷の軽減
- eBirdの地理的・季節的なメタデータフィルタリングが利用可能

**実装詳細:**
- BirdNET V2.4: `birdnet.load("acoustic", "2.4", "tf")`
- Perch V2: `birdnet.load("perch", "v2", "tf")`
- 両方のモデルで統一されたAPIを使用
- 自動モデルダウンロード

**トレードオフ:**
- 既存のperch-hopliteからの移行が必要
- 既存の埋め込みは互換性がない（1536次元→1024次元）

### 3. フィルタリングの分離

**決定:** フィルタリングロジックを推論から分離

**理由:**
- どのモデルでもどのフィルタでも使用可能
- 異なるフィルタリング戦略の実装が容易
- テストの容易化

**トレードオフ:**
- より多くのクラスとインターフェース
- フィルタコンテキストの伝播が必要

### 4. レジストリパターン

**決定:** モデルを自己登録する中央レジストリを使用

**理由:**
- モデルの動的検出
- ワーカーコードの簡素化
- プラグインアーキテクチャへの道

**トレードオフ:**
- グローバルステートの導入
- モジュールのインポート順序への依存

## パフォーマンス特性

### BirdNET推論

**CPU:**
- 3秒セグメント: ~200-300ms
- 1時間の音声: ~5-10分

**GPU (CUDA):**
- 3秒セグメント: ~50-100ms
- 1時間の音声: ~1-2分

### メモリ使用量

**モデルロード時:**
- BirdNET: ~500MB

**推論時（バッチサイズ32）:**
- ピークメモリ: ~1-2GB

**埋め込み保存:**
- 1時間の音声（3秒セグメント）: ~5MB
  - 1200セグメント × 1024次元 × 4バイト ≈ 5MB

### スケーラビリティ

**並列処理:**
- 複数のワーカーを実行可能（それぞれ独自のモデルインスタンス）
- データベース操作がボトルネックになる可能性

**推奨事項:**
- CPUワーカー: 1-2ワーカー/コア
- GPUワーカー: 1-2ワーカー/GPU
- バッチサイズの調整でメモリとスループットのバランスを取る

## 今後の展開

### 短期

1. **追加モデルのサポート**
   - カスタムモデルのサポート
   - 他の音響解析モデル（YAMNet、PANNsなど）のサポート

2. **パフォーマンス最適化**
   - バッチ処理の改善
   - モデルキャッシングの強化
   - GPU利用の最適化

### 長期

1. **プラグインシステム**
   - サードパーティモデルの簡単な統合
   - モデルマーケットプレイス

2. **分散推論**
   - Celeryまたは類似のタスクキュー
   - マルチノードクラスター

3. **オンライン推論**
   - リアルタイムストリーミング
   - WebSocketベースのAPI

## 参考資料

- **BirdNET**: https://github.com/birdnet-team/birdnet/
- **eBird Status and Trends**: https://ebird.org/science/status-and-trends
- **H3 Geospatial Indexing**: https://h3geo.org/

## 関連ドキュメント

- [新しいモデルの追加方法](./ADDING_NEW_MODELS.md)
- [ML Models Setup](./ML_MODELS.md)
