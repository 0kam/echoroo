# Quickstart — Zero-email Deployment

**Audience**: An ecologist setting up Echoroo for their lab. Assumes only `git`, `docker`, and a web browser. No SMTP, Resend, Mailpit, DKIM, DNS, or transactional email service is required.

## 1. Get the application

```bash
git clone <repo-url>
cd echoroo
cp .env.example .env
```

Open `.env` in a text editor. The only fields you need to set:

- `ECHOROO_INITIAL_SUPERUSER_EMAIL` — your email (used as your login identifier; not verified anywhere).
- `ECHOROO_DB_PASSWORD` — a random string of your choosing.

**You do not need to set any `RESEND_*`, `EMAIL_*`, or `SMTP_*` variable**. They are not present in the example file, and the application uses no outbound email under any circumstance.

## 2. Start the application

```bash
./scripts/docker.sh dev
```

Wait ~30 seconds for the stack to come up. Open <http://localhost:3000>.

## 3. Set up the system superuser

On first launch, the setup wizard prompts for the system superuser email and password. Submit. You are now logged in as the deployment's system superuser.

You will **not** see a "verify your email" banner anywhere. No verification email is sent — none is required.

## 4. Create a project (regular case)

From the dashboard, click **Create project**. Fill the name, choose visibility (Public for browsable, Restricted for invite-only), submit. The project is created with you as owner.

## 5. Onboard collaborators

### Single invite

1. Open the project's **Collaborators** screen.
2. Enter a collaborator's email and role (Viewer / Member / Admin), click **Issue invitation**.
3. A one-shot URL appears: `https://your-host/invite/...`. Click **Copy**.
4. Paste the URL into Slack / lab chat / your own email / a piece of paper — whatever channel you and the collaborator use.

When the collaborator opens the URL:
- If they don't have an account: they sign up using the bound email.
- If they're already logged in with the same email: they click **Accept**.

They land in the project at the role you chose.

### Bulk invite (20 people at once)

1. Same screen, switch to **Bulk mode**.
2. Paste a list of emails (newline-separated, up to 50 at a time).
3. Choose one role to apply to all.
4. A table appears with one URL per email. **Copy as CSV** for easy distribution.

If you close the browser tab before copying, the URLs are **not recoverable**. Revoke and reissue the missing rows from the invitations list.

## 6. Bootstrap a project for a colleague

If you want a colleague to **own** a project (not just join it):

1. **Create project** form.
2. Fill the project name, visibility, and the **Intended owner email** field at the bottom.
3. Submit. The response shows the new project (initially owned by you as a placeholder) plus one invitation URL.
4. Share the URL with the future owner.
5. When they accept, the project's ownership automatically transfers to them, and you are demoted to project Admin. Your activity view shows a composite audit entry summarising what happened.

## 7. Recover a forgotten password

If a collaborator emails you "I forgot my password":

1. Open **Admin → Users**.
2. Find the user, click **Reset password**.
3. You are prompted to **step up** (re-enter your current password and complete a 2FA challenge — TOTP or WebAuthn).
4. Confirm the reset. A click-to-reveal dialog shows a randomly generated temporary password. **Copy** it (the clipboard clears in 60 seconds; the value is not recoverable after you close the dialog).
5. Hand off the temporary password to the user through your usual channel.
6. They log in with it. Echoroo immediately redirects them to the change-password screen and blocks every other route until they pick a new password.

The temporary password is good for 24 hours. After that they need to ask you to reset again.

## 8. Recover a lost 2FA device

Same as §7, but click **Disable 2FA** in the user's admin page. Step-up is still required. After you confirm, the user can log in with their password and re-enroll their 2FA device.

## 9. Notice something suspicious on your own account

A small **!** badge appears at the top of your screen whenever Echoroo has a security-relevant event for you. Click to see:
- Logins from new devices
- API keys that were revoked
- Email changes
- 2FA resets

The full timeline is in **Profile → Activity** (banners only show recent items; activity is permanent).

## Verification — fresh deployment

Run the application's "no email subsystem traces" pytest as a smoke test:

```bash
docker exec echoroo-backend uv run pytest \
  apps/api/tests/contract/test_no_email_subsystem_traces.py -q
```

Pass means the deployment has no Resend / Mailpit / SMTP references anywhere in the active code or configuration.

**You're done.** The remainder of this document is FAQ — naive deployers may stop reading here.

---

## Where to learn more

- `docs/operations/inviting-users.md` — full single + bulk invite walkthroughs
- `docs/operations/admin-recovery-flows.md` — password / 2FA recovery
- `docs/operations/superuser-bootstrap.md` — bootstrap workflow
- `docs/runbook/invitation_token_kid_rotation.md` — operator runbook for invitation token key rotation
- `docs/runbook/zero-email-deployment-secret-rotation.md` — after-deploy CI / Actions secrets cleanup

## FAQ — common misconceptions

### "Do I need a Resend account?"

No.

### "Do I need a custom domain name?"

No.

### "Do I need to set up DKIM / SPF / DMARC DNS records?"

No.

### "Do I need an institutional SMTP relay?"

No.

### "Do I need a Mailpit container in the dev compose?"

No.

If something on the internet asks Echoroo to authenticate your email address or asks you to configure any of the above, ignore it — Echoroo does not, will not, and will never send email out of this deployment.
