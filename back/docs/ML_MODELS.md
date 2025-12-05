# ML Models Setup

Echorooで使用するMLモデルのセットアップ方法です。

**推奨: Pythonパッケージ経由でインストール（モデル自動ダウンロード）**

---

## クイックスタート

```bash
# BirdNET (推奨)
pip install birdnet

# または、ML extras経由でインストール
pip install whombat[ml]
```

---

## BirdNET V2.4

BirdNETは、Echorooで使用される主要な音響解析モデルです。高精度な鳥類分類と汎用的な音響埋め込みの両方をサポートしています。

### スペック
- 入力: 3秒 @ 48kHz (144,000 samples)
- 埋め込み: 1024次元
- 出力: 6,522種の鳥類分類
- パッケージバージョン: 0.2.10+
- NumPy互換性: numpy<2.0 (soundeventと互換)

### インストール

```bash
# CPU版
pip install birdnet

# GPU版 (NVIDIA CUDA必要、Linux x86_64のみ)
pip install birdnet[and-cuda]

# エッジデバイス (Raspberry Pi等、Windows不可)
pip install birdnet[litert]
```

### 使用例 (birdnet v0.2.x API)

```python
import birdnet

# モデルをロード (初回実行時に自動ダウンロード)
model = birdnet.load('acoustic', '2.4', 'tf')

print(f"Sample rate: {model.get_sample_rate()}")        # 48000
print(f"Embedding dim: {model.get_embeddings_dim()}")   # 1024
print(f"Number of species: {model.n_species}")          # 6522

# 埋め込みを取得
embeddings_result = model.encode("/path/to/audio.wav")
embeddings = embeddings_result.embeddings  # shape: (n_files, n_segments, 1024)
print(f"Embeddings shape: {embeddings.shape}")

# 種の予測を取得
predictions_result = model.predict("/path/to/audio.wav", top_k=5)
species_probs = predictions_result.species_probs  # shape: (n_files, n_segments, n_species)
species_list = model.species_list  # List of species names
```

### Whombatでの使用

```python
from whombat.ml.birdnet import BirdNETLoader, BirdNETInference

# ローダーを初期化してモデルをロード
loader = BirdNETLoader()
loader.load()

# 推論エンジンを作成
inference = BirdNETInference(loader, confidence_threshold=0.5, top_k=10)

# ファイル全体を解析
results = inference.predict_file("/path/to/audio.wav")
for result in results:
    print(f"{result.start_time}s - {result.end_time}s")
    print(f"  Embedding shape: {result.embedding.shape}")
    if result.has_detection:
        print(f"  Top prediction: {result.top_prediction}")

# ファイルから埋め込みのみを取得
embeddings = inference.get_embeddings_from_file("/path/to/audio.wav")
print(f"Embeddings shape: {embeddings.shape}")  # (n_segments, 1024)
```

### 機能

#### 音響埋め込み
- 1024次元の高品質な音響特徴ベクトル
- 類似音検索に最適
- 音響イベントのクラスタリングに使用可能

#### 種分類
- 6,522種の鳥類を識別
- 信頼度スコア付き予測
- Top-K予測のサポート

#### GPU加速
- CUDA対応GPUでの高速推論
- バッチ処理のサポート
- メモリ効率的な推論

### 参考リンク
- [birdnet PyPI](https://pypi.org/project/birdnet/)
- [birdnet GitHub](https://github.com/birdnet-team/birdnet/)
- [BirdNET-Analyzer Documentation](https://birdnet-team.github.io/BirdNET-Analyzer/)

---

## 以前のPerchサポートについて

**注意**: Whombat v0.8.6以降、perch-hopliteパッケージのサポートは終了しました。

### 移行理由

1. **依存関係の競合**: perch-hopliteはnumpy>=2.0を必要としますが、soundevent（Whombatのコア依存関係）はnumpy<2.0を必要とします
2. **統一されたAPI**: BirdNETは埋め込みと分類の両方を単一のAPIで提供します
3. **GPU対応**: BirdNETはCUDAを通じてGPU加速をサポートします
4. **メンテナンス性**: 単一のMLバックエンドにより、コードベースがシンプルになります

### 移行ガイド

既存のPerchベースの実装からBirdNETへの移行:

#### コード変更

**Before (Perch)**:
```python
from whombat.ml.perch import PerchLoader
loader = PerchLoader()
loader.load()
model = loader.get_model()
```

**After (BirdNET)**:
```python
from whombat.ml.birdnet import BirdNETLoader
loader = BirdNETLoader()
loader.load()
model = loader.get_model()
```

#### 埋め込み次元の変更

- Perch: 1536次元
- BirdNET: 1024次元

既存の埋め込みデータベースは、新しいBirdNETベースの埋め込みで再生成する必要があります。

#### 互換性に関する注意

BirdNETの埋め込みは、Perchの埋め込みと直接互換性はありません。類似検索などの機能を使用する場合は、既存の音声データを再処理してBirdNET埋め込みを生成する必要があります。

---

## 動作確認

```python
# BirdNET
import birdnet
model = birdnet.load('acoustic', '2.4', 'tf')
print(f"BirdNET loaded: {model.n_species} species")

# Whombat ML API
from whombat.ml.birdnet import BirdNETLoader, BirdNETInference
loader = BirdNETLoader()
loader.load()
print(f"Loader: {loader}")
print(f"Model specification: {loader.specification}")
```

---

## トラブルシューティング

### Import Error: birdnet not found

```bash
pip install birdnet
```

### GPU not detected

CUDA対応版をインストール:
```bash
pip install birdnet[and-cuda]
```

CUDA環境を確認:
```python
import tensorflow as tf
print(f"GPU available: {len(tf.config.list_physical_devices('GPU')) > 0}")
```

### メモリ不足エラー

- バッチサイズを減らす
- より小さなオーディオチャンクで処理
- CPUモードを使用（GPUメモリが不足している場合）

---

## ライセンス

- **BirdNET**: CC BY-NC-SA 4.0 (非商用)
