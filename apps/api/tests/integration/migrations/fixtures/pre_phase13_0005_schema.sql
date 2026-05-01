--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: annotationsource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.annotationsource AS ENUM (
    'human',
    'model'
);


--
-- Name: annotationvotesource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.annotationvotesource AS ENUM (
    'member',
    'guest_authenticated',
    'trusted_user'
);


--
-- Name: datasetstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.datasetstatus AS ENUM (
    'pending',
    'scanning',
    'processing',
    'completed',
    'failed'
);


--
-- Name: datasetvisibility; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.datasetvisibility AS ENUM (
    'private',
    'public'
);


--
-- Name: detectionsource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.detectionsource AS ENUM (
    'birdnet',
    'perch_search',
    'human'
);


--
-- Name: detectionstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.detectionstatus AS ENUM (
    'unreviewed',
    'confirmed',
    'rejected'
);


--
-- Name: invitationkind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.invitationkind AS ENUM (
    'member',
    'trusted'
);


--
-- Name: invitationstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.invitationstatus AS ENUM (
    'pending',
    'accepted',
    'declined',
    'expired',
    'revoked'
);


--
-- Name: projectlicense; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.projectlicense AS ENUM (
    'CC0',
    'CC-BY',
    'CC-BY-NC',
    'CC-BY-SA'
);


--
-- Name: projectmemberrole; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.projectmemberrole AS ENUM (
    'viewer',
    'member',
    'admin'
);


--
-- Name: projectstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.projectstatus AS ENUM (
    'active',
    'dormant',
    'archived'
);


--
-- Name: projectvisibility; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.projectvisibility AS ENUM (
    'public',
    'restricted'
);


--
-- Name: tagcategory; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.tagcategory AS ENUM (
    'species',
    'sound_type',
    'quality'
);


--
-- Name: taxonoverrideapprovalstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.taxonoverrideapprovalstatus AS ENUM (
    'applied',
    'pending_superuser_approval',
    'rejected'
);


--
-- Name: taxonoverridedirection; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.taxonoverridedirection AS ENUM (
    'stricter',
    'looser'
);


--
-- Name: taxonsensitivitysource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.taxonsensitivitysource AS ENUM (
    'iucn',
    'moe_rdb',
    'manual'
);


--
-- Name: trusteduserstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.trusteduserstatus AS ENUM (
    'active',
    'expired',
    'revoked'
);


--
-- Name: forbid_audit_log_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.forbid_audit_log_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$;


--
-- Name: prevent_last_superuser_deletion(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_last_superuser_deletion() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF current_user = 'echoroo_app' THEN
                IF (SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL) <= 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot delete last superuser without creator_founder override';
                    END IF;
                END IF;
            END IF;
            RETURN OLD;
        END;
        $$;


SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: annotation_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annotation_comments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    annotation_id uuid NOT NULL,
    commenter_user_id uuid NOT NULL,
    project_id uuid NOT NULL,
    body text NOT NULL,
    source public.annotationvotesource NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: annotation_votes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annotation_votes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    annotation_id uuid NOT NULL,
    voter_user_id uuid NOT NULL,
    project_id uuid NOT NULL,
    vote smallint NOT NULL,
    source public.annotationvotesource NOT NULL,
    project_role_at_vote public.projectmemberrole,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_annotation_votes_source_role_consistency CHECK ((((source = 'member'::public.annotationvotesource) AND (project_role_at_vote IS NOT NULL)) OR ((source = ANY (ARRAY['guest_authenticated'::public.annotationvotesource, 'trusted_user'::public.annotationvotesource])) AND (project_role_at_vote IS NULL))))
);


--
-- Name: annotations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.annotations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    detection_id uuid NOT NULL,
    user_id uuid,
    source public.annotationsource NOT NULL,
    taxon_id character varying(64),
    label character varying(200),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: api_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    prefix character varying(20) NOT NULL,
    hashed_secret character varying(64) NOT NULL,
    granted_permissions jsonb NOT NULL,
    project_id uuid,
    allowed_ip_cidrs character varying[],
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    revoked_reason character varying(100),
    last_used_at timestamp with time zone,
    scope_violation_count_10min integer DEFAULT 0 NOT NULL,
    ip_violation_count integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_api_keys_expires_at_window CHECK (((expires_at > created_at) AND (expires_at <= (created_at + '2 years'::interval)))),
    CONSTRAINT ck_api_keys_granted_permissions_array CHECK ((jsonb_typeof(granted_permissions) = 'array'::text))
);


--
-- Name: datasets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.datasets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    status public.datasetstatus DEFAULT 'pending'::public.datasetstatus NOT NULL,
    visibility public.datasetvisibility DEFAULT 'private'::public.datasetvisibility NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: dek_rewrap_failures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dek_rewrap_failures (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    table_name character varying(100) NOT NULL,
    row_id uuid NOT NULL,
    attempted_at timestamp with time zone NOT NULL,
    error_detail text NOT NULL,
    resolved_at timestamp with time zone
);


--
-- Name: detections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.detections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    recording_id uuid NOT NULL,
    project_id uuid NOT NULL,
    taxon_id character varying(64),
    source public.detectionsource NOT NULL,
    status public.detectionstatus DEFAULT 'unreviewed'::public.detectionstatus NOT NULL,
    start_time double precision NOT NULL,
    end_time double precision NOT NULL,
    confidence double precision,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: iucn_sync_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.iucn_sync_attempts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    status character varying(20) NOT NULL,
    error_detail text,
    synced_count integer,
    loosened_species_count integer
);


--
-- Name: outbox_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.outbox_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    event_type character varying(100) NOT NULL,
    payload jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    retry_count integer DEFAULT 0 NOT NULL,
    next_retry_at timestamp with time zone,
    processed_at timestamp with time zone,
    last_error text,
    idempotency_key character varying(128)
);


--
-- Name: password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.password_reset_tokens (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    requested_ip character varying(45),
    requested_user_agent character varying(500),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: platform_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.platform_audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    actor_user_id_hash character varying(64) NOT NULL,
    action character varying(100) NOT NULL,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    request_id character varying(64) NOT NULL,
    ip_hash character varying(64) NOT NULL,
    user_agent_hash character varying(64) NOT NULL,
    before jsonb,
    after jsonb,
    prev_hash character varying(64) NOT NULL,
    row_hash character varying(64) NOT NULL
);


--
-- Name: project_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_audit_log (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    actor_user_id_hash character varying(64) NOT NULL,
    project_id uuid,
    action character varying(100) NOT NULL,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    request_id character varying(64) NOT NULL,
    ip_hash character varying(64) NOT NULL,
    user_agent_hash character varying(64) NOT NULL,
    before jsonb,
    after jsonb,
    prev_hash character varying(64) NOT NULL,
    row_hash character varying(64) NOT NULL,
    CONSTRAINT ck_project_audit_log_project_id_required CHECK ((((action)::text = 'genesis'::text) OR (project_id IS NOT NULL)))
);


--
-- Name: project_invitations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_invitations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    kind public.invitationkind NOT NULL,
    email character varying(255),
    email_hash character varying(64) NOT NULL,
    role public.projectmemberrole,
    granted_permissions jsonb,
    trusted_duration_seconds integer,
    token_hash character varying(64) NOT NULL,
    invited_by_id uuid NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone,
    declined_at timestamp with time zone,
    revoked_at timestamp with time zone,
    status public.invitationstatus DEFAULT 'pending'::public.invitationstatus NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_project_invitations_kind_fields CHECK (((kind IS NOT NULL) AND (status IS NOT NULL) AND (((kind = 'member'::public.invitationkind) AND (role IS NOT NULL) AND (granted_permissions IS NULL) AND (trusted_duration_seconds IS NULL)) OR ((kind = 'trusted'::public.invitationkind) AND (role IS NULL) AND (jsonb_typeof(granted_permissions) = 'array'::text) AND (trusted_duration_seconds IS NOT NULL) AND ((trusted_duration_seconds >= 1) AND (trusted_duration_seconds <= 31536000)))))),
    CONSTRAINT ck_project_invitations_status_timestamps CHECK ((((status = 'accepted'::public.invitationstatus) AND (accepted_at IS NOT NULL) AND (declined_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'declined'::public.invitationstatus) AND (declined_at IS NOT NULL) AND (accepted_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::public.invitationstatus) AND (revoked_at IS NOT NULL)) OR ((status = 'pending'::public.invitationstatus) AND (accepted_at IS NULL) AND (declined_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'expired'::public.invitationstatus) AND (accepted_at IS NULL) AND (declined_at IS NULL))))
);


--
-- Name: project_license_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_license_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    old_license public.projectlicense,
    new_license public.projectlicense NOT NULL,
    changed_at timestamp with time zone NOT NULL,
    changed_by_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: project_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role public.projectmemberrole NOT NULL,
    joined_at timestamp with time zone NOT NULL,
    invited_by_id uuid,
    expires_at timestamp with time zone,
    removed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_project_members_viewer_expires CHECK (((role = 'viewer'::public.projectmemberrole) OR (expires_at IS NULL)))
);


--
-- Name: project_taxon_sensitivity_overrides; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_taxon_sensitivity_overrides (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    taxon_id character varying(64) NOT NULL,
    sensitivity_h3_res integer NOT NULL,
    direction public.taxonoverridedirection NOT NULL,
    approval_status public.taxonoverrideapprovalstatus DEFAULT 'applied'::public.taxonoverrideapprovalstatus NOT NULL,
    requested_by_id uuid NOT NULL,
    approved_by_id uuid,
    approved_at timestamp with time zone,
    rejected_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_taxon_overrides_direction_vs_approval CHECK ((((direction = 'stricter'::public.taxonoverridedirection) AND (approval_status = 'applied'::public.taxonoverrideapprovalstatus)) OR ((direction = 'looser'::public.taxonoverridedirection) AND (approval_status = ANY (ARRAY['pending_superuser_approval'::public.taxonoverrideapprovalstatus, 'applied'::public.taxonoverrideapprovalstatus, 'rejected'::public.taxonoverrideapprovalstatus]))))),
    CONSTRAINT ck_taxon_overrides_h3_discrete CHECK ((sensitivity_h3_res = ANY (ARRAY[2, 5, 7, 9, 15])))
);


--
-- Name: project_trusted_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_trusted_users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    user_id uuid NOT NULL,
    invitation_id uuid NOT NULL,
    granted_by_id uuid NOT NULL,
    granted_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status public.trusteduserstatus DEFAULT 'active'::public.trusteduserstatus NOT NULL,
    granted_permissions jsonb NOT NULL,
    email_at_invitation character varying(255),
    email_at_invitation_hash character varying(64) NOT NULL,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_trusted_users_duration_within_one_year CHECK (((expires_at > granted_at) AND (expires_at <= (granted_at + '1 year'::interval)))),
    CONSTRAINT ck_trusted_users_permissions_non_empty_array CHECK (((jsonb_typeof(granted_permissions) = 'array'::text) AND (jsonb_array_length(granted_permissions) > 0)))
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    owner_id uuid NOT NULL,
    visibility public.projectvisibility NOT NULL,
    license public.projectlicense NOT NULL,
    restricted_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    restricted_config_version integer DEFAULT 1 NOT NULL,
    status public.projectstatus DEFAULT 'active'::public.projectstatus NOT NULL,
    dormant_since timestamp with time zone,
    archived_since timestamp with time zone,
    review_min_votes integer DEFAULT 2 NOT NULL,
    review_consensus_threshold double precision DEFAULT 0.667 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_projects_restricted_config_shape CHECK (((restricted_config IS NOT NULL) AND (jsonb_typeof(restricted_config) = 'object'::text) AND ((visibility <> 'restricted'::public.projectvisibility) OR ((restricted_config ? 'allow_media_playback'::text) AND (restricted_config ? 'allow_detection_view'::text) AND (restricted_config ? 'mask_species_in_detection'::text) AND (restricted_config ? 'allow_download'::text) AND (restricted_config ? 'allow_export'::text) AND (restricted_config ? 'allow_voting_and_comments'::text) AND (restricted_config ? 'public_location_precision_h3_res'::text) AND (restricted_config ? 'allow_precise_location_to_viewer'::text)))))
);


--
-- Name: recordings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.recordings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    dataset_id uuid,
    site_id uuid,
    path text NOT NULL,
    duration_seconds double precision,
    sample_rate integer,
    channels integer,
    recorded_at timestamp with time zone,
    h3_index_member character varying(32),
    h3_index_member_resolution integer,
    gps_stripped boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.refresh_tokens (
    jti uuid NOT NULL,
    user_id uuid NOT NULL,
    family_id uuid NOT NULL,
    issued_at timestamp with time zone DEFAULT now() NOT NULL,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sites; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sites (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    h3_index_member character varying(32) NOT NULL,
    h3_index_member_resolution integer DEFAULT 15 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_sites_h3_member_resolution CHECK ((h3_index_member_resolution = ANY (ARRAY[9, 15])))
);


--
-- Name: superuser_approval_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.superuser_approval_requests (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    action character varying(100) NOT NULL,
    detail jsonb NOT NULL,
    requested_by_id uuid,
    requesting_user_id uuid,
    approvals jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    executed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_superuser_approval_requests_actor_present CHECK (((requested_by_id IS NOT NULL) <> (requesting_user_id IS NOT NULL)))
);


--
-- Name: superusers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.superusers (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    added_by_id uuid,
    added_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    webauthn_credentials jsonb DEFAULT '[]'::jsonb NOT NULL,
    allowed_ip_cidrs character varying[] DEFAULT ARRAY[]::character varying[] NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: system_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_settings (
    key character varying(100) NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by_id uuid
);


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tags (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    category public.tagcategory NOT NULL,
    name character varying(200) NOT NULL,
    taxon_id character varying(64),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: taxon_sensitivities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxon_sensitivities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    taxon_id character varying(64) NOT NULL,
    source public.taxonsensitivitysource NOT NULL,
    category character varying(10),
    sensitivity_h3_res integer NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_taxon_sensitivities_h3_discrete CHECK ((sensitivity_h3_res = ANY (ARRAY[2, 5, 7, 9, 15])))
);


--
-- Name: token_families; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_families (
    family_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone
);


--
-- Name: user_login_notifications_seen; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_login_notifications_seen (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    ip_hash character varying(64) NOT NULL,
    ua_hash character varying(64) NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    display_name character varying(100),
    two_factor_enabled boolean DEFAULT false NOT NULL,
    two_factor_secret_encrypted bytea,
    two_factor_secret_dek_version integer,
    two_factor_backup_codes_hashed character varying[],
    security_stamp character varying(64) NOT NULL,
    last_login_at timestamp with time zone,
    last_first_party_activity_at timestamp with time zone,
    registered_timezone character varying(64),
    deleted_at timestamp with time zone,
    two_factor_reset_cooldown_until timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: wipe_guard; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wipe_guard (
    id integer DEFAULT 1 NOT NULL,
    wiped_at timestamp with time zone NOT NULL,
    wiped_by_superuser_ids character varying[] NOT NULL,
    CONSTRAINT ck_wipe_guard_singleton CHECK ((id = 1))
);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.alembic_version VALUES ('0005');


--
-- Data for Name: annotation_comments; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: annotation_votes; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: annotations; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: api_keys; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: datasets; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: dek_rewrap_failures; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: detections; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: iucn_sync_attempts; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: outbox_events; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: password_reset_tokens; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: platform_audit_log; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.platform_audit_log VALUES ('79634b8a-c873-4200-9d3b-116e650909e4', '2026-04-29 08:00:30.957644+00', '0000000000000000000000000000000000000000000000000000000000000000', 'genesis', '{}', 'genesis', '0000000000000000000000000000000000000000000000000000000000000000', '0000000000000000000000000000000000000000000000000000000000000000', NULL, NULL, '0000000000000000000000000000000000000000000000000000000000000000', '0000000000000000000000000000000000000000000000000000000000000000');


--
-- Data for Name: project_audit_log; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.project_audit_log VALUES ('6df8b895-f36f-46d1-8132-6e297ffc6fc5', '2026-04-29 08:00:30.957644+00', '0000000000000000000000000000000000000000000000000000000000000000', NULL, 'genesis', '{}', 'genesis', '0000000000000000000000000000000000000000000000000000000000000000', '0000000000000000000000000000000000000000000000000000000000000000', NULL, NULL, '0000000000000000000000000000000000000000000000000000000000000000', '0000000000000000000000000000000000000000000000000000000000000000');


--
-- Data for Name: project_invitations; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: project_license_history; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: project_members; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: project_taxon_sensitivity_overrides; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: project_trusted_users; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: projects; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: recordings; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: refresh_tokens; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sites; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: superuser_approval_requests; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: superusers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: system_settings; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.system_settings VALUES ('trusted_default_duration_seconds', '7776000', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('trusted_max_duration_seconds', '31536000', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('dormant_threshold_seconds', '31622400', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('api_key_rotation_warn_days', '90', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('api_key_scope_violation_window_seconds', '600', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('api_key_scope_violation_threshold', '10', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('totp_verify_window_per_15min', '5', '2026-04-29 08:00:30.957644+00', NULL);
INSERT INTO public.system_settings VALUES ('totp_lockout_threshold', '10', '2026-04-29 08:00:30.957644+00', NULL);


--
-- Data for Name: tags; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: taxon_sensitivities; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: token_families; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_login_notifications_seen; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: wipe_guard; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: annotation_comments annotation_comments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_comments
    ADD CONSTRAINT annotation_comments_pkey PRIMARY KEY (id);


--
-- Name: annotation_votes annotation_votes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_votes
    ADD CONSTRAINT annotation_votes_pkey PRIMARY KEY (id);


--
-- Name: annotations annotations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotations
    ADD CONSTRAINT annotations_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);


--
-- Name: api_keys api_keys_prefix_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_prefix_key UNIQUE (prefix);


--
-- Name: datasets datasets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_pkey PRIMARY KEY (id);


--
-- Name: dek_rewrap_failures dek_rewrap_failures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dek_rewrap_failures
    ADD CONSTRAINT dek_rewrap_failures_pkey PRIMARY KEY (id);


--
-- Name: detections detections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT detections_pkey PRIMARY KEY (id);


--
-- Name: iucn_sync_attempts iucn_sync_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.iucn_sync_attempts
    ADD CONSTRAINT iucn_sync_attempts_pkey PRIMARY KEY (id);


--
-- Name: outbox_events outbox_events_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT outbox_events_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: outbox_events outbox_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.outbox_events
    ADD CONSTRAINT outbox_events_pkey PRIMARY KEY (id);


--
-- Name: password_reset_tokens password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id);


--
-- Name: password_reset_tokens password_reset_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: platform_audit_log platform_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_audit_log
    ADD CONSTRAINT platform_audit_log_pkey PRIMARY KEY (id);


--
-- Name: project_audit_log project_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_audit_log
    ADD CONSTRAINT project_audit_log_pkey PRIMARY KEY (id);


--
-- Name: project_invitations project_invitations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_invitations
    ADD CONSTRAINT project_invitations_pkey PRIMARY KEY (id);


--
-- Name: project_invitations project_invitations_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_invitations
    ADD CONSTRAINT project_invitations_token_hash_key UNIQUE (token_hash);


--
-- Name: project_license_history project_license_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_license_history
    ADD CONSTRAINT project_license_history_pkey PRIMARY KEY (id);


--
-- Name: project_members project_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_pkey PRIMARY KEY (id);


--
-- Name: project_taxon_sensitivity_overrides project_taxon_sensitivity_overrides_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_taxon_sensitivity_overrides
    ADD CONSTRAINT project_taxon_sensitivity_overrides_pkey PRIMARY KEY (id);


--
-- Name: project_trusted_users project_trusted_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_trusted_users
    ADD CONSTRAINT project_trusted_users_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: recordings recordings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recordings
    ADD CONSTRAINT recordings_pkey PRIMARY KEY (id);


--
-- Name: refresh_tokens refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (jti);


--
-- Name: sites sites_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT sites_pkey PRIMARY KEY (id);


--
-- Name: superuser_approval_requests superuser_approval_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superuser_approval_requests
    ADD CONSTRAINT superuser_approval_requests_pkey PRIMARY KEY (id);


--
-- Name: superusers superusers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superusers
    ADD CONSTRAINT superusers_pkey PRIMARY KEY (id);


--
-- Name: superusers superusers_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superusers
    ADD CONSTRAINT superusers_user_id_key UNIQUE (user_id);


--
-- Name: system_settings system_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (key);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);


--
-- Name: taxon_sensitivities taxon_sensitivities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxon_sensitivities
    ADD CONSTRAINT taxon_sensitivities_pkey PRIMARY KEY (id);


--
-- Name: token_families token_families_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_families
    ADD CONSTRAINT token_families_pkey PRIMARY KEY (family_id);


--
-- Name: user_login_notifications_seen uq_user_login_notifications_seen_tuple; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_login_notifications_seen
    ADD CONSTRAINT uq_user_login_notifications_seen_tuple UNIQUE (user_id, ip_hash, ua_hash);


--
-- Name: user_login_notifications_seen user_login_notifications_seen_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_login_notifications_seen
    ADD CONSTRAINT user_login_notifications_seen_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: sites ux_sites_project_h3; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT ux_sites_project_h3 UNIQUE (project_id, h3_index_member);


--
-- Name: sites ux_sites_project_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT ux_sites_project_name UNIQUE (project_id, name);


--
-- Name: tags ux_tags_project_category_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT ux_tags_project_category_name UNIQUE (project_id, category, name);


--
-- Name: taxon_sensitivities ux_taxon_sensitivities_taxon_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxon_sensitivities
    ADD CONSTRAINT ux_taxon_sensitivities_taxon_source UNIQUE (taxon_id, source);


--
-- Name: wipe_guard wipe_guard_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wipe_guard
    ADD CONSTRAINT wipe_guard_pkey PRIMARY KEY (id);


--
-- Name: ix_annotation_comments_annotation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_comments_annotation ON public.annotation_comments USING btree (annotation_id);


--
-- Name: ix_annotation_votes_annotation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_votes_annotation ON public.annotation_votes USING btree (annotation_id);


--
-- Name: ix_annotation_votes_project_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotation_votes_project_source ON public.annotation_votes USING btree (project_id, source);


--
-- Name: ix_annotations_detection; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_annotations_detection ON public.annotations USING btree (detection_id);


--
-- Name: ix_api_keys_expires_at_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_expires_at_active ON public.api_keys USING btree (expires_at) WHERE (revoked_at IS NULL);


--
-- Name: ix_api_keys_project_revoked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_project_revoked ON public.api_keys USING btree (project_id, revoked_at);


--
-- Name: ix_api_keys_user_revoked; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_keys_user_revoked ON public.api_keys USING btree (user_id, revoked_at);


--
-- Name: ix_datasets_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_datasets_project_id ON public.datasets USING btree (project_id);


--
-- Name: ix_detections_project_taxon; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_detections_project_taxon ON public.detections USING btree (project_id, taxon_id);


--
-- Name: ix_detections_recording; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_detections_recording ON public.detections USING btree (recording_id);


--
-- Name: ix_iucn_sync_attempts_status_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_iucn_sync_attempts_status_started ON public.iucn_sync_attempts USING btree (status, started_at DESC);


--
-- Name: ix_outbox_events_event_type_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_event_type_created ON public.outbox_events USING btree (event_type, created_at DESC);


--
-- Name: ix_outbox_events_status_next_retry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_outbox_events_status_next_retry ON public.outbox_events USING btree (status, next_retry_at) WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'processing'::character varying])::text[]));


--
-- Name: ix_password_reset_tokens_token_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_token_hash ON public.password_reset_tokens USING btree (token_hash);


--
-- Name: ix_password_reset_tokens_user_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_password_reset_tokens_user_expires ON public.password_reset_tokens USING btree (user_id, expires_at);


--
-- Name: ix_platform_audit_log_action_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_platform_audit_log_action_created ON public.platform_audit_log USING btree (action, created_at DESC);


--
-- Name: ix_platform_audit_log_actor_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_platform_audit_log_actor_created ON public.platform_audit_log USING btree (actor_user_id_hash, created_at DESC);


--
-- Name: ix_project_audit_log_action_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_audit_log_action_created ON public.project_audit_log USING btree (action, created_at DESC);


--
-- Name: ix_project_audit_log_actor_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_audit_log_actor_created ON public.project_audit_log USING btree (actor_user_id_hash, created_at DESC);


--
-- Name: ix_project_audit_log_project_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_audit_log_project_created ON public.project_audit_log USING btree (project_id, created_at DESC);


--
-- Name: ix_project_invitations_status_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_invitations_status_expires ON public.project_invitations USING btree (status, expires_at);


--
-- Name: ix_project_license_history_project_changed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_license_history_project_changed_at ON public.project_license_history USING btree (project_id, changed_at DESC);


--
-- Name: ix_project_members_project_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_members_project_role ON public.project_members USING btree (project_id, role);


--
-- Name: ix_project_members_user_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_members_user_project ON public.project_members USING btree (user_id, project_id) WHERE (removed_at IS NULL);


--
-- Name: ix_project_trusted_users_project_user_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_trusted_users_project_user_status ON public.project_trusted_users USING btree (project_id, user_id, status);


--
-- Name: ix_project_trusted_users_status_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_project_trusted_users_status_expires ON public.project_trusted_users USING btree (status, expires_at);


--
-- Name: ix_projects_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_owner_id ON public.projects USING btree (owner_id);


--
-- Name: ix_projects_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_status ON public.projects USING btree (status);


--
-- Name: ix_projects_status_dormant_since; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_status_dormant_since ON public.projects USING btree (status, dormant_since DESC);


--
-- Name: ix_projects_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_visibility ON public.projects USING btree (visibility);


--
-- Name: ix_recordings_dataset_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recordings_dataset_id ON public.recordings USING btree (dataset_id);


--
-- Name: ix_recordings_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recordings_project_id ON public.recordings USING btree (project_id);


--
-- Name: ix_recordings_site_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_recordings_site_id ON public.recordings USING btree (site_id);


--
-- Name: ix_refresh_tokens_consumed_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_consumed_at ON public.refresh_tokens USING btree (consumed_at) WHERE (consumed_at IS NULL);


--
-- Name: ix_refresh_tokens_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_expires_at ON public.refresh_tokens USING btree (expires_at);


--
-- Name: ix_refresh_tokens_family_jti; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_refresh_tokens_family_jti ON public.refresh_tokens USING btree (family_id, jti);


--
-- Name: ix_refresh_tokens_user_family; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_refresh_tokens_user_family ON public.refresh_tokens USING btree (user_id, family_id);


--
-- Name: ix_sites_h3_index_member; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sites_h3_index_member ON public.sites USING btree (h3_index_member);


--
-- Name: ix_superusers_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_superusers_revoked_at ON public.superusers USING btree (revoked_at);


--
-- Name: ix_tags_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_tags_project_id ON public.tags USING btree (project_id);


--
-- Name: ix_taxon_overrides_taxon_approval; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxon_overrides_taxon_approval ON public.project_taxon_sensitivity_overrides USING btree (taxon_id, approval_status);


--
-- Name: ix_taxon_sensitivities_source_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxon_sensitivities_source_updated ON public.taxon_sensitivities USING btree (source, updated_at DESC);


--
-- Name: ix_taxon_sensitivities_taxon; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_taxon_sensitivities_taxon ON public.taxon_sensitivities USING btree (taxon_id);


--
-- Name: ix_token_families_revoked_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_families_revoked_at ON public.token_families USING btree (revoked_at);


--
-- Name: ix_token_families_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_token_families_user_id ON public.token_families USING btree (user_id);


--
-- Name: ix_user_login_notifications_seen_user_id_last_seen_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_login_notifications_seen_user_id_last_seen_at ON public.user_login_notifications_seen USING btree (user_id, last_seen_at);


--
-- Name: ix_users_deleted_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_deleted_at ON public.users USING btree (deleted_at);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ux_project_invitations_pending; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_project_invitations_pending ON public.project_invitations USING btree (project_id, email_hash) WHERE (status = 'pending'::public.invitationstatus);


--
-- Name: ux_project_members_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_project_members_active ON public.project_members USING btree (project_id, user_id) WHERE (removed_at IS NULL);


--
-- Name: ux_project_trusted_users_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_project_trusted_users_active ON public.project_trusted_users USING btree (project_id, user_id) WHERE (status = 'active'::public.trusteduserstatus);


--
-- Name: ux_taxon_overrides_applied_unique; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_taxon_overrides_applied_unique ON public.project_taxon_sensitivity_overrides USING btree (project_id, taxon_id) WHERE (approval_status = 'applied'::public.taxonoverrideapprovalstatus);


--
-- Name: platform_audit_log platform_audit_log_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER platform_audit_log_immutable BEFORE DELETE OR UPDATE ON public.platform_audit_log FOR EACH ROW EXECUTE FUNCTION public.forbid_audit_log_mutation();


--
-- Name: project_audit_log project_audit_log_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER project_audit_log_immutable BEFORE DELETE OR UPDATE ON public.project_audit_log FOR EACH ROW EXECUTE FUNCTION public.forbid_audit_log_mutation();


--
-- Name: superusers superuser_last_protection; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER superuser_last_protection BEFORE DELETE ON public.superusers FOR EACH ROW EXECUTE FUNCTION public.prevent_last_superuser_deletion();


--
-- Name: annotation_comments annotation_comments_annotation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_comments
    ADD CONSTRAINT annotation_comments_annotation_id_fkey FOREIGN KEY (annotation_id) REFERENCES public.annotations(id) ON DELETE CASCADE;


--
-- Name: annotation_comments annotation_comments_commenter_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_comments
    ADD CONSTRAINT annotation_comments_commenter_user_id_fkey FOREIGN KEY (commenter_user_id) REFERENCES public.users(id);


--
-- Name: annotation_comments annotation_comments_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_comments
    ADD CONSTRAINT annotation_comments_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: annotation_votes annotation_votes_annotation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_votes
    ADD CONSTRAINT annotation_votes_annotation_id_fkey FOREIGN KEY (annotation_id) REFERENCES public.annotations(id) ON DELETE CASCADE;


--
-- Name: annotation_votes annotation_votes_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_votes
    ADD CONSTRAINT annotation_votes_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: annotation_votes annotation_votes_voter_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotation_votes
    ADD CONSTRAINT annotation_votes_voter_user_id_fkey FOREIGN KEY (voter_user_id) REFERENCES public.users(id);


--
-- Name: annotations annotations_detection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotations
    ADD CONSTRAINT annotations_detection_id_fkey FOREIGN KEY (detection_id) REFERENCES public.detections(id) ON DELETE CASCADE;


--
-- Name: annotations annotations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.annotations
    ADD CONSTRAINT annotations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: api_keys api_keys_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: api_keys api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_keys
    ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: datasets datasets_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: detections detections_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT detections_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: detections detections_recording_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.detections
    ADD CONSTRAINT detections_recording_id_fkey FOREIGN KEY (recording_id) REFERENCES public.recordings(id) ON DELETE CASCADE;


--
-- Name: superuser_approval_requests fk_superuser_approval_requests_requesting_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superuser_approval_requests
    ADD CONSTRAINT fk_superuser_approval_requests_requesting_user_id FOREIGN KEY (requesting_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: password_reset_tokens password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.password_reset_tokens
    ADD CONSTRAINT password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: project_audit_log project_audit_log_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_audit_log
    ADD CONSTRAINT project_audit_log_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: project_invitations project_invitations_invited_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_invitations
    ADD CONSTRAINT project_invitations_invited_by_id_fkey FOREIGN KEY (invited_by_id) REFERENCES public.users(id);


--
-- Name: project_invitations project_invitations_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_invitations
    ADD CONSTRAINT project_invitations_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_license_history project_license_history_changed_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_license_history
    ADD CONSTRAINT project_license_history_changed_by_id_fkey FOREIGN KEY (changed_by_id) REFERENCES public.users(id);


--
-- Name: project_license_history project_license_history_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_license_history
    ADD CONSTRAINT project_license_history_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_members project_members_invited_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_invited_by_id_fkey FOREIGN KEY (invited_by_id) REFERENCES public.users(id);


--
-- Name: project_members project_members_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_members project_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_members
    ADD CONSTRAINT project_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE RESTRICT;


--
-- Name: project_taxon_sensitivity_overrides project_taxon_sensitivity_overrides_approved_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_taxon_sensitivity_overrides
    ADD CONSTRAINT project_taxon_sensitivity_overrides_approved_by_id_fkey FOREIGN KEY (approved_by_id) REFERENCES public.superusers(id);


--
-- Name: project_taxon_sensitivity_overrides project_taxon_sensitivity_overrides_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_taxon_sensitivity_overrides
    ADD CONSTRAINT project_taxon_sensitivity_overrides_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_taxon_sensitivity_overrides project_taxon_sensitivity_overrides_requested_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_taxon_sensitivity_overrides
    ADD CONSTRAINT project_taxon_sensitivity_overrides_requested_by_id_fkey FOREIGN KEY (requested_by_id) REFERENCES public.users(id);


--
-- Name: project_trusted_users project_trusted_users_granted_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_trusted_users
    ADD CONSTRAINT project_trusted_users_granted_by_id_fkey FOREIGN KEY (granted_by_id) REFERENCES public.users(id);


--
-- Name: project_trusted_users project_trusted_users_invitation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_trusted_users
    ADD CONSTRAINT project_trusted_users_invitation_id_fkey FOREIGN KEY (invitation_id) REFERENCES public.project_invitations(id);


--
-- Name: project_trusted_users project_trusted_users_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_trusted_users
    ADD CONSTRAINT project_trusted_users_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_trusted_users project_trusted_users_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_trusted_users
    ADD CONSTRAINT project_trusted_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: projects projects_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- Name: recordings recordings_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recordings
    ADD CONSTRAINT recordings_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(id) ON DELETE CASCADE;


--
-- Name: recordings recordings_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recordings
    ADD CONSTRAINT recordings_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: recordings recordings_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.recordings
    ADD CONSTRAINT recordings_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.sites(id) ON DELETE SET NULL;


--
-- Name: refresh_tokens refresh_tokens_family_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_family_id_fkey FOREIGN KEY (family_id) REFERENCES public.token_families(family_id) ON DELETE CASCADE;


--
-- Name: refresh_tokens refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: sites sites_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT sites_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: superuser_approval_requests superuser_approval_requests_requested_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superuser_approval_requests
    ADD CONSTRAINT superuser_approval_requests_requested_by_id_fkey FOREIGN KEY (requested_by_id) REFERENCES public.superusers(id);


--
-- Name: superusers superusers_added_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superusers
    ADD CONSTRAINT superusers_added_by_id_fkey FOREIGN KEY (added_by_id) REFERENCES public.users(id);


--
-- Name: superusers superusers_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.superusers
    ADD CONSTRAINT superusers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: system_settings system_settings_updated_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_settings
    ADD CONSTRAINT system_settings_updated_by_id_fkey FOREIGN KEY (updated_by_id) REFERENCES public.superusers(id);


--
-- Name: tags tags_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: token_families token_families_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_families
    ADD CONSTRAINT token_families_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_login_notifications_seen user_login_notifications_seen_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_login_notifications_seen
    ADD CONSTRAINT user_login_notifications_seen_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


