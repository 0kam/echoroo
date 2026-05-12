/**
 * Smoke test for `can()` (Spec 007 Phase 2B.1).
 *
 * This is a small spot-check; the matrix-complete test lives in
 * Phase 2B.2.
 */

import { describe, it, expect } from 'vitest';

import {
  can,
  type ProjectContext,
  type RestrictedToggles,
} from './permissions';

const ALL_TOGGLES_ON: RestrictedToggles = {
  allow_media_playback: true,
  allow_detection_view: true,
  allow_download: true,
  allow_export: true,
  allow_voting_and_comments: true,
  allow_precise_location_to_viewer: true,
};

const ALL_TOGGLES_OFF: RestrictedToggles = {
  allow_media_playback: false,
  allow_detection_view: false,
  allow_download: false,
  allow_export: false,
  allow_voting_and_comments: false,
  allow_precise_location_to_viewer: false,
};

describe('can() — smoke test', () => {
  it('viewer on public can view_media', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'viewer',
      visibility: 'public',
    };
    expect(can('view_media', ctx)).toBe(true);
  });

  it('member on public CANNOT manage_dataset_admin (AD-1B vocabulary)', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'member',
      visibility: 'public',
    };
    expect(can('manage_dataset_admin', ctx)).toBe(false);
  });

  it('admin on public CAN manage_dataset_admin', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'admin',
      visibility: 'public',
    };
    expect(can('manage_dataset_admin', ctx)).toBe(true);
  });

  it('unauthenticated on public CAN view_media (guest overlay)', () => {
    const ctx: ProjectContext = {
      authState: 'unauthenticated',
      role: null,
      visibility: 'public',
    };
    expect(can('view_media', ctx)).toBe(true);
  });

  it('authenticated_non_member on public CAN vote (matches backend public-vote)', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_non_member',
      role: null,
      visibility: 'public',
    };
    expect(can('vote', ctx)).toBe(true);
  });

  it('unauthenticated on public CANNOT vote (guest overlay excludes vote)', () => {
    const ctx: ProjectContext = {
      authState: 'unauthenticated',
      role: null,
      visibility: 'public',
    };
    // Per fixture: visibility_overlays.public.guest = ['view_detection', 'view_media']
    expect(can('vote', ctx)).toBe(false);
  });

  it('pending_invitation NEVER grants permissions (safe default)', () => {
    const ctx: ProjectContext = {
      authState: 'pending_invitation',
      role: null,
      visibility: 'public',
    };
    expect(can('vote', ctx)).toBe(false);
    expect(can('view_media', ctx)).toBe(false);
  });

  it('loading NEVER grants permissions (safe default)', () => {
    const ctx: ProjectContext = {
      authState: 'loading',
      role: null,
      visibility: 'public',
    };
    expect(can('manage_dataset', ctx)).toBe(false);
    expect(can('view_media', ctx)).toBe(false);
  });

  it('unauthenticated on restricted with allow_media_playback=true CAN view_media', () => {
    const ctx: ProjectContext = {
      authState: 'unauthenticated',
      role: null,
      visibility: 'restricted',
      restrictedConfig: ALL_TOGGLES_ON,
    };
    expect(can('view_media', ctx)).toBe(true);
  });

  it('unauthenticated on restricted with all toggles OFF gets nothing', () => {
    const ctx: ProjectContext = {
      authState: 'unauthenticated',
      role: null,
      visibility: 'restricted',
      restrictedConfig: ALL_TOGGLES_OFF,
    };
    expect(can('view_media', ctx)).toBe(false);
    expect(can('view_detection', ctx)).toBe(false);
    expect(can('vote', ctx)).toBe(false);
  });

  it('viewer on restricted with allow_voting_and_comments=true CAN vote and comment', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'viewer',
      visibility: 'restricted',
      restrictedConfig: ALL_TOGGLES_ON,
    };
    expect(can('vote', ctx)).toBe(true);
    expect(can('comment', ctx)).toBe(true);
  });

  it('viewer on restricted with allow_precise_location_to_viewer=true CAN view_precise_location', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'viewer',
      visibility: 'restricted',
      restrictedConfig: { ...ALL_TOGGLES_OFF, allow_precise_location_to_viewer: true },
    };
    expect(can('view_precise_location', ctx)).toBe(true);
  });

  it('owner on public has every project permission', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'owner',
      visibility: 'public',
    };
    expect(can('delete_project', ctx)).toBe(true);
    expect(can('transfer_ownership', ctx)).toBe(true);
    expect(can('override_taxon_sensitivity', ctx)).toBe(true);
    expect(can('manage_trusted', ctx)).toBe(true);
  });

  it('member CANNOT delete_project or transfer_ownership', () => {
    const ctx: ProjectContext = {
      authState: 'authenticated_member',
      role: 'member',
      visibility: 'public',
    };
    expect(can('delete_project', ctx)).toBe(false);
    expect(can('transfer_ownership', ctx)).toBe(false);
  });
});
