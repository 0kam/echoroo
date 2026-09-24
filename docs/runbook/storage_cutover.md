# Storage Cutover Runbook

**Status**: pre-launch maintenance procedure
**Scope**: storage migration slice 4b
**Owner**: release driver and operations

This is a destructive, empty-deployment cutover. Per decision 9, existing
LocalStack objects are not migrated. Existing dev, preview, and ninjin
deployments are recreated with an empty database and an empty application
storage tree.

## Cutover

1. Schedule a maintenance window and, on the Docker host, stop the frontend,
   API, Celery workers, beat, Redis, PostgreSQL, and LocalStack explicitly. Do
   not start the new version while old processes can write.

   ```bash
   docker compose stop frontend backend worker worker-cpu beat redis db localstack
   ```

2. Confirm that any required pre-cutover records have been handled according
   to the deployment decision. On the Docker host, discard the existing
   PostgreSQL database volume and LocalStack data directory. LocalStack is
   retained only for KMS in the new stack; no old application objects are
   copied.

   ```bash
   docker compose down --remove-orphans
   docker volume rm <project>_db-data
   rm -rf ./.data/localstack
   ```

3. Mount the host's Lustre filesystem and create the production storage-tree
   directory. `/lustre/echoroo/storage` is the documented example host
   directory; replace it with the actual mount point. The application-owned
   root must be owned by UID/GID `1000:1000` and have mode `0750`.
4. From the Docker host, run the provisioner inside the backend container so
   it runs as the container's UID/GID 1000 against the mounted path:

   ```bash
   docker compose run --rm backend uv run python -m \
     echoroo.scripts.provision_storage /data/storage
   ```

   The provisioner writes `.echoroo-storage` and runs the full
   `ensure_ready(full=True)` filesystem probe. Treat a failed probe as a
   failed mount or permissions check; do not create a replacement tree on
   local disk.
5. Start the new version. Run migrations and the normal initial setup again,
   including creation of the first administrator and its TOTP enrollment.
6. Check `/health/ready` and confirm that its component is named `storage`.
   Then test login, upload/import, recording playback, search-reference audio,
   and audit-log export before ending the maintenance window.

## Production bind-mount layout

Use directories on the same Lustre mount and bind-mount the same container
paths in the API and every Celery worker. `search_tmp` contains only the job
manifest; uploaded reference audio is stored under `STORAGE_ROOT`.

| Host Lustre directory | Container path | Setting / use |
| --- | --- | --- |
| `/lustre/echoroo/storage` | `/data/storage` | `STORAGE_ROOT`; recordings, models, references, audit archives |
| `/lustre/echoroo/upload_staging` | `/data/upload_staging` | `UPLOAD_STAGING_DIR`; chunk staging |
| `/lustre/echoroo/audio_compressed` | `/data/audio_compressed` | `COMPRESSED_CACHE_DIR`; disposable OGG cache |
| `/lustre/echoroo/search_tmp` | `/data/search_tmp` | Shared search job manifests only |

The API and all workers must use the same values for `STORAGE_ROOT`,
`UPLOAD_STAGING_DIR`, `COMPRESSED_CACHE_DIR`, and the `/data/search_tmp` path.
Keep PostgreSQL and Redis on local disk. The storage root is application-owned;
published files and directories must remain writable by UID/GID 1000, while
the upload staging area keeps its stricter staging permissions.
