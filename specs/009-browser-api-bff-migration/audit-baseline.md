# Spec/009 Audit Baseline

Captured at the start of the browser API → BFF migration to anchor the
T122a SC-003 diff (and any future regression check).

## Browser-side /api/v1 grep snapshot 2026-05-13 (T003)

- Date: 2026-05-13
- Branch HEAD: `bfd81353b2b58b16426e35dbdc44fbe3c84e4de9`
- Command:
  ```bash
  rg -n '/api/v1/[a-zA-Z0-9/_${}-]+' apps/web/src/ \
      --glob '!**/__tests__/**' \
      --glob '!**/lib/types/**' | sort -u
  ```

Output:

```
apps/web/src/hooks.server.ts:65:    const response = await fetch(`${getServerApiUrl()}/api/v1/setup/status`);
apps/web/src/lib/api/admin.ts:34:    const endpoint = `/api/v1/admin/users${query ? `?${query}` : ''}`;
apps/web/src/lib/api/admin.ts:43:    return apiClient.patch<User>(`/api/v1/admin/users/${userId}`, data);
apps/web/src/lib/api/admin.ts:50:    return apiClient.get<Record<string, SystemSetting>>('/api/v1/admin/settings');
apps/web/src/lib/api/admin.ts:57:    return apiClient.patch<void>('/api/v1/admin/settings', data);
apps/web/src/lib/api/auth.ts:107:  return apiClient.post<MessageResponse>('/api/v1/auth/verify-email/resend');
apps/web/src/lib/api/auth.ts:40:  return apiClient.post<LoginResponse>('/api/v1/auth/login', data);
apps/web/src/lib/api/auth.ts:47:  return apiClient.post<RegisterResponse>('/api/v1/auth/register', data);
apps/web/src/lib/api/auth.ts:54:  await apiClient.post('/api/v1/auth/logout');
apps/web/src/lib/api/auth.ts:61:  return apiClient.post<TokenResponse>('/api/v1/auth/refresh');
apps/web/src/lib/api/auth.ts:68:  return apiClient.post<MessageResponse>('/api/v1/auth/password-reset/request', { email });
apps/web/src/lib/api/auth.ts:78:  return apiClient.post<MessageResponse>('/api/v1/auth/password-reset/confirm', {
apps/web/src/lib/api/auth.ts:88:  return apiClient.post<MessageResponse>('/api/v1/auth/verify-email', { token });
apps/web/src/lib/api/client.test.ts:108:      await apiClient.get('/api/v1/test');
apps/web/src/lib/api/client.test.ts:138:    expect(isPublicReadablePath('/api/v1/users/me')).toBe(false);
apps/web/src/lib/api/client.test.ts:20:    const result = await apiClient.get('/api/v1/test');
apps/web/src/lib/api/client.test.ts:23:      'http://localhost:8000/api/v1/test',
apps/web/src/lib/api/client.test.ts:248:    await apiClient.get('/api/v1/users/me');
apps/web/src/lib/api/client.test.ts:268:    // Only ONE fetch call — no `/api/v1/auth/refresh` retry.
apps/web/src/lib/api/client.test.ts:294:    await expect(apiClient.get('/api/v1/users/me')).rejects.toThrow();
apps/web/src/lib/api/client.test.ts:307:    await expect(apiClient.get('/api/v1/users/me')).rejects.toThrow();
apps/web/src/lib/api/client.test.ts:43:    const result = await apiClient.post('/api/v1/test', mockData);
apps/web/src/lib/api/client.test.ts:46:      'http://localhost:8000/api/v1/test',
apps/web/src/lib/api/client.test.ts:61:    await expect(apiClient.get('/api/v1/test')).rejects.toThrow('Not found');
apps/web/src/lib/api/client.test.ts:83:      await apiClient.post('/api/v1/test', { allowed_ip_cidrs: ['bad'] });
apps/web/src/lib/api/client.ts:153:   * `/api/v1/auth/refresh` and gets 401 in response.
apps/web/src/lib/api/client.ts:206:   * recognises it. The legacy `/api/v1/auth/refresh` route reads a
apps/web/src/lib/api/client.ts:354:    // would only trigger a useless `/api/v1/auth/refresh` round-trip and
apps/web/src/lib/api/licenses.ts:13:    return apiClient.get<LicenseListResponse>('/api/v1/admin/licenses');
apps/web/src/lib/api/licenses.ts:20:    return apiClient.get<License>(`/api/v1/admin/licenses/${id}`);
apps/web/src/lib/api/licenses.ts:27:    return apiClient.post<License>('/api/v1/admin/licenses', data);
apps/web/src/lib/api/licenses.ts:34:    return apiClient.patch<License>(`/api/v1/admin/licenses/${id}`, data);
apps/web/src/lib/api/licenses.ts:41:    return apiClient.delete<void>(`/api/v1/admin/licenses/${id}`);
apps/web/src/lib/api/projects.ts:195:    const endpoint = `/api/v1/projects${query ? `?${query}` : ''}`;
apps/web/src/lib/api/projects.ts:204:    return apiClient.get<Project>(`/api/v1/projects/${projectId}`);
apps/web/src/lib/api/projects.ts:211:    return apiClient.post<Project>('/api/v1/projects', data);
apps/web/src/lib/api/projects.ts:218:    return apiClient.patch<Project>(`/api/v1/projects/${projectId}`, data);
apps/web/src/lib/api/projects.ts:225:    return apiClient.delete<void>(`/api/v1/projects/${projectId}`);
apps/web/src/lib/api/projects.ts:232:    return apiClient.get<ProjectMember[]>(`/api/v1/projects/${projectId}/members`);
apps/web/src/lib/api/projects.ts:239:    return apiClient.post<ProjectMember>(`/api/v1/projects/${projectId}/members`, data);
apps/web/src/lib/api/projects.ts:251:      `/api/v1/projects/${projectId}/members/${userId}`,
apps/web/src/lib/api/projects.ts:260:    return apiClient.delete<void>(`/api/v1/projects/${projectId}/members/${userId}`);
apps/web/src/lib/api/projects.ts:267:    return apiClient.get<ProjectOverviewResponse>(`/api/v1/projects/${projectId}/overview`);
apps/web/src/lib/api/query-client.ts:53: * `meta: { projectId }`. Accepts both the `/api/v1/projects/{id}/...`
apps/web/src/lib/api/query-client.ts:62: * no project segment is present (e.g. `/api/v1/users/me`).
apps/web/src/lib/api/recorders.ts:31:    return apiClient.get<RecorderListResponse>(`/api/v1/admin/recorders${query ? `?${query}` : ''}`);
apps/web/src/lib/api/recorders.ts:38:    return apiClient.get<Recorder>(`/api/v1/admin/recorders/${id}`);
apps/web/src/lib/api/recorders.ts:45:    return apiClient.post<Recorder>('/api/v1/admin/recorders', data);
apps/web/src/lib/api/recorders.ts:52:    return apiClient.patch<Recorder>(`/api/v1/admin/recorders/${id}`, data);
apps/web/src/lib/api/recorders.ts:59:    return apiClient.delete<void>(`/api/v1/admin/recorders/${id}`);
apps/web/src/lib/api/setup.ts:21:  return apiClient.post<User>('/api/v1/setup/initialize', data);
apps/web/src/lib/api/taxa.ts:23:  return apiClient.get<TaxonSearchResult[]>(`/api/v1/taxa/search?${searchParams.toString()}`);
apps/web/src/lib/api/taxa.ts:35:  return apiClient.get<GBIFSpeciesResult[]>(`/api/v1/taxa/gbif-search?${searchParams.toString()}`);
apps/web/src/lib/api/tokens.ts:12:  return apiClient.get<APIToken[]>('/api/v1/users/me/api-tokens');
apps/web/src/lib/api/tokens.ts:22:  return apiClient.post<APITokenCreateResponse>('/api/v1/users/me/api-tokens', request);
apps/web/src/lib/api/tokens.ts:29:  return apiClient.delete<void>(`/api/v1/users/me/api-tokens/${tokenId}`);
apps/web/src/lib/api/users.ts:40: * ``/api/v1/users/me`` Bearer-JWT path is still served by
apps/web/src/lib/api/users.ts:53:  return apiClient.patch<User>('/api/v1/users/me', data);
apps/web/src/lib/api/users.ts:60:  return apiClient.request<PasswordChangeResponse>('/api/v1/users/me/password', {
apps/web/src/lib/api/web-auth.ts:7: * Unlike the legacy `/api/v1/auth/*` endpoints, these endpoints:
apps/web/src/lib/components/annotation/AnnotationExportDialog.svelte:31:    return `/api/v1/projects/${projectId}/annotation-projects/${annotationProjectId}/export?${params}`;
apps/web/src/lib/components/annotation/ExportDialog.svelte:80:      const url = `/api/v1/projects/${projectId}/annotation-projects/${annotationProjectId}/export?format=${selectedFormat}`;
apps/web/src/lib/components/common/MiniSpectrogram.svelte:62:    const url = `/api/v1/projects/${projId}/recordings/${recId}/spectrogram?${params}`;
apps/web/src/lib/components/data/ExportDialog.svelte:25:    return `/api/v1/projects/${projectId}/datasets/${datasetId}/export${queryString ? `?${queryString}` : ''}`;
apps/web/src/lib/stores/auth.svelte.ts:191:          '/api/v1/auth/login',
apps/web/src/lib/stores/auth.svelte.ts:220:     * NOTE: We deliberately do NOT call the legacy `/api/v1/auth/logout`
apps/web/src/lib/stores/auth.svelte.ts:225:     * NEXT login flow and 401 every subsequent `/api/v1/users/me` call
apps/web/src/lib/stores/auth.svelte.ts:254:     * Uses `/web-api/v1/auth/refresh` (not the legacy `/api/v1/auth/refresh`)
apps/web/src/lib/stores/auth.svelte.ts:287: * a background `/api/v1/auth/refresh` call fails. These correspond to the
apps/web/src/lib/utils/audioPlayback.svelte.ts:37:    return `/api/v1/projects/${projectId}/recordings/${recordingId}/playback?${params}`;
apps/web/src/lib/utils/audioPlayback.svelte.ts:75:    return `/api/v1/projects/${projectId}/recordings/${recordingId}/spectrogram?${params}`;
apps/web/src/routes/(app)/projects/[id]/annotations/[annotationProjectId]/+page.svelte:192:        `/api/v1/projects/${projectId}/clip-annotations/batch-tag`,
apps/web/src/routes/(public)/explore/projects/[id]/+page.svelte:147:   * (/api/v1/projects/{pid}/recordings/{rid}/audio) gates on VIEW_MEDIA which
apps/web/src/routes/(public)/explore/projects/[id]/+page.svelte:152:    return `/api/v1/projects/${rec.project_id}/recordings/${rec.id}/audio`;
apps/web/src/routes/+layout.svelte:23:   * stay on the explore page even when `/api/v1/auth/refresh` returns 401.
apps/web/src/routes/setup/+page.server.ts:16:    const response = await fetch(`${getServerApiUrl()}/api/v1/setup/status`);
```

## Pytest baseline 2026-05-13 (T002)

- Date: 2026-05-13
- Branch HEAD: `bfd81353b2b58b16426e35dbdc44fbe3c84e4de9`
- Backend pytest command (spec form): `(cd apps/api && uv run pytest -q 2>&1 | tail -10)`. The host-side `uv` run failed immediately with a stale `.venv` permission issue: `error: failed to remove directory '/home/okamoto/Projects/echoroo/apps/api/.venv/lib': Permission denied (os error 13)` (the bind-mounted `.venv` is owned by the container's user). Effective run was inside the dev container: `docker exec echoroo-backend sh -c 'cd /app && uv run pytest --no-cov -q'`. `--no-cov` is required because `pytest-cov` defaults to writing a coverage data file inside `/app` (bind mount), producing `INTERNALERROR: coverage.exceptions.DataError: Couldn't use data file '/app/.coverage.<host>.pid<N>.<rand>': unable to open database file`. With `--no-cov` the run reaches its natural end.
- Captured tail of last in-container `pytest --no-cov -q` run (last visible section): the short-test-summary block ended with the listed FAILED entries below. The pytest process exits via `subprocess` cleanly; the bind-mount means `tail -10` after a `|` clips the final aggregate count line, but the captured short-test-summary tail still anchors which suites were red at the launch checkpoint:

```
ERROR tests/security/test_stream_guard_parity.py::test_parity_superuser
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_approve_request_rejects_duplicate_from_same_approver
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_approve_request_rejects_revoked_approver
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_enter_break_glass_resolves_actor_user_id_to_superuser_id
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_enter_break_glass_skips_persist_when_actor_not_a_superuser
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_revoke_apply_blocks_when_only_one_active_superuser
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_revoke_apply_two_concurrent_revokes_leave_one_active
ERROR tests/unit/services/test_superuser_service_phase15_nogo.py::test_approve_request_two_concurrent_approvers_serialise
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_approve_request_rejects_duplicate_from_same_approver
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_approve_request_rejects_revoked_approver
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_enter_break_glass_resolves_actor_user_id_to_superuser_id
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_enter_break_glass_skips_persist_when_actor_not_a_superuser
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_revoke_apply_blocks_when_only_one_active_superuser
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_revoke_apply_two_concurrent_revokes_leave_one_active
ERROR tests/unit_baseline/test_superuser_service_phase15_nogo.py::test_approve_request_two_concurrent_approvers_serialise
ERROR tests/workers/test_search_janitor.py::test_dry_run_blocks_deletion
ERROR tests/workers/test_search_janitor.py::test_age_filter_excludes_recent
ERROR tests/workers/test_search_janitor.py::test_db_referenced_key_preserved
ERROR tests/workers/test_search_janitor.py::test_case_a_prefix_bulk_delete
ERROR tests/workers/test_search_janitor.py::test_case_b_individual_delete
ERROR tests/workers/test_search_janitor.py::test_legacy_non_uuid_job_id_tolerated
ERROR tests/workers/test_search_janitor.py::test_invalid_project_id_skipped
ERROR tests/workers/test_search_janitor.py::test_partial_failure_logged
FAILED tests/runbook/test_quickstart_phase3_smoke.py::test_check_wipe_guard_runs_against_live_stack
FAILED tests/security/authorization/test_endpoint_coverage.py::test_every_route_registered_in_actions
FAILED tests/security/crypto/test_dek_rewrap_and_kms_isolation.py::test_dek_rewrap_script_exists
FAILED tests/security/race_conditions/test_superuser_last_protection.py::test_concurrent_revokes_advisory_lock_serialises
FAILED tests/unit/services/test_api_key_lifecycle.py::test_api_key_write_permissions_canonical_subset_matches_expected
FAILED tests/unit/services/test_api_key_lifecycle.py::test_permission_enum_fully_partitioned_into_write_or_red
FAILED tests/unit/services/test_api_key_lifecycle.py::test_api_key_write_permissions_partition_is_total
```

- Visible counts in the captured tail (lower bound; pytest cuts the aggregate trailing line because of the docker exec pipe → tail buffering): **≥ 7 FAILED, ≥ 23 ERROR** at the launch HEAD. These are pre-existing test infrastructure issues that pre-date spec/009 (superuser fixture wiring, search janitor S3 fixture, coverage threshold gate, etc.) and **MUST NOT regress** during the spec/009 migration. T122a (Phase 9) re-runs `pytest tests/contract tests/integration` against the same HEAD diff and asserts **zero new failures**.
- Frontend `npm run check` result: `svelte-check found 0 errors and 18 warnings in 7 files` — green for spec/009 baseline purposes (warnings are pre-existing Svelte 5 deprecation notices and SSR `fetch` advisories outside the migration scope).
- Dev stack status at capture time: `echoroo-backend`, `echoroo-frontend`, `echoroo-db`, `echoroo-redis`, `echoroo-localstack`, `echoroo-worker-1`, `echoroo-worker-cpu-1` all up; backend logs show only routine `GET /health 200 OK` traffic; frontend logs show only Vite HMR reloads (no startup errors).

### Pytest baseline — follow-up (carryover for T122a)

The full pytest run is long-running (>1 hour) in the bind-mounted dev container, and `tail -N | docker exec` truncates the aggregated `= N failed, M passed, ... =` line. T122a (Phase 9 SC-003 evidence) will re-run the full suite with output redirected to a file inside the spec directory (`specs/009-browser-api-bff-migration/sc-evidence.md`) so the exact aggregate count is captured for the post-migration HEAD diff. For Phase 1 baseline purposes the failing-suite list above is sufficient to detect regressions: if Phase 9's run includes any FAIL or ERROR not in this list, T122a fails.
