/**
 * Static lint test for spec/007 Phase 1.5 / AD-3 / Q23.
 *
 * The global `QueryCache.onError` / `MutationCache.onError` hook in
 * `query-client.ts` relies on every project-scoped query/mutation
 * being tagged with `meta: { projectId }`. A missing meta means the
 * demotion mitigation silently no-ops because the URL-extraction
 * fallback only fires when the request URL still embeds the
 * project segment — not all surfaces do.
 *
 * This test scans a curated set of source files (the data + detection
 * components updated under Phase 1.5) using a brace-balancing parser
 * to extract the full options object of each `createQuery({...})` /
 * `createMutation({...})` call. It then fails when an options block
 * mentions the `projectId` identifier (project-scoped marker) but
 * lacks a top-level `meta:` key.
 *
 * Phase 2B.3 will replace this regex-based lint with a proper AST
 * walker; for now we cover the files audited under Phase 1.5 so a
 * regression that strips `meta` is caught in CI.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Files known to be project-scoped and audited under Phase 1.5.
 * Adding a new project-scoped query/mutation file should be paired
 * with adding it here.
 */
const AUDITED_FILES = [
  'src/lib/components/data/ClipList.svelte',
  'src/lib/components/data/ImportProgress.svelte',
  'src/lib/components/detection/DetectionReviewGrid.svelte',
];

/** Match the start of a `createQuery(` or `createMutation(` call. */
const CREATE_CALL_START_RE = /\bcreate(Query|Mutation)\s*\(\s*\{/g;

interface Violation {
  file: string;
  kind: 'Query' | 'Mutation';
  snippet: string;
}

/**
 * Given a source string and the index of the opening `{` of an
 * options object, walk forward respecting brace depth and skipping
 * string / template / comment bodies, and return the substring
 * between the opening `{` (exclusive) and the matching closing `}`
 * (exclusive). Returns `null` if no balanced match is found.
 */
function extractBalancedBlock(source: string, openBraceIdx: number): string | null {
  let depth = 1;
  let i = openBraceIdx + 1;
  while (i < source.length) {
    const ch = source[i];
    const next = source[i + 1];

    // Skip block comments.
    if (ch === '/' && next === '*') {
      const end = source.indexOf('*/', i + 2);
      if (end === -1) return null;
      i = end + 2;
      continue;
    }
    // Skip line comments.
    if (ch === '/' && next === '/') {
      const end = source.indexOf('\n', i + 2);
      i = end === -1 ? source.length : end + 1;
      continue;
    }
    // Skip string / template literals — they may contain unbalanced
    // braces that would otherwise throw off the depth counter.
    if (ch === '"' || ch === "'" || ch === '`') {
      const quote = ch;
      i += 1;
      while (i < source.length) {
        if (source[i] === '\\') {
          i += 2;
          continue;
        }
        if (source[i] === quote) {
          i += 1;
          break;
        }
        // Template-literal ${...} interpolations may themselves
        // contain braces — track them too.
        if (quote === '`' && source[i] === '$' && source[i + 1] === '{') {
          let innerDepth = 1;
          i += 2;
          while (i < source.length && innerDepth > 0) {
            if (source[i] === '{') innerDepth += 1;
            else if (source[i] === '}') innerDepth -= 1;
            i += 1;
          }
          continue;
        }
        i += 1;
      }
      continue;
    }

    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth -= 1;
      if (depth === 0) {
        return source.slice(openBraceIdx + 1, i);
      }
    }
    i += 1;
  }
  return null;
}

function scan(file: string): Violation[] {
  const fullPath = resolve(__dirname, '../../../..', file);
  const source = readFileSync(fullPath, 'utf8');
  const violations: Violation[] = [];

  for (const match of source.matchAll(CREATE_CALL_START_RE)) {
    const kind = (match[1] ?? 'Query') as 'Query' | 'Mutation';
    const matchIdx = match.index ?? 0;
    // The match consumes the opening `{`; the brace index is the
    // last char of `match[0]`.
    const openBraceIdx = matchIdx + match[0].length - 1;
    const optionsBody = extractBalancedBlock(source, openBraceIdx);
    if (optionsBody === null) continue;

    // Heuristic: only flag factories whose body references the
    // `projectId` identifier — that's our signal that the call is
    // project-scoped.
    const isProjectScoped = /\bprojectId\b/.test(optionsBody);
    if (!isProjectScoped) continue;

    // Look for a top-level `meta:` key — to keep this simple we
    // strip nested `{...}` blocks first so a deeply nested
    // `meta:` (unlikely but possible inside an `onSuccess` callback)
    // doesn't satisfy the check.
    const topLevel = stripNested(optionsBody);
    const hasMeta = /(^|\n|,|\{)\s*meta\s*:/.test(topLevel);
    if (hasMeta) continue;

    violations.push({
      file,
      kind,
      snippet: optionsBody.slice(0, 240).replace(/\s+/g, ' ').trim(),
    });
  }

  return violations;
}

function stripNested(body: string): string {
  let out = '';
  let depth = 0;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === '{') depth += 1;
    else if (ch === '}') {
      depth = Math.max(0, depth - 1);
      continue;
    }
    if (depth === 0) out += ch;
  }
  return out;
}

describe('meta-completeness lint (spec/007 Phase 1.5 / AD-3)', () => {
  it.each(AUDITED_FILES)(
    'every project-scoped create(Query|Mutation) in %s has meta: { projectId }',
    (file) => {
      const violations = scan(file);
      if (violations.length > 0) {
        const detail = violations
          .map(
            (v) =>
              `  - create${v.kind} in ${v.file} missing meta:\n      ${v.snippet}`,
          )
          .join('\n');
        throw new Error(
          `Found ${violations.length} project-scoped create(Query|Mutation) call(s) without meta: { projectId } in ${file}:\n${detail}`,
        );
      }
      expect(violations).toEqual([]);
    },
  );
});
