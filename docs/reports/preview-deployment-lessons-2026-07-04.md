# 所内プレビュー運用で得た知見まとめ（2026-07-04）

所内プレビュー機（ninjin: RTX 5080 / Blackwell, LAN 158.210.76.44, compose.dev.yaml ベース）を
開発マシンと別に立てて運用した約1ヶ月で踏んだ問題と対処の記録。
開発マシン側はコード整理が進んでおり git マージは想定しない。
**コードではなく「何が起きて・なぜで・どう塞いだか」を移植するためのドキュメント**。

対応コミット: #167 (58fa8e23), #168 (e15e0f01), #161 (f8e96eb4),
ブランチ `claude/dazzling-tu-409ed7`（restart ポリシー + watchdog、2026-07-04 時点未マージ）。

---

## 1. 【最重大】LocalStack 再起動で KMS 鍵が消え、全ユーザーが 2FA ロックアウト

**症状**: ホスト再起動後、全ユーザーの TOTP 検証が `IncorrectKeyException`（KMS Decrypt 失敗）。
PII ハッシュ・監査チェーン MAC も過去データと不一致になる。

**原因**: LocalStack **Community は状態を永続化しない**。`PERSISTENCE=1` は Pro 専用機能で、
Community では**エラーも警告も出さず黙って無視される**。素の `kms create-key` は起動のたびに
ランダムな鍵素材を新規生成するため、コンテナ再起動 = 旧鍵で包んだ全暗号文が復号不能。

**対処**（`scripts/init-localstack.sh`、冪等）:
- `create-key --origin EXTERNAL` + `_custom_id_` タグで**固定 UUID** の鍵を作成
  （LocalStack の制約: 固定 ID は UUID 形式必須。対称暗号文には key id が埋め込まれるため固定必須）
- AWS の外部鍵素材インポートフロー（`get-parameters-for-import` → RSA-OAEP-SHA256 で素材をラップ →
  `import-key-material`、無期限）で**固定の鍵素材**を毎起動インポート
- 同じ素材 + 同じ key id なら、再起動前に作った暗号文/MAC が再起動後も検証可能
- ENCRYPT_DECRYPT（TOTP DEK）と GENERATE_VERIFY_MAC（HMAC 3種）の両方で、
  実コンテナ再起動をまたぐ round-trip を community-archive 4.14.x で検証済み
- 素材は dev 専用のフェイク 32 バイト（リポジトリに平文で置いてよいもの）。env で上書き可。
  本番は実 AWS KMS（素材エクスポート不能）なので無関係

**復旧手段**: ロックアウトされたユーザーは `reset_user_two_factor`
（`two_factor_reset_service`）で救済。

**開発マシンへの示唆**: LocalStack を使う限り**同種の仕込みが必須**。init スクリプトの
実装が別物でも「固定 UUID + 固定素材のインポート」という設計だけ持っていけば良い。
alias 名は env（`AWS_KMS_CMK_*_ALIAS`）で環境ごとに変えられる設計にしておく。

## 2. LocalStack のイメージは pin 必須（>=2026.03.0 は起動しない）

LocalStack >= 2026.03.0 は auth token 必須になり、無いと **exit 55
("License activation failed")** で起動すらしない。`:latest` や `:3` は踏む。

**対処**: `localstack/localstack:community-archive@sha256:6b6172cf…`
（token 不要の最終 Community ビルド、4.14.x 系、2026-03-18）に digest 固定。
compose だけでなく **CI（ci.yml / e2e.yml）も同じ pin に揃える**こと。

## 3. フレッシュインストールで毎回踏む小物（#167）

新マシンへのクリーンデプロイで全部踏んだもの:

- **redis TLS 鍵の権限**: `gen-redis-dev-cert.sh` が 600 で生成すると、非 root で動く
  redis コンテナが `:ro` bind mount 越しに redis.key を読めない → **644 で生成**
  （dev 専用の自己署名素材なので許容）
- **paraglide の named-volume マウントポイント**: `apps/web/src/lib/paraglide/.gitkeep` を
  track しないと fresh clone にディレクトリが無く、`:ro` の src bind mount では作れない
- **project.inlang は `:rw` でマウント**: inlang がプラグインキャッシュを書くため
  `:ro` だと EROFS。`project.inlang/cache/plugins/.gitkeep` も track
- **Dockerfile.dev で `/app/src/lib/paraglide` を node 所有で作成**: fresh な named volume が
  node 所有を引き継ぎ、vite がランタイムを自動生成できるようにする

## 4. Blackwell GPU では TF が使えず、CPU フォールバックがホストごと落とす（#168）

**症状**: BirdNET / Perch（ともに TensorFlow）が RTX 5080（sm_120）で、GPU 列挙は成功するのに
カーネル起動でクラッシュ。CPU に切り替えると推論が RAM を食い尽くし**ホストが突然リブート**
（プレビュー機で実際に複数回発生。journalctl 上は OOM-kill ではなく abrupt-halt に見えるので
原因特定が紛らわしい）。

**対処**（env 駆動、デフォルトは従来 GPU 動作のまま）:
- `ECHOROO_ML_USE_GPU=false` → **TF import 前に** `CUDA_VISIBLE_DEVICES=-1` を設定
- CPU モード時はスレッドキャップ（OMP/TF/OPENBLAS/MKL、`ECHOROO_ML_CPU_NUM_THREADS=8`）と
  Perch warmup 縮小（`ECHOROO_ML_CPU_WARMUP_BATCHES=1`、XLA-CPU コンパイル時の RAM スパイク対策）
- worker / worker-cpu に `mem_limit=${ECHOROO_WORKER_MEM_LIMIT:-0}`（ホスト道連れ防止の上限）

**プレビュー機の実運用値**: `ECHOROO_ML_USE_GPU=false`, `ECHOROO_WORKER_MEM_LIMIT=24g`
（ホスト RAM の約4割）, `ECHOROO_ML_GPU_BATCH_SIZE=4`

**実装上の罠**: この env 設定は **numpy / TF を import する前**に実行しないと無意味
（BLAS がスレッド設定を初期化時に読むため）。celery_app.py の先頭で、numpy を引き込む
一切の import より前に呼ぶ。`echoroo.ml` の `__init__` は BirdNET/Perch → numpy を連鎖
import するので、そこから import してはいけない（workers 側の空 `__init__` 経由にする）。

## 5. Celery ワーカーのサイレント停止（2026-07-04 対処、未マージ分）

**症状**: アップロードした音源がいつまでもインポートされない。エラーは一切出ない。
データセットは `pending` のまま（これはデフォルト状態であり原因ではない）。

**原因**: 6/21 のホスト再起動時、`restart: unless-stopped` が付いていた
backend / frontend / db / redis は自動復帰したが、**worker / worker-cpu / beat / localstack には
restart ポリシーが無く**、14日間停止したままだった。backend はタスクを enqueue するだけなので
表面上は全 API が正常、フロントは 2 秒ポーリングを永遠に続ける＝無限スピナー。

**対処**（3層、ブランチ `claude/dazzling-tu-409ed7`）:
1. compose.dev.yaml の worker / worker-cpu / beat / localstack に `restart: unless-stopped`
2. Docker デーモンのブート時起動を確認（`systemctl is-enabled docker`）
3. cron watchdog（`scripts/worker-watchdog.sh`、5分間隔）: 3コンテナのどれかが非稼働なら
   `docker compose up -d --no-recreate` で起こす（手動 stop の戻し忘れ対策）

**celery ping ベースの healthcheck + autoheal は意図的に不採用**: ワーカーは `--pool=solo` で
動いており、長時間 CPU 推論中は ping に応答できない。ping 死活監視を入れると
処理中のタスクごと殺される。

**付随して分かった罠**:
- upload session が VALIDATED / VALIDATING / IMPORTING で宙吊りになると、
  active-session チェック（services/upload.py）により**新規アップロードが 409 で全部弾かれる**。
  ワーカー復旧後は宙吊りセッションの import を手動 dispatch して完了させる必要がある
- フロントのアップロード UI はステータスが進まない場合の停滞検知が無い（改善余地）

## 6. その他ハマりポイント（デバッグ時の思い込み防止）

- **dataset の `pending`** は「作成直後・未インポート」のデフォルト状態。
  インポート完了で自動的に `completed` になる。手動変更の UI/権限は存在しない
- **2FA リセット後の 72h クールダウン**はプロジェクト削除・メンバー変更・API キー・
  export / download 系のみ制限し、**アップロードには効かない**
  （middleware/two_factor_enforcement.py の `COOLDOWN_RESTRICTED_PATTERNS`）
- データセットの Public / Private はアップロード処理に無関係

## 開発マシンへの反映チェックリスト

- [ ] LocalStack: 固定 UUID + 固定鍵素材インポート方式の init になっているか（§1）
- [ ] LocalStack: イメージが community-archive に digest 固定されているか（compose + CI）（§2）
- [ ] fresh-install 4点セット（redis 鍵 perms / paraglide .gitkeep / inlang :rw / Dockerfile.dev）（§3）
- [ ] ML device env 一式が存在し、TF/numpy import 前に適用されるか（§4）
- [ ] GPU が使えないマシンでは `.env` に `ECHOROO_ML_USE_GPU=false` + `ECHOROO_WORKER_MEM_LIMIT`（§4）
- [ ] celery 系コンテナ全部に restart ポリシー + watchdog（§5）
- [ ] 2FA ロックアウト時の復旧手順（`reset_user_two_factor`）を運用側が知っているか（§1）
