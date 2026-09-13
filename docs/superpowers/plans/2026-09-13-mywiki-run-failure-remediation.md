# myWiki Run Failure Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the three observed GitHub Actions failures in the myWiki project: intermittent Supabase 504s during data refresh, the missing remote `wiki_page_keywords` table, and the OpenRouter reasoning request mismatch.

**Architecture:** Add bounded exponential retry at the shared Supabase repository boundary and reduce the active-document page payload to the fields its callers actually use. Apply the already-reviewed keyword-table migration to the production Supabase project, then make classifier requests defer reasoning behavior to OpenRouter so models that require reasoning are not rejected.

**Tech Stack:** Python 3.12, pytest, supabase-py/PostgREST, OpenAI-compatible OpenRouter client, GitHub Actions.

**Spec:** User request to remediate the failures reported by the 2026-09-13 myWiki GitHub Actions runs.

## Global Constraints

- Preserve existing untracked user files `.codex-backup-raw-retention/` and `test_refresh_tmp.py`.
- Do not expose Supabase service-role keys or OpenRouter keys in logs, tests, or commits.
- Use bounded retries only for transient Supabase transport/gateway failures; never retry missing-table, authorization, or validation errors.
- Apply the existing `supabase/migrations/20260806020000_create_wiki_page_keywords.sql` SQL to the remote project; do not create a duplicate schema definition.
- Verify every production-facing change with a direct check or a passing automated test before claiming completion.

---

### Task 1: Make active-document reads resilient to transient Supabase gateway failures

**Files:**
- Modify: `src/pipeline_common/db.py`
- Modify: `src/pipeline_common/repository.py:246-277`
- Test: `tests/test_pipeline_db.py`
- Test: `tests/pipeline/test_pipeline.py`

**Interfaces:**
- Produces `execute_with_retry(operation, *, attempts=3, initial_delay_seconds=2.0)`, which retries only errors identified as transient gateway/timeout failures and re-raises the final exception.
- `repository.list_active_documents()` continues returning dictionaries with `id`, `workspace_id`, and `canonical_url`, while requesting only those columns and retrying each page query.

- [ ] **Step 1: Write the failing retry tests**

  Add tests for one transient `504` followed by success, and for a non-transient `PGRST205` error that must not be retried. Inject a fake sleeper so tests do not wait.

- [ ] **Step 2: Run the focused tests and verify they fail for the missing helper**

  Run: `pytest -q tests/test_pipeline_db.py`

  Expected: FAIL because `execute_with_retry` and transient-error detection do not exist yet.

- [ ] **Step 3: Implement bounded retry and the smaller active-document projection**

  Extract numeric error codes from both exception attributes and PostgREST dictionary arguments, retry `408/429/500/502/503/504` plus timeout/gateway text, log only the attempt and error code, and rebuild the Supabase query on every attempt.

- [ ] **Step 4: Run the focused tests and existing pagination tests**

  Run: `pytest -q tests/test_pipeline_db.py tests/pipeline/test_pipeline.py`

  Expected: PASS, including the existing multi-page and workspace-isolation tests.

### Task 2: Apply and verify the missing keyword-table migration remotely

**Files:**
- Source SQL: `supabase/migrations/20260806020000_create_wiki_page_keywords.sql`
- Test/verification: remote Supabase project `hwtfnemluhbivmgtnoud`

**Interfaces:**
- Remote schema gains `public.wiki_page_keywords` with its unique constraint, keyword index, RLS enabled, and workspace-member SELECT policy.

- [ ] **Step 1: Confirm the migration and table are absent before mutation**

  Use Supabase migration/table listing for project `hwtfnemluhbivmgtnoud`; expected current state is no matching migration and no `public.wiki_page_keywords` table.

- [ ] **Step 2: Apply the existing migration SQL**

  Apply the exact contents of `supabase/migrations/20260806020000_create_wiki_page_keywords.sql` with migration name `create_wiki_page_keywords`.

- [ ] **Step 3: Verify the remote schema and data API path**

  Confirm the migration and table are listed, run `select count(*) from public.wiki_page_keywords`, and run Supabase security/performance advisors. Do not modify access policy beyond the migration's existing RLS policy.

### Task 3: Stop classifier requests from disabling required OpenRouter reasoning

**Files:**
- Modify: `src/analysis/classifier.py:129-158`
- Test: `tests/test_analysis_classifier.py`

**Interfaces:**
- `_complete()` sends the standard OpenAI-compatible request without forcing `reasoning.enabled=false`; OpenRouter/model defaults decide whether reasoning is required.

- [ ] **Step 1: Write the failing request-shape test**

  Stub the OpenAI-compatible client, call `_complete()` with the current DeepSeek model, and assert the request has no `extra_body` field.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run: `pytest -q tests/test_analysis_classifier.py -k reasoning`

  Expected: FAIL because the current classifier always sends `extra_body={"reasoning": {"enabled": False}}`.

- [ ] **Step 3: Remove the incompatible forced reasoning override**

  Keep the existing fallback flow and free-model pacing unchanged; remove only the classifier-level forced reasoning payload.

- [ ] **Step 4: Run classifier, wiki keyword, and dedup tests**

  Run: `pytest -q tests/test_analysis_classifier.py tests/test_wiki_keyword_batch.py tests/test_wiki_dedup.py`

  Expected: PASS.

### Task 4: Run the full verification and inspect the next scheduled runs

**Files:**
- No additional source files.

- [ ] **Step 1: Run the full local test suite**

  Run: `pytest -q`

  Expected: PASS with no new failures.

- [ ] **Step 2: Re-check remote migration state and repository diff**

  Confirm the keyword table is present, confirm only intended tracked files changed, and confirm the pre-existing untracked files remain untouched.

- [ ] **Step 3: Trigger or inspect the next GitHub Actions runs**

  Prefer the next scheduled runs for verification. If a manual run is needed, run only the affected workflows after the user-approved code state is available; inspect job logs for the original 504, PGRST205, and reasoning errors.

