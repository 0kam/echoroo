import { describe, it, expect } from 'vitest';
import {
  ALL_TRUSTED_PERMISSIONS,
  permissionRecordFrom,
  emptyPermissionRecord,
  defaultInvitePermissionRecord,
  selectedPermissions,
} from './trustedPermissions';

describe('permissionRecordFrom', () => {
  it('sets exactly the granted permissions to true', () => {
    const record = permissionRecordFrom(['view_media', 'download']);
    expect(record.view_media).toBe(true);
    expect(record.download).toBe(true);
    expect(record.view_detection).toBe(false);
    expect(record.export).toBe(false);
  });

  it('produces a key for every allowlisted permission', () => {
    const record = permissionRecordFrom([]);
    expect(Object.keys(record).sort()).toEqual([...ALL_TRUSTED_PERMISSIONS].sort());
  });

  it('accepts a Set as well as an array', () => {
    const record = permissionRecordFrom(new Set(['vote'] as const));
    expect(record.vote).toBe(true);
    expect(record.comment).toBe(false);
  });
});

describe('emptyPermissionRecord', () => {
  it('is all false', () => {
    const record = emptyPermissionRecord();
    expect(Object.values(record).every((v) => v === false)).toBe(true);
  });
});

describe('defaultInvitePermissionRecord', () => {
  it('grants the safe read-only defaults (media + detection)', () => {
    const record = defaultInvitePermissionRecord();
    expect(record.view_media).toBe(true);
    expect(record.view_detection).toBe(true);
    expect(record.view_precise_location).toBe(false);
    expect(record.download).toBe(false);
    expect(record.export).toBe(false);
  });
});

describe('selectedPermissions', () => {
  it('flattens the record into allowlist order', () => {
    const record = permissionRecordFrom(['download', 'view_media', 'comment']);
    // Order follows ALL_TRUSTED_PERMISSIONS, not insertion order.
    expect(selectedPermissions(record)).toEqual(['view_media', 'download', 'comment']);
  });

  it('round-trips with permissionRecordFrom', () => {
    const granted = ['view_detection', 'export'] as const;
    expect(selectedPermissions(permissionRecordFrom(granted)).sort()).toEqual(
      [...granted].sort(),
    );
  });

  it('returns an empty array for an all-false record', () => {
    expect(selectedPermissions(emptyPermissionRecord())).toEqual([]);
  });
});
