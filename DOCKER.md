# Whombat Docker ガイド

Dockerを使用してWhombatを起動する方法を説明します。

## 📋 目次

- [クイックスタート](#クイックスタート)
- [起動モード](#起動モード)
- [設定](#設定)
- [よくある使い方](#よくある使い方)
- [トラブルシューティング](#トラブルシューティング)

---

## 🚀 クイックスタート

### 1. 環境設定

```bash
# .envファイルを作成
cp .env.example .env

# .envファイルを編集して、少なくともオーディオディレクトリを設定
# WHOMBAT_AUDIO_DIR=/path/to/your/audio/files
nano .env
```

### 2. 起動

```bash
# シンプルモード（SQLite）で起動
./scripts/docker.sh start

# または、PostgreSQLで起動
./scripts/docker.sh start postgres
```

### 3. アクセス

ブラウザで http://localhost:5000 にアクセス

初回ログイン:
- ユーザー名: `admin`
- パスワード: `admin`

---

## 🎯 起動モード

Whombatは4つのDockerモードで起動できます:

### 1. **Simple モード (推奨)** 📦

```bash
./scripts/docker.sh start simple
# または
./scripts/docker.sh start
```

**特徴:**
- SQLiteデータベース使用
- 1つのコンテナで完結
- セットアップが最も簡単
- 個人利用や小規模プロジェクトに最適

**compose file:** `compose.simple.yaml`

### 2. **PostgreSQL モード** 🐘

```bash
./scripts/docker.sh start postgres
```

**特徴:**
- PostgreSQLデータベース使用
- より高いパフォーマンス
- 複数ユーザーでの同時利用に適している
- 本番環境やチーム利用に推奨

**compose file:** `compose.postgres.yaml`

### 3. **Development モード** 🔧

```bash
./scripts/docker.sh start dev
```

**特徴:**
- フロントエンドとバックエンドが別コンテナ
- ホットリロード有効
- Storybook、ドキュメントサーバーも起動
- 開発者向け

**compose file:** `compose.dev.yaml`

**アクセスポート:**
- Frontend: http://localhost:3000
- Backend: http://localhost:5000
- Storybook: http://localhost:6006
- Docs: http://localhost:8000

### 4. **Production モード** 🚢

```bash
./scripts/docker.sh start prod
```

**特徴:**
- PostgreSQL + Traefik (リバースプロキシ)
- 複数レプリカでのスケーリング
- ロードバランシング
- 大規模展開向け

**compose file:** `compose.prod.yaml`

---

## ⚙️ 設定

### 環境変数 (.env)

主要な設定項目:

```bash
# ネットワーク設定
WHOMBAT_DOMAIN=localhost          # アクセスするドメイン/IPアドレス
WHOMBAT_HOST=0.0.0.0             # バインドするインターフェース
WHOMBAT_PORT=5000                # バックエンドポート
WHOMBAT_FRONTEND_PORT=3000       # フロントエンドポート

# オーディオディレクトリ（必須）
WHOMBAT_AUDIO_DIR=/path/to/audio # 音声ファイルのパス

# データベース（PostgreSQLモード時）
POSTGRES_DB=whombat
POSTGRES_USER=postgres
POSTGRES_PASSWORD=whombat

# 開発モード
WHOMBAT_DEV=false                # true: 開発モード、false: 本番モード
```

詳細は `.env.example` を参照してください。

### リモートアクセス設定

リモートサーバーで起動する場合:

```bash
# .env
WHOMBAT_DOMAIN=192.168.1.100     # サーバーのIPアドレス
WHOMBAT_HOST=0.0.0.0             # すべてのインターフェースでリッスン
```

---

## 💡 よくある使い方

### コンテナの管理

```bash
# 起動
./scripts/docker.sh start [simple|postgres|dev|prod]

# 停止
./scripts/docker.sh stop

# 再起動
./scripts/docker.sh restart

# ステータス確認
./scripts/docker.sh status

# ログ表示
./scripts/docker.sh logs

# 特定のサービスのログ
./scripts/docker.sh logs whombat
```

### データの管理

```bash
# イメージの再ビルド
./scripts/docker.sh build

# コンテナとネットワークの削除（データは保持）
./scripts/docker.sh clean

# すべて削除（データベース含む）⚠️
./scripts/docker.sh clean-all
```

### データのバックアップ

```bash
# SQLiteの場合（simpleモード）
docker compose -f compose.simple.yaml cp whombat:/data/whombat.db ./backup-$(date +%Y%m%d).db

# PostgreSQLの場合
docker exec whombat-db pg_dump -U postgres whombat > backup-$(date +%Y%m%d).sql
```

### データのリストア

```bash
# SQLiteの場合
docker compose -f compose.simple.yaml cp ./backup.db whombat:/data/whombat.db
docker compose -f compose.simple.yaml restart

# PostgreSQLの場合
cat backup.sql | docker exec -i whombat-db psql -U postgres whombat
```

---

## 🔧 トラブルシューティング

### よくある問題

#### 1. ポートが既に使用されている

**エラー:** `Bind for 0.0.0.0:5000 failed: port is already allocated`

**解決策:**
```bash
# ポートを使用しているプロセスを確認
sudo lsof -i :5000

# .envでポートを変更
WHOMBAT_PORT=5001
```

#### 2. オーディオファイルが見つからない

**症状:** アプリでオーディオファイルが表示されない

**解決策:**
```bash
# 1. .envでWHOMBAT_AUDIO_DIRが正しく設定されているか確認
# 2. ディレクトリの権限を確認
ls -la /path/to/audio

# 3. コンテナ内でマウントを確認
docker exec whombat ls -la /audio
```

#### 3. データベース接続エラー（PostgreSQLモード）

**解決策:**
```bash
# データベースコンテナの状態を確認
docker compose -f compose.postgres.yaml ps

# データベースログを確認
docker compose -f compose.postgres.yaml logs db

# データベースコンテナを再起動
docker compose -f compose.postgres.yaml restart db
```

#### 4. コンテナが起動しない

**解決策:**
```bash
# ログを確認
./scripts/docker.sh logs

# イメージを再ビルド
./scripts/docker.sh build

# すべてクリーンアップして再起動
./scripts/docker.sh clean
./scripts/docker.sh start
```

### デバッグ方法

```bash
# コンテナ内に入る
docker exec -it whombat bash

# 環境変数を確認
docker exec whombat env | grep WHOMBAT

# ネットワークを確認
docker network ls
docker network inspect whombat-private

# ボリュームを確認
docker volume ls
docker volume inspect whombat-data
```

---

## 📚 関連ドキュメント

- [メインREADME](README.md)
- [設定ガイド](CONFIGURATION.md)
- [クイックスタート](QUICK_START.md)
- [開発者ガイド](back/docs/developer_guide/index.md)

---

## 🆘 サポート

問題が解決しない場合:

1. [GitHub Issues](https://github.com/mbsantiago/whombat/issues) で既存の問題を検索
2. 新しいissueを作成（ログとエラーメッセージを含める）
3. [ディスカッション](https://github.com/mbsantiago/whombat/discussions) でコミュニティに質問

---

## 🔄 次のステップ

Docker環境が動作したら:

1. **初回セットアップ**: http://localhost:5000/first でユーザーとオーディオディレクトリを設定
2. **データインポート**: [インポートガイド](back/docs/user_guide/guides/import.md) を参照
3. **アノテーション開始**: [ユーザーガイド](back/docs/user_guide/index.md) を参照
