# spec/011 Zero-email Deployment — Session Handoff (2026-05-21)

## Mode: フルオート実装

192 タスクを **フルオート** で実装する。私の指示を逐一仰がず、決定済み事項に沿って SSA 委任 + Codex review + 段階的 commit/PR で進める。完了通知のみ報告する。

## 開始時点での状態

- **Worktree**: `/home/okamoto/Projects/echoroo/.claude/worktrees/unruffled-kowalevski-7b4461`
- **Branch**: `011-zero-email-deployment` (`origin` への push なし、worktree local)
- **未 commit 変更**: Phase 1 完了 (T001-T004 done) + Phase 0+1+2 アーティファクト一式
- **メイン読込必須**:
  - `specs/011-zero-email-deployment/spec.md` (Rev.3.2、3 周 3 者収束 + Rev.3.3 patch + Rev.3.2 final)
  - `specs/011-zero-email-deployment/plan.md` (Rev.2 + Rev.3.2 patches)
  - `specs/011-zero-email-deployment/research.md` (R1-R14)
  - `specs/011-zero-email-deployment/data-model.md` (Rev.2)
  - `specs/011-zero-email-deployment/contracts/*.yaml` (6 ファイル)
  - `specs/011-zero-email-deployment/quickstart.md`
  - `specs/011-zero-email-deployment/tasks.md` (192 task、T001-T004 は `[x]` 済)
  - `~/.claude/projects/-home-okamoto-Projects-echoroo/memory/MEMORY.md` (echoroo project memory)

## 実行戦略 (確定)

### 12-step Implementation Plan を 1 PR ずつ main へ出す

`spec.md §Implementation Phasing` で 12 step に分割済。各 step を 1 PR にする。順序厳守:

1. **Step 1**: Migration `0021_zero_email_additive` (additive only)
2. **Step 2**: Banner subsystem (write side, services/user_banner.py, /me API, services/email.py の helper を banner enqueue 化)
3. **Step 3**: Middleware atomic swap (新 ForcedPasswordChangeMiddleware 追加 + 旧 EmailVerificationEnforcementMiddleware unregister を **同 PR**)
4. **Step 4**: step_up_token_service.py JWT 拡張 (factors + admin_recovery scope, Redis 不使用)
5. **Step 5**: Admin password reset (services/admin_password_reset.py + endpoint + UI)
6. **Step 6**: invitation_service.py 改修 (envelope 3→4 part + kid rotation + InvitationCreateOutcome refactor) + Trusted-overlay endpoint invitation_url + OpenAPI harness multi-spec
7. **Step 7**: Member-kind invitation endpoint + 既存ユーザー accept branch + frontend
8. **Step 8**: Bulk invitation
9. **Step 9**: SU bootstrap (intended_owner_email + ownership_transfer_on_accept + composite audit)
10. **Step 10**: Delete email subsystem (US1 MVP の deletion 部分、最大の cleanup PR)
11. **Step 11**: Migration `0022_email_subsystem_removal` (destructive)
12. **Step 12**: Documentation + final OpenAPI sync + SC validation

### 並列化

- Step 1, 2, 3, 4 は順次 (Step 1 が他全部の前提)
- Step 5 / 6 は Step 4 完了後並列可
- Step 7 は Step 6 後
- Step 8 は Step 7 後
- Step 9 は Step 7 後 (Step 8 と並列可)
- Step 10 は Step 1-9 後
- Step 11 は Step 10 後
- Step 12 は最後

### 各 step PR の標準フロー

1. **新 worktree 作成** (`git worktree add ../011-step-N` で別 worktree、本 worktree とは独立) — または background agent に `isolation: worktree` で投げる
2. **SSA 実装**: backend-developer / frontend-developer / fullstack-developer の最適者を選択。プロンプトに spec/plan/tasks 該当 task 全部のパスと FR-ID を渡す
3. **Codex review**: `codex exec --dangerously-bypass-approvals-and-sandbox --cd <worktree>` で確認
4. **必要なら SSA で fix → Codex re-review**、最大 3 round
5. **テスト実行**: `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov <changed paths> -q'` (memory: `pytest-docker-exec-pattern.md` 参照)
6. **typecheck**: backend `mypy`, frontend `tsc` (CLAUDE.md の規定)
7. **frontend がある step は Playwright で実機確認** (memory: `feedback_verify_before_pr.md`)
8. **tasks.md の対応 checkbox を `[x]` に更新**
9. **commit** (Co-Authored-By: Claude Opus 4.7 ...) → `git push -u origin <branch>` → `gh pr create`
10. **PR # を tasks.md の対応 step section に記録**

### PR 命名規則

- `feat(spec/011): step N — <短い要約>` (例: `feat(spec/011): step 1 — migration 0021 additive`)
- Body: spec FR-ID 一覧、test plan 結果、`Closes` で関連 issue (なければ省略)

## 主要決定事項リマインダ (繰り返し参照される事実)

- **Migration**: 0021 (additive) + 0022 (destructive)。0020 は target_taxa で既に占有
- **Migration `0022` の destructive 内容**: `email_verification_tokens` table drop, `password_reset_tokens` table drop, `users.email_verified_at` drop
- **Migration `0021` 内容**: `users.must_change_password`, `users.temp_password_expires_at`, `users.email_change_cooldown_until`, `project_invitations.ownership_transfer_on_accept BOOL + CHECK (ownership_transfer_on_accept=false OR kind='member')`, `user_banner_dismissals(user_id, audit_table, audit_log_id, dismissed_at)` polymorphic over `project_audit_log + platform_audit_log`
- **Step-up token**: 既存 `apps/api/echoroo/services/step_up_token_service.py` の **HS256 JWT を拡張** (web_session_secret 署名、Redis 不使用)。`factors` claim + `admin_recovery` scope 追加
- **TrustedDeviceService.revoke_all_for_user**: **既存** helper を変更 (現状 `del reason` で破棄 → 使用 + `auth.trusted_device.revoke_all` audit emit + 全 callsite に reason code 渡す)
- **Invitation envelope**: 3-part `{token}.{exp}.{mac_b64u}` → 4-part `{token}.{exp}.{kid}.{mac_b64u}`。MAC は `_b64u_encode(HMAC-SHA-256(secret_for(kid), token + "." + exp + "." + kid))`
- **kid rotation env**: `INVITATION_TOKEN_KID_NEW` / `_OLD` / `_HMAC_KEY` / `_HMAC_KEY_OLD` / `_KID_GRACE_HOURS` (default 24)。Phase 17 A-12 と同 pattern。`KID_OLD` set without `HMAC_KEY_OLD` で boot 拒否 (model_validator)
- **Audit action constants**: `audit_service.py` ではなく **service-private** モジュールに配置 (invitation_service.py, admin_password_reset.py 等)。命名 `verb.noun.verb` 3-segment dot (`project.member.invite_accepted_signup` 等)
- **DESTRUCTIVE_ACTIONS allowlist**: `services/audit_service.py` 配置 (cross-cutting)
- **ACTION constants**: `core/actions.py` に 5 件追加 (PROJECT_MEMBER_INVITATION_ISSUE_ACTION, ADMIN_USER_RESET_PASSWORD_ACTION, USER_BANNER_LIST_ACTION, USER_BANNER_DISMISS_ACTION, USER_ACTIVITY_LIST_ACTION)
- **endpoint_allowlist 拡張**: `TOKEN_AUTH_ONLY` (invitation public 2 route) + `AUTHENTICATED_SELF_NO_GATE` (step-up 2 route、新 allowlist)
- **services/email.py**: 削除 3 helper (verification / password_reset / 2fa_magic_link)、書き換え 5 helper (login_notification / email_change / 2fa_dispatched / api_key_revoke / api_key_scope_degrade) → banner audit emit。**ファイル自体は retain** (R9)
- **ForcedPasswordChangeMiddleware allowlist**: `/auth/change-password`, `/auth/logout` (web-v1 + v1 両 mirror), `/health`, `/metrics`, `/favicon.ico`, OPTIONS method 全 path, `/static/` prefix
- **`/auth/change-password`** は **`PUBLIC_AUTH_PATHS` に追加しない** (CSRF + session 必須、middleware allowlist のみ)
- **Telemetry redaction**: 新規 `apps/api/echoroo/observability/sentry.py` (Sentry init は `SENTRY_DSN` set 時のみ enable) + 新規 `apps/api/echoroo/middleware/redaction.py` (`audit_logging.py` は拡張しない)
- **OpenAPI harness**: snapshot file 無し。`apps/api/tests/contract/test_openapi_diff.py` を contracts dir 複数対応に refactor (`_CONTRACTS_DIRS` tuple 化)、spec/006 baseline 維持 + spec/011 追加
- **CI guard**: 新規 `apps/api/tests/contract/test_no_email_subsystem_traces.py` (regex は spec.md NFR-011-001 をそのまま使う、`smtp` 単独は false-positive 回避のため不使用)
- **既存ユーザー accept**: invitation 受諾は `caller_state` で signup branch / authenticated user branch を分岐、`canonicalize_email` (NFKC + casefold) で bound email 比較
- **SU bootstrap composite audit**: `project.ownership.bootstrap_transfer` 1 行 + `pre_transfer_action_summary` JSON (shape: `{summary: [{action, occurred_at, target_id?}]}`、`target_id` は DESTRUCTIVE_ACTIONS のみ preserve)

## 守ること (memory より)

- **CLAUDE.md**: chat は日本語、コード/コメントは英語、typecheck 必須
- **pytest は docker exec 経由**: `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov ...'` (host で `uv run pytest` は `.venv` 権限で blocked)
- **redis-cli FLUSHALL 厳禁** (session / Celery 全消し)
- **rate-limit clear** は `login_attempts` table delete のみ
- **Rosé Pine theme** (frontend)、Light=Dawn / Dark=Main
- **i18n**: en.json + ja.json 両方更新 (Paraglide-JS v2.13.1、~2060 keys)
- **Test account**: `test@echoroo.app` (Playwright/e2e)、`okamoto.ryotaro@nies.go.jp` (admin)。memory `test-accounts.md` 参照
- **並列 SSA 制約**: 3 並列禁止、`isolation: "worktree"` 必須、完了後 `git log --all --graph` 検証 (memory `feedback_parallel_ssa_git_isolation.md`)
- **PR 前に Playwright で実機確認** (memory `feedback_verify_before_pr.md`、PR #89/90/91 の revert 教訓)
- **UI 実装の前に旧実装を `git show <commit> -- <path>` で確認** (memory `feedback_check_prior_ui.md`)
- **Discord で進捗 ping**: chat_id `1489151483030142976` (memory `feedback_discord_communication.md`)。各 step PR 完了時に「Step N merged」ping
- **Celery worker**: classifier/sampling/banner enqueue 変更後は `echoroo-worker-cpu` も restart (memory `celery-workers.md`)

## 開始の最初のアクション

1. 本 HANDOFF.md と `memory/MEMORY.md` を読む
2. `git status` + `git log -1` + `git branch --show-current` で状態確認
3. **Phase 1 (T001-T004) は既に [x] 済、内容も適用済**。これを Step 0 として **独立 commit + PR** に切るか、Step 1 (migration 0021) と一緒にまとめるかを最初に判断。私の推奨は **Step 0 として独立 PR** (理由: pyproject.toml / .env.example / compose.dev.yaml のみで差分小、merge 競合リスク低、Step 1 が clean に main 上に乗る)
4. Step 0 PR を出した後、Step 1 (T010-T014 migration 0021 + 設定) を SSA に投げる
5. 以降は 12 step 順次 / 並列可能な step は並列で

## 完了基準

- 192 task 全てが tasks.md で `[x]`
- spec.md SC-1〜SC-6 が全部実機検証済 (T740-T745)
- 全 PR が main にマージ済
- `test_no_email_subsystem_traces.py` が CI で green
- main から `./scripts/docker.sh dev` で email 設定無しに deploy 可能

## 完了時のレポート先

- main HEAD commit hash + PR # リストを Discord chat_id `1489151483030142976` にポスト
- `~/.claude/projects/-home-okamoto-Projects-echoroo/memory/` に `project_011_completion_<date>.md` を作成し、`MEMORY.md` index に追記

## エスカレーション条件 (これらは私に確認を求める)

- セキュリティ重大判断 (新規 attack surface 発見等)
- spec/plan/data-model に矛盾発見でアーティファクト書き直しが必要なケース
- 3 round Codex review でも収束しない実装判断
- 既存 main の機能を意図せず壊す可能性のある change
- 24h を超える長時間連続実行 (chunk して再開へ)

それ以外 (typecheck error、test failure、SSA 出力の軽微な fix、PR レビュー comments) は自律対応。

---

**準備 OK なら開始してください。Step 0 (Phase 1 commit + PR) → Step 1 (migration 0021) の順で。**
