# Tasks: System Administration

**Input**: Design documents from `/specs/001-administration/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: TDD approach per constitution - tests are REQUIRED for all API endpoints and services.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Backend**: `apps/api/echoroo/` (FastAPI)
- **Frontend**: `apps/web/src/` (SvelteKit)
- **Backend Tests**: `apps/api/tests/`
- **Frontend Tests**: `apps/web/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and core configuration

- [x] T001 [P] Configure core security utilities in apps/api/echoroo/core/security.py (JWT, password hashing with bcrypt)
- [x] T002 [P] Configure exception handlers in apps/api/echoroo/core/exceptions.py
- [x] T003 [P] Configure settings loader in apps/api/echoroo/core/settings.py
- [x] T004 [P] Create base repository class (in repositories/__init__.py)
- [x] T005 [P] Create base schema classes in apps/api/echoroo/schemas/__init__.py
- [x] T006 Setup API router registration in apps/api/echoroo/api/v1/__init__.py
- [x] T007 [P] Configure database session dependency in apps/api/echoroo/core/database.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Authentication Middleware

- [x] T008 Create authentication middleware in apps/api/echoroo/middleware/auth.py (JWT validation, current_user dependency)
- [x] T009 Create rate limiting middleware in apps/api/echoroo/middleware/rate_limit.py (Redis sliding window)

### Core Repositories

- [x] T010 [P] Create UserRepository in apps/api/echoroo/repositories/user.py
- [x] T011 [P] Create SystemSettingRepository in apps/api/echoroo/repositories/system.py
- [x] T012 [P] Create LoginAttemptRepository (in repositories/user.py)

### Core Schemas

- [x] T013 [P] Create auth schemas in apps/api/echoroo/schemas/auth.py (LoginRequest, RegisterRequest, TokenResponse)
- [x] T014 [P] Create user schemas in apps/api/echoroo/schemas/user.py (UserResponse, UserUpdate, ProfileUpdate)

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 6 - 初回セットアップ (Priority: P1) 🎯 MVP

**Goal**: Enable initial system setup with first admin account creation

**Independent Test**: Access /setup page, create admin, verify redirect to login

### Tests for User Story 6

- [x] T015 [P] [US6] Contract test for GET /api/v1/setup/status in apps/api/tests/contract/test_setup.py
- [x] T016 [P] [US6] Contract test for POST /api/v1/setup/complete in apps/api/tests/contract/test_setup.py
- [x] T017 [P] [US6] Integration test for setup flow in apps/api/tests/integration/test_setup_flow.py

### Implementation for User Story 6

- [x] T018 [P] [US6] Create setup schemas in apps/api/echoroo/schemas/setup.py
- [x] T019 [US6] Create SetupService in apps/api/echoroo/services/setup.py
- [x] T020 [US6] Create setup router in apps/api/echoroo/api/v1/setup.py (status, complete endpoints)
- [x] T021 [US6] Create setup page in apps/web/src/routes/setup/+page.svelte
- [x] T022 [US6] Create setup page server load in apps/web/src/routes/setup/+page.server.ts
- [x] T023 [US6] Add setup status check in apps/web/src/hooks.server.ts

**Checkpoint**: Initial setup wizard functional - system can be bootstrapped

---

## Phase 4: User Story 1 - ユーザー登録とログイン (Priority: P1) 🎯 MVP

**Goal**: Enable user authentication (login, logout, registration, password reset)

**Independent Test**: Register, login, logout, password reset flow

### Tests for User Story 1

- [x] T024 [P] [US1] Contract test for POST /api/v1/auth/login in apps/api/tests/contract/test_auth.py
- [x] T025 [P] [US1] Contract test for POST /api/v1/auth/logout in apps/api/tests/contract/test_auth.py
- [x] T026 [P] [US1] Contract test for POST /api/v1/auth/register in apps/api/tests/contract/test_auth.py
- [x] T027 [P] [US1] Contract test for POST /api/v1/auth/refresh in apps/api/tests/contract/test_auth.py
- [x] T028 [P] [US1] Contract test for password reset endpoints in apps/api/tests/contract/test_auth.py
- [x] T029 [P] [US1] Integration test for auth flow in apps/api/tests/integration/test_auth_flow.py

### Implementation for User Story 1

- [x] T030 [US1] Create AuthService in apps/api/echoroo/services/auth.py (login, register, token refresh, password reset)
- [x] T031 [US1] Create auth router in apps/api/echoroo/api/v1/auth.py
- [x] T032 [P] [US1] Create auth store in apps/web/src/lib/stores/auth.svelte.ts
- [x] T033 [P] [US1] Create API client in apps/web/src/lib/api/client.ts
- [x] T034 [US1] Create login page in apps/web/src/routes/(auth)/login/+page.svelte
- [x] T035 [US1] Create register page in apps/web/src/routes/(auth)/register/+page.svelte
- [x] T036 [US1] Create password reset pages in apps/web/src/routes/(auth)/reset-password/
- [x] T037 [US1] Create auth layout guard in apps/web/src/routes/(app)/+layout.server.ts
- [x] T038 [US1] Create logout action (in auth service)

**Checkpoint**: Users can register, login, and logout - core auth functional

---

## Phase 5: User Story 2 - プロジェクト作成と管理 (Priority: P1)

**Goal**: Enable project CRUD and basic member management

**Independent Test**: Create project, edit settings, view project list

### Tests for User Story 2

- [x] T039 [P] [US2] Contract test for GET /api/v1/projects in apps/api/tests/contract/test_projects.py
- [x] T040 [P] [US2] Contract test for POST /api/v1/projects in apps/api/tests/contract/test_projects.py
- [x] T041 [P] [US2] Contract test for PATCH /api/v1/projects/{id} in apps/api/tests/contract/test_projects.py
- [x] T042 [P] [US2] Contract test for DELETE /api/v1/projects/{id} in apps/api/tests/contract/test_projects.py
- [x] T043 [P] [US2] Integration test for project flow in apps/api/tests/integration/test_project_flow.py

### Implementation for User Story 2

- [x] T044 [P] [US2] Create project schemas in apps/api/echoroo/schemas/project.py
- [x] T045 [P] [US2] Create ProjectRepository in apps/api/echoroo/repositories/project.py
- [x] T046 [US2] Create ProjectService in apps/api/echoroo/services/project.py
- [x] T047 [US2] Create projects router in apps/api/echoroo/api/v1/projects.py
- [x] T048 [P] [US2] Create API client in apps/web/src/lib/api/projects.ts
- [x] T049 [US2] Create project list page in apps/web/src/routes/(app)/projects/+page.svelte
- [x] T050 [US2] Create project create page in apps/web/src/routes/(app)/projects/new/+page.svelte
- [x] T051 [US2] Create project detail page in apps/web/src/routes/(app)/projects/[id]/+page.svelte
- [x] T052 [US2] Create project settings page in apps/web/src/routes/(app)/projects/[id]/settings/+page.svelte
- [x] T053 [US2] Create dashboard page with project list in apps/web/src/routes/(app)/dashboard/+page.svelte

**Checkpoint**: Users can create and manage projects - core workflow functional

---

## Phase 6: User Story 3 - プロジェクトメンバー権限管理 (Priority: P2)

**Goal**: Enable role-based member management (Admin/Member/Viewer)

**Independent Test**: Add member with role, change role, verify permissions

### Tests for User Story 3

- [x] T054 [P] [US3] Contract test for GET /api/v1/projects/{id}/members in apps/api/tests/contract/test_permissions.py
- [x] T055 [P] [US3] Contract test for POST /api/v1/projects/{id}/members in apps/api/tests/contract/test_permissions.py
- [x] T056 [P] [US3] Contract test for PATCH /api/v1/projects/{id}/members/{user_id} in apps/api/tests/contract/test_permissions.py
- [x] T057 [P] [US3] Contract test for DELETE /api/v1/projects/{id}/members/{user_id} in apps/api/tests/contract/test_permissions.py
- [x] T058 [P] [US3] Integration test for role-based access control in apps/api/tests/integration/test_permissions.py

### Implementation for User Story 3

- [x] T059 [P] [US3] Create member schemas in apps/api/echoroo/schemas/project.py (ProjectMember schemas)
- [x] T060 [P] [US3] Create ProjectMemberRepository in apps/api/echoroo/repositories/project.py
- [x] T061 [US3] Create ProjectMemberService in apps/api/echoroo/services/project.py
- [x] T062 [US3] Add member endpoints to projects router in apps/api/echoroo/api/v1/projects.py
- [x] T063 [US3] Create permission checker decorator in apps/api/echoroo/core/permissions.py
- [x] T064 [US3] Create member management component (in members page)
- [x] T065 [US3] Create role selector component (in members page)
- [x] T066 [US3] Add members tab to project detail in apps/web/src/routes/(app)/projects/[id]/members/+page.svelte

**Checkpoint**: Project admins can manage member roles

---

## Phase 7: User Story 4 - ユーザープロフィール管理 (Priority: P2)

**Goal**: Enable profile editing and password change

**Independent Test**: View profile, update display name, change password

### Tests for User Story 4

- [x] T067 [P] [US4] Contract test for GET /api/v1/profile in apps/api/tests/contract/test_users.py
- [x] T068 [P] [US4] Contract test for PATCH /api/v1/profile in apps/api/tests/contract/test_users.py
- [x] T069 [P] [US4] Contract test for PUT /api/v1/profile/password in apps/api/tests/contract/test_users.py

### Implementation for User Story 4

- [x] T070 [P] [US4] Create profile schemas in apps/api/echoroo/schemas/user.py
- [x] T071 [US4] Create ProfileService in apps/api/echoroo/services/user.py
- [x] T072 [US4] Create profile endpoints in apps/api/echoroo/api/v1/users.py
- [x] T073 [P] [US4] Create API client in apps/web/src/lib/api/users.ts
- [x] T074 [US4] Create profile page in apps/web/src/routes/(app)/profile/+page.svelte
- [x] T075 [US4] Create password change form (in profile page)

**Checkpoint**: Users can manage their profile and password

---

## Phase 8: User Story 5 - システム管理者機能 (Priority: P2)

**Goal**: Enable superuser to manage all users and system settings

**Independent Test**: Access admin panel, list users, disable user, change settings

### Tests for User Story 5

- [x] T076 [P] [US5] Contract test for GET /api/v1/admin/users in apps/api/tests/contract/test_admin.py
- [x] T077 [P] [US5] Contract test for PATCH /api/v1/admin/users/{id} in apps/api/tests/contract/test_admin.py
- [x] T078 [P] [US5] Contract test for POST /api/v1/admin/users/{id}/force-logout in apps/api/tests/contract/test_admin.py
- [x] T079 [P] [US5] Contract test for GET /api/v1/admin/settings in apps/api/tests/contract/test_admin.py
- [x] T080 [P] [US5] Contract test for PATCH /api/v1/admin/settings in apps/api/tests/contract/test_admin.py

### Implementation for User Story 5

- [x] T081 [P] [US5] Create admin schemas in apps/api/echoroo/schemas/admin.py
- [x] T082 [US5] Create AdminUserService in apps/api/echoroo/services/admin.py
- [x] T083 [US5] Create SystemSettingService in apps/api/echoroo/services/admin.py
- [x] T084 [US5] Create users admin endpoints in apps/api/echoroo/api/v1/admin.py
- [x] T085 [US5] Create admin settings endpoints in apps/api/echoroo/api/v1/admin.py
- [x] T086 [US5] Create superuser guard in apps/api/echoroo/core/permissions.py
- [x] T087 [P] [US5] Create API client in apps/web/src/lib/api/admin.ts
- [x] T088 [US5] Create admin layout in apps/web/src/routes/(admin)/+layout.svelte
- [x] T089 [US5] Create admin dashboard (in layout)
- [x] T090 [US5] Create user management page in apps/web/src/routes/(admin)/admin/users/+page.svelte
- [x] T091 [US5] Create settings page in apps/web/src/routes/(admin)/admin/settings/+page.svelte

**Checkpoint**: Superusers can manage system-wide settings and users

---

## Phase 9: User Story 8 - レコーダー管理 (Priority: P2)

**Goal**: Enable master data management for recorders

**Independent Test**: List recorders, create recorder, edit, delete

### Tests for User Story 8

- [x] T092 [P] [US8] Contract test for GET /api/v1/admin/recorders in apps/api/tests/contract/test_recorders.py
- [x] T093 [P] [US8] Contract test for POST /api/v1/admin/recorders in apps/api/tests/contract/test_recorders.py
- [x] T094 [P] [US8] Contract test for PATCH /api/v1/admin/recorders/{id} in apps/api/tests/contract/test_recorders.py
- [x] T095 [P] [US8] Contract test for DELETE /api/v1/admin/recorders/{id} in apps/api/tests/contract/test_recorders.py

### Implementation for User Story 8

- [x] T096 [US8] Create Recorder model in apps/api/echoroo/models/recorder.py
- [x] T097 [US8] Add Recorder to models/__init__.py
- [x] T098 [P] [US8] Create recorder schemas in apps/api/echoroo/schemas/recorder.py
- [x] T099 [P] [US8] Create RecorderRepository in apps/api/echoroo/repositories/recorder.py
- [x] T100 [US8] Create RecorderService in apps/api/echoroo/services/recorder.py
- [x] T101 [US8] Add recorder endpoints to admin router in apps/api/echoroo/api/v1/admin.py
- [x] T102 [US8] Create Alembic migration for recorders table with seed data in apps/api/alembic/versions/
- [x] T103 [P] [US8] Create API client in apps/web/src/lib/api/recorders.ts (follows existing pattern)
- [x] T104 [US8] Create recorder management page in apps/web/src/routes/(admin)/admin/recorders/+page.svelte
- [x] T105 [US8] Create recorder form (inline in page, follows existing pattern)

**Checkpoint**: Administrators can manage recorder master data

---

## Phase 10: User Story 9 - ライセンス管理 (Priority: P2)

**Goal**: Enable master data management for licenses

**Independent Test**: List licenses, create license, edit, delete

### Tests for User Story 9

- [x] T106 [P] [US9] Contract test for GET /api/v1/admin/licenses in apps/api/tests/contract/test_licenses.py
- [x] T107 [P] [US9] Contract test for POST /api/v1/admin/licenses in apps/api/tests/contract/test_licenses.py
- [x] T108 [P] [US9] Contract test for PATCH /api/v1/admin/licenses/{id} in apps/api/tests/contract/test_licenses.py
- [x] T109 [P] [US9] Contract test for DELETE /api/v1/admin/licenses/{id} in apps/api/tests/contract/test_licenses.py

### Implementation for User Story 9

- [x] T110 [US9] Create License model in apps/api/echoroo/models/license.py
- [x] T111 [US9] Add License to models/__init__.py
- [x] T112 [P] [US9] Create license schemas in apps/api/echoroo/schemas/license.py
- [x] T113 [P] [US9] Create LicenseRepository in apps/api/echoroo/repositories/license.py
- [x] T114 [US9] Create LicenseService in apps/api/echoroo/services/license.py
- [x] T115 [US9] Add license endpoints to admin router in apps/api/echoroo/api/v1/admin.py
- [x] T116 [US9] Create Alembic migration for licenses table with seed data in apps/api/alembic/versions/
- [x] T117 [P] [US9] Create API client in apps/web/src/lib/api/licenses.ts (follows existing pattern)
- [x] T118 [US9] Create license management page in apps/web/src/routes/(admin)/admin/licenses/+page.svelte
- [x] T119 [US9] Create license form (inline in page, follows existing pattern)

**Checkpoint**: Administrators can manage license master data

---

## Phase 11: User Story 7 - APIトークン管理 (Priority: P3)

**Goal**: Enable programmatic API access via tokens

**Independent Test**: Generate token, use token for API call, revoke token

### Tests for User Story 7

- [x] T120 [P] [US7] Contract test for API tokens in apps/api/tests/contract/test_tokens.py
- [x] T121 [P] [US7] Contract test for POST /api/v1/users/me/api-tokens in apps/api/tests/contract/test_tokens.py
- [x] T122 [P] [US7] Contract test for DELETE /api/v1/users/me/api-tokens/{id} in apps/api/tests/contract/test_tokens.py
- [x] T123 [P] [US7] Integration test for API token authentication in apps/api/tests/integration/test_token_auth.py

### Implementation for User Story 7

- [x] T124 [P] [US7] Create api token schemas in apps/api/echoroo/schemas/token.py
- [x] T125 [P] [US7] Create APITokenRepository (in services/token.py)
- [x] T126 [US7] Create APITokenService in apps/api/echoroo/services/token.py
- [x] T127 [US7] Create api tokens endpoints in apps/api/echoroo/api/v1/users.py
- [x] T128 [US7] Add API token authentication to middleware in apps/api/echoroo/middleware/auth.py
- [x] T129 [P] [US7] Create API client in apps/web/src/lib/api/tokens.ts
- [x] T130 [US7] Create API tokens page in apps/web/src/routes/(app)/profile/api-tokens/+page.svelte
- [x] T131 [US7] Create token display modal (inline in page)

**Checkpoint**: Users can generate and manage API tokens

---

## Phase 12: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T132 [P] Run mypy type check on backend (apps/api) - 1 warning in middleware (non-blocking)
- [x] T133 [P] Run npm check on frontend (apps/web) - 0 errors, 0 warnings
- [x] T134 [P] Run ruff linter on backend (apps/api) - All checks passed
- [x] T135 [P] Run eslint on frontend (apps/web) - 0 errors, 4 warnings (any types)
- [x] T136 Create e2e test for full registration flow in apps/web/tests/e2e/auth.spec.ts
- [x] T137 Create e2e test for project management flow in apps/web/tests/e2e/projects.spec.ts
- [x] T138 Create e2e test for admin panel flow in apps/web/tests/e2e/admin.spec.ts
- [x] T139 Validate quickstart.md scenarios - covered by e2e tests
- [x] T140 Security audit - CSRF protection, XSS prevention, SQL injection prevention implemented

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 6 (Phase 3)**: Depends on Foundational - First MVP milestone
- **User Story 1 (Phase 4)**: Depends on Foundational - Second MVP milestone
- **User Story 2 (Phase 5)**: Depends on Foundational + US1 (auth required)
- **User Stories 3-9 (Phase 6-11)**: Depend on Foundational + US1
- **Polish (Phase 12)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Setup (Phase 1)
    │
    ▼
Foundational (Phase 2)
    │
    ├──────────────────────────────────────────────────┐
    │                                                  │
    ▼                                                  ▼
[US6] Initial Setup ──► [US1] Auth ──► [US2] Projects
    (P1)                   (P1)            (P1)
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
    [US3] Roles         [US4] Profile       [US5] Admin
      (P2)                (P2)                (P2)
                            │                   │
                            │          ┌────────┴────────┐
                            │          │                 │
                            ▼          ▼                 ▼
                        [US7] API    [US8] Recorders  [US9] Licenses
                         Tokens        (P2)             (P2)
                          (P3)
```

### Within Each User Story

1. Tests MUST be written and FAIL before implementation (TDD)
2. Models before services
3. Repositories before services
4. Services before routers
5. Backend before frontend
6. Story complete before moving to next priority

### Parallel Opportunities

**Phase 1 (all parallel)**:
- T001, T002, T003, T004, T005, T007

**Phase 2 (parallel groups)**:
- T010, T011, T012 (repositories)
- T013, T014 (schemas)

**Per User Story**:
- All tests marked [P] can run in parallel
- Models/schemas marked [P] can run in parallel
- Frontend components marked [P] can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together:
Task: "Contract test for POST /api/v1/auth/login in apps/api/tests/contract/test_auth.py"
Task: "Contract test for POST /api/v1/auth/logout in apps/api/tests/contract/test_auth.py"
Task: "Contract test for POST /api/v1/auth/register in apps/api/tests/contract/test_auth.py"
Task: "Contract test for POST /api/v1/auth/refresh in apps/api/tests/contract/test_auth.py"

# Launch frontend components in parallel:
Task: "Create auth store in apps/web/src/lib/stores/auth.ts"
Task: "Create API client in apps/web/src/lib/api/client.ts"
```

---

## Parallel Example: User Story 8 + 9 (can run in parallel)

```bash
# Developer A: User Story 8 (Recorders)
Task: "Create Recorder model in apps/api/echoroo/models/recorder.py"
Task: "Create RecorderRepository in apps/api/echoroo/repositories/recorder.py"
Task: "Create RecorderService in apps/api/echoroo/services/recorder.py"

# Developer B: User Story 9 (Licenses) - simultaneously
Task: "Create License model in apps/api/echoroo/models/license.py"
Task: "Create LicenseRepository in apps/api/echoroo/repositories/license.py"
Task: "Create LicenseService in apps/api/echoroo/services/license.py"
```

---

## Implementation Strategy

### MVP First (P1 Stories Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 6 (Initial Setup)
4. Complete Phase 4: User Story 1 (Auth)
5. Complete Phase 5: User Story 2 (Projects)
6. **STOP and VALIDATE**: Test all P1 stories independently
7. Deploy/demo if ready - **This is the MVP!**

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add User Story 6 → Test → Deploy (can bootstrap system)
3. Add User Story 1 → Test → Deploy (can authenticate)
4. Add User Story 2 → Test → Deploy (MVP complete!)
5. Add P2 stories in any order → Test → Deploy
6. Add P3 stories → Test → Deploy

### Parallel Team Strategy

With 3 developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 6 → User Story 1
   - Developer B: User Story 2 (starts when US1 has auth ready)
   - Developer C: Frontend components (parallel with backend)
3. After MVP:
   - Developer A: User Story 3 + 4
   - Developer B: User Story 5
   - Developer C: User Story 8 + 9 (parallel)
4. Finally: User Story 7 (P3)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (TDD per constitution)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Models are already implemented: User, Project, ProjectMember, APIToken, LoginAttempt, SystemSetting
- New models to implement: Recorder, License
