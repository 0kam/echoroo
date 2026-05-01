# Plan: S3 Orphan Janitor — `search_reference/` cleanup (v1, 2026-04-23)

## 1. 背景 / 目的

search session の batch / rerun / delete flow で、以下 3 ケースのプロセスクラッシュにより `search_reference/{project_id}/{job_id}/` 配下に S3 orphan が残りうる:

- **Case A**: `_prepare_batch_job` で S3 put 完了後、DB commit 直前に crash → DB に session なし / S3 に残存
- **Case B**: DELETE session commit 成功 → post-commit `delete_object` loop 途中 crash → DB 消去済 / S3 残留
- **Case C**: rerun commit 成功 → stale key 差分削除途中 crash → 新 key のみ DB、旧 key が S3 に残留

既存の post-commit cleanup は `contextlib.suppress(Exception)` で best-effort。`uploads/` prefix は `cleanup_orphan_uploads` hourly task で対応済みだが、`search_reference/` は未対応。本 plan はこれを hourly Celery Beat task として追加する。

## 2. 対象 / 非対象 prefix

| Prefix | 対応 |
|---|---|
| `search_reference/{project_id}/{job_id}/` | **本 plan で対応** |
| `uploads/` | 既存 `cleanup_orphan_uploads` (apps/api/echoroo/workers/upload_tasks.py:885) |
| `recordings/` | dataset lifecycle 管理下、対象外 |

## 3. DB side source of truth

全 `search_sessions` 行から union して `known_keys: set[str]` を構築:

- **`SearchSession.reference_audio_keys`** (JSONB list of strings) — `apps/api/echoroo/models/search_session.py:124`
- **`SearchSession.species_config[*]["sources"][*]["s3_key"]`** (JSONB nested) — schema: `apps/api/echoroo/schemas/search.py:89` (`SourceConfig`)

Codex 確認済: 現 write path で s3_key を埋め込むのは `SourceConfig.s3_key` のみ。`services/search.py` / `batch.py` / `sessions.py` の create flow も同じ schema。

## 4. 検出アルゴリズム

```
async def _run_orphan_cleanup() -> JanitorResult:
    # Step 1: DB 側 known_keys + known_job_prefixes set 構築
    #         (project_id, job_id) 単位で「DB に session が存在する prefix」を記録
    known_keys, known_job_prefixes = await _collect_db_reference_keys()

    # Step 2: S3 paginated list (prefix="search_reference/")
    s3_objects = await _list_s3_objects(prefix="search_reference/")
    #   -> list[S3Object(key, last_modified, size)]

    # Step 3: age filter
    cutoff = now(UTC) - timedelta(hours=JANITOR_AGE_HOURS=24)
    aged = [o for o in s3_objects if o.last_modified < cutoff]

    # Step 4: (project_id, job_id) で group 化
    groups: dict[tuple[uuid, str], list[S3Object]] = _group_by_job_prefix(aged)
    #   parse: search_reference/{pid-uuid}/{job_id:str}/{rest}
    #   pid が UUID でない key は skip (parse 失敗 log)
    #   job_id は文字列許容 (legacy "old-job" など)

    # Step 5: orphan 判定
    #   Case A 最適化: 同 prefix 配下の全 key が known_keys に不在、かつ
    #                  (project_id, job_id) が known_job_prefixes にない
    #                  → prefix 単位で一括削除候補
    #   それ以外: individual key 単位 (Case B / C)
    prefix_deletes, individual_deletes = _classify_orphans(
        groups, known_keys, known_job_prefixes
    )

    # Step 6: 削除 (dry-run なら log のみ)
    if settings.JANITOR_DRY_RUN:
        log_dry_run(prefix_deletes, individual_deletes)
        return JanitorResult(dry_run=True, ...)

    deleted_count, failed_count = 0, 0
    for (pid, jid), objs in prefix_deletes:
        # prefix-level: delete_objects_by_prefix は内部で list + batch 削除
        n = delete_objects_by_prefix(f"search_reference/{pid}/{jid}/")
        deleted_count += n
        logger.info("janitor: prefix deleted", extra={...})

    for chunk in chunked(individual_deletes, 1000):
        resp = delete_objects_batch(chunk)  # 新 helper、Errors 返却
        deleted_count += len(chunk) - len(resp.errors)
        failed_count += len(resp.errors)
        if resp.errors:
            logger.warning("janitor: partial deletion failure", extra={"errors": resp.errors[:10]})

    return JanitorResult(deleted=deleted_count, failed=failed_count, ...)
```

### 4.1. `_collect_db_reference_keys`

- 1 query: `SELECT reference_audio_keys, species_config, celery_job_id, project_id FROM search_sessions`
- `known_keys`: `reference_audio_keys` + `species_config[*]["sources"][*]["s3_key"]` を全 row で union
- `known_job_prefixes`: `(project_id, celery_job_id)` set — Case A 最適化のため
- `species_config` nested extract は defensive (`.get()` / `or []` / 型 check)、未知形式は空返却

### 4.2. prefix parse

```python
def _parse_search_reference_key(key: str) -> tuple[UUID, str, str] | None:
    # search_reference/{project_uuid}/{job_id}/{file...}
    parts = key.split("/", 3)
    if len(parts) < 4 or parts[0] != "search_reference":
        return None
    try:
        project_id = UUID(parts[1])
    except ValueError:
        return None  # legacy / malformed prefix -> skip
    return (project_id, parts[2], parts[3])
```

**決定事項 (Codex指摘反映)**:
- project_id のみ UUID 検証
- job_id は文字列許容 (`tests/contract/test_search_writes.py:316` で `old-job` fixture 存在)
- parse 失敗 key は skip + debug log (誤削除回避)

### 4.3. age filter

- default 24h (env `JANITOR_AGE_HOURS` で override 可)
- Codex 確認済: `run_batch_search` は `time_limit=300` / `soft_time_limit=270` (apps/api/echoroo/workers/search_tasks.py:33)、明示 retry 設定なし → 24h は十分保守的

## 5. 新規ファイル / 変更

### 5.1. `apps/api/echoroo/core/s3.py`

既存: `get_s3_client`, `delete_object`, `delete_objects_by_prefix`, `upload_*`, `list_*`。

**追加**:

```python
def list_objects_paginated(prefix: str, client: Any = None) -> Iterator[S3ObjectMeta]:
    """Yield S3 objects under prefix, using ContinuationToken for pagination."""
    # boto3 list_objects_v2 を ContinuationToken で反復、各 Contents を S3ObjectMeta 化
    # S3ObjectMeta: NamedTuple(key: str, last_modified: datetime, size: int)

def delete_objects_batch(keys: list[str], client: Any = None) -> BatchDeleteResult:
    """Delete up to 1000 keys via s3 delete_objects API.

    Returns:
        BatchDeleteResult(deleted: list[str], errors: list[DeletionError])
    """
    # boto3 delete_objects({"Objects": [{"Key": k} for k in keys], "Quiet": False})
    # response["Errors"] を DeletionError に map
```

### 5.2. `apps/api/echoroo/core/settings.py`

```python
# Janitor
JANITOR_DRY_RUN: bool = True  # default True, flip to False after prod monitoring
JANITOR_AGE_HOURS: int = 24
```

### 5.3. `apps/api/echoroo/workers/search_tasks.py`

既存 `run_batch_search` の下に追加:

```python
@app.task(name="echoroo.workers.search_tasks.cleanup_orphan_search_reference")
def cleanup_orphan_search_reference() -> dict[str, Any]:
    """Remove orphan S3 objects under search_reference/ prefix.

    Detects keys that:
      - match search_reference/{valid_project_uuid}/{job_id}/{file}
      - are older than JANITOR_AGE_HOURS (default 24h)
      - are not referenced by any SearchSession (reference_audio_keys or
        species_config[*].sources[*].s3_key)

    For job prefixes where no key is DB-referenced AND celery_job_id is
    unknown, deletes the entire prefix in one batch (Case A optimization).
    Otherwise deletes individual orphan keys via s3:DeleteObjects (chunked 1000).

    Honors JANITOR_DRY_RUN=true to log-only without deleting.
    """
    logger.info("Starting orphan search_reference cleanup")
    return asyncio.run(_run_orphan_search_reference_cleanup())
```

### 5.4. `apps/api/echoroo/workers/celery_app.py`

```python
app.conf.beat_schedule = {
    "cleanup-orphan-uploads": {
        "task": "echoroo.workers.upload_tasks.cleanup_orphan_uploads",
        "schedule": crontab(minute=0),  # hourly at :00
    },
    "cleanup-orphan-search-reference": {  # NEW
        "task": "echoroo.workers.search_tasks.cleanup_orphan_search_reference",
        "schedule": crontab(minute=30),  # hourly at :30 (offset from uploads)
    },
    "fetch-japanese-vernacular-names-weekly": {
        ...
    },
}
```

### 5.5. `apps/api/tests/workers/test_search_janitor.py` (新規)

LocalStack は integration 扱いで container 内でしか動かないので **unit test は moto / fake S3 client** で書く。`boto3.client("s3")` を monkeypatch で差し替え、`async_sessionmaker` からの DB は既存 conftest を流用。

**テストケース**:

1. **T1 — dry-run blocks deletion**: `JANITOR_DRY_RUN=true` で orphan 検出しても delete が呼ばれない。return の `dry_run=True` / `candidates=N`
2. **T2 — age filter**: 23h ago の key は skip、25h ago は対象
3. **T3 — DB referenced key preserved**: `reference_audio_keys` / `species_config[*].sources[*].s3_key` に含まれる key は削除されない
4. **T4 — Case A prefix bulk delete**: DB に session がない job prefix 配下の全 key を `delete_objects_by_prefix` で削除する（individual delete 呼ばれない）
5. **T5 — Case B/C individual delete**: 同 prefix 内で一部 key だけ orphan の場合、`delete_objects_batch` 個別削除
6. **T6 — legacy job_id ("old-job") tolerated**: non-UUID job_id でも parse 成功、age + DB check が動く
7. **T7 — invalid project_id skipped**: project_id UUID parse 失敗 key は touched されない (skip log のみ)
8. **T8 — partial failure logged**: `delete_objects_batch` の `errors` 返却時、`failed_count` が return に反映 + warning log に error key が載る
9. **T9 — species_config nested malformed**: `species_config` が `None` / list でない / sources key 欠如 / s3_key 欠如 でも落ちない (defensive extract)

## 6. Gate 定義

### Gate 1: 静的検証
- `docker exec echoroo-backend uv run mypy apps/api/echoroo/workers/search_tasks.py apps/api/echoroo/core/s3.py apps/api/echoroo/core/settings.py`
- `docker exec echoroo-backend uv run ruff check apps/api/echoroo/`

### Gate 2: 自動テスト
- `docker exec echoroo-backend uv run pytest apps/api/tests/workers/test_search_janitor.py -v` → 9/9 pass
- 既存 smoke 全通過: `docker exec echoroo-backend uv run pytest apps/api/tests/contract/` → previous green count 維持

### Gate 3: dev 環境動作確認 (LocalStack)
1. Celery worker 再起動: `./scripts/docker.sh dev restart`
2. `docker exec echoroo-backend uv run python -c "from echoroo.workers.search_tasks import cleanup_orphan_search_reference; print(cleanup_orphan_search_reference.delay().get(timeout=30))"` — 実 cron 待たず手動発火
3. **dry-run 検証 (default)**:
   - `JANITOR_DRY_RUN=true` で意図的な orphan を LocalStack に put (awscli or boto3 script)
   - 手動発火 → `dry_run=True, candidates=N` が return
   - worker log に `janitor: prefix deleted (DRY RUN)` 等が記録される
   - LocalStack 上 key は残存していることを `aws s3 ls` で確認
4. **非 dry-run 検証**:
   - env `JANITOR_DRY_RUN=false` + worker restart
   - 意図的 orphan を 2 通り (job prefix 全 orphan / 一部 orphan) 作成
   - 手動発火 → return に `deleted=N, failed=0`
   - LocalStack 上 orphan key 消失を `aws s3 ls` で確認
   - 有効な session の `reference_audio_keys` が**削除されていない**ことを確認 (UI で既存 session を開いて reference audio が再生できる)
5. **部分失敗検証** (optional): mock で Errors を強制注入して warning log を確認 — unit test T8 でカバー済なら省略可
6. **console error 0**: Playwright で `/en/projects/{id}/search` を開いて既存 session の詳細画面が正常動作 + console error 0

## 7. 実装順序

```
1. plan.md 保存 (このファイル)                           (main)
2. core/s3.py helper 追加                                 (SSA: backend-developer, sequential)
3. core/settings.py に JANITOR_DRY_RUN                   (SSA: backend-developer, parallel-safe w/ step 2)
4. workers/search_tasks.py + celery_app.py beat 登録     (SSA: backend-developer, after 2+3)
5. tests/workers/test_search_janitor.py (9 tests)         (SSA: test-automator, after 4)
6. Gate 1 + Gate 2 実行                                    (SSA: test-automator)
7. Gate 3 (main 手動、Playwright MCP + bash)              (main)
8. commit (3-5 commits 程度): helper / settings / task / beat / tests)
9. memory 更新 (follow-up 全消化)                          (main)
```

**並列化方針**: Step 2 と 3 は独立ファイルだが、CLAUDE.md の「並列 SSA は git worktree isolation なしでは危険」を踏まえ **sequential default**。Step 5 は step 4 完了後に起動。

## 8. リスク / 非目標

### 最大リスク: DB ↔ S3 race
- DB read と S3 list の間で新規 batch が進行すると、list に載った新 key が DB に未反映 → orphan 誤判定
- **mitigation**: age filter 24h で吸収 (実 batch は 5 min 以内完了)
- 追加 safety net: DB read を **S3 list の後** に行う (新規 session が S3 put → DB commit の順で動くため、list-then-DB だと偽陽性が出やすい)。**S3 list → DB read → diff** の順固定

### 既知の触らない領域
- `uploads/` / `recordings/` / `exports/` 他 prefix — 対象外
- 既存 post-commit cleanup の挙動 — 変更せず
- rerun / batch の S3+DB ordering — 直近 commit で修正済、今回は janitor のみ追加

### 非目標
- metric 収集基盤 (Prometheus 等) — log ベースで audit、将来の別 plan
- retention policy (古いが DB referenced な key の削除) — 本 janitor の対象外
- schema migration — DB 変更なし

## 9. Codex review 判定 (2026-04-23)

**Conditional Go**。以下 5 点反映済:

1. ✅ species_config 抽出前提 OK (`SourceConfig.s3_key` のみ)
2. ✅ age filter 24h 妥当 (batch task は 5 min 以内)
3. ✅ prefix parse: project_id のみ UUID 検証、job_id は文字列許容 (legacy `old-job` 互換)
4. ✅ 削除失敗 metrics 強化: `delete_objects` Errors を `failed_count` と warning log に記録
5. ✅ dry-run default = True (初回 prod 監視期間)、Case A prefix 一括削除最適化

## 10. 完了定義

- Gate 1 / Gate 2 pass
- Gate 3 で dry-run → 非 dry-run の両方動作確認、既存 session 破壊なし確認
- `project_refactor_handoff_2026-04-18.md` の「後続 janitor task」follow-up を解消済に更新
- commit 3-5 本、PR 不要 (main 直 push なし、コミットのみ)
