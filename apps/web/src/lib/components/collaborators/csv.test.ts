import { describe, it, expect } from 'vitest';
import { csvEscape, buildBulkCsv } from './csv';
import type { BulkInvitationResultItem } from '$lib/types';

describe('csvEscape', () => {
  it('returns plain values untouched', () => {
    expect(csvEscape('alice@example.com')).toBe('alice@example.com');
    expect(csvEscape('issued')).toBe('issued');
    expect(csvEscape('')).toBe('');
  });

  it('wraps and doubles quotes when a comma is present', () => {
    expect(csvEscape('a,b')).toBe('"a,b"');
  });

  it('doubles internal quotes and wraps', () => {
    expect(csvEscape('a"b')).toBe('"a""b"');
  });

  it('wraps when a newline is present', () => {
    expect(csvEscape('a\nb')).toBe('"a\nb"');
  });
});

describe('buildBulkCsv', () => {
  const resolveUrl = (raw: string) => `https://app.example.com/invite/${raw}`;

  it('emits the header even with no rows', () => {
    expect(buildBulkCsv([], resolveUrl)).toBe('email,status,invitation_url');
  });

  it('resolves the URL only for issued rows and leaves others blank', () => {
    const results: BulkInvitationResultItem[] = [
      {
        email: 'alice@example.com',
        status: 'issued',
        invitation_id: 'inv-1',
        invitation_url: 'tok-1',
        expires_at: '2026-12-31T00:00:00Z',
        error_message: null,
      },
      {
        email: 'bob@example.com',
        status: 'already_member',
        invitation_id: null,
        invitation_url: null,
        expires_at: null,
        error_message: null,
      },
    ];

    const csv = buildBulkCsv(results, resolveUrl);

    expect(csv).toBe(
      [
        'email,status,invitation_url',
        'alice@example.com,issued,https://app.example.com/invite/tok-1',
        'bob@example.com,already_member,',
      ].join('\n'),
    );
  });

  it('escapes fields that contain a comma', () => {
    const results: BulkInvitationResultItem[] = [
      {
        email: 'a,b@example.com',
        status: 'issued',
        invitation_id: 'inv-2',
        invitation_url: 'tok-2',
        expires_at: '2026-12-31T00:00:00Z',
        error_message: null,
      },
    ];

    const csv = buildBulkCsv(results, () => 'https://x/y,z');

    expect(csv).toBe(
      'email,status,invitation_url\n"a,b@example.com",issued,"https://x/y,z"',
    );
  });
});
