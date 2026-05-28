# Local Mail Retention Scope

## Scope

This first phase covers normal mailbox reading for Outlook/Hotmail accounts and generic IMAP accounts. The retained data is intended to keep the normal mail list and message detail body usable across app restarts, temporary provider failures, and offline starts.

Included mailbox paths:

- Outlook/Hotmail OAuth accounts using Microsoft Graph list/detail reads.
- Outlook/Hotmail OAuth accounts that fall back to IMAP for normal mailbox reads.
- Standard IMAP provider accounts.

## Configuration switch

Normal mail local retention is controlled by `normal_mail_local_retention_enabled` and is disabled by default. The app keeps normal mailbox reads remote-first until the user explicitly enables this setting from the settings page.

When enabled, retention stores normal mailbox list metadata and only the message bodies that were viewed or explicitly backfilled for local fallback. The retained rows live in local SQLite. The switch applies to normal Outlook/Hotmail and standard IMAP mailbox list/detail flows; it is not a generic attachment archive or raw message archive.

The backend keeps this switch in a small process-local cache for hot mail-list paths. Settings updates through the normal `/api/settings` flow refresh the cache immediately; direct database edits outside the app should be treated as unsupported operational changes until the process is restarted or the setting is saved again through the app.

## Local-first list load

When retention is enabled, normal mailbox list views should load retained local rows first for the selected account and folder. The UI can render this retained list immediately without waiting for Microsoft Graph or IMAP, preserving the normal received-date ordering and pagination semantics. Continued list pagination must keep using the local retained source (`source=local`) while the visible list is in local-first mode, so users can load beyond the first page even when the remote provider is still unavailable.

If the remote provider is unavailable, rate limited, or slow, the retained list remains the user-visible fallback instead of being cleared. Local rows should be treated as cached mailbox state, not as a separate mailbox mode. When retention is disabled, the client should not request the local list source and should show the normal remote result or the explicit disabled local-storage message.

Keyword filtering may need full bodies. When a retained row already has a cached body, filtering should inspect that local body first and avoid an extra remote detail fetch for the same message. Remote detail fetches are reserved for rows whose cached subject, preview, and body are not enough to decide the keyword match.

## Background remote sync

After the enabled local-first list is shown, the app may start a background remote sync for the same account and folder when credentials and network access are available. A successful remote sync should upsert list metadata into SQLite using the provider identity for the message, update cache timestamps, and avoid duplicates for the same account, folder, provider message id, and id mode.

Remote sync must not block initial list rendering. A failed sync should leave the retained list intact and surface an error or stale-state hint only where the existing UI has a place to do so.

## New-message notice

When background sync finds messages that were not already retained locally, the client should show a non-destructive new-message notice. The notice tells the user that newer remote messages are available without abruptly replacing the list while they are reading.

Background sync must stage newly discovered rows without immediately merging them into the current visible list. After the user accepts the notice, the client merges the staged rows into the current list, highlights the newly visible messages, updates the list cache, and triggers best-effort body retention for the newly accepted rows.

## Detail body retention

When retention is enabled, opening a message detail should prefer a retained body when one is already cached for that retained list row. If the retained row has no body yet, the app should fetch the body from the active provider path, then store the normalized display body and related body metadata for future reads.

If a remote detail fetch fails but a retained body exists, the detail view should show the retained body as a fallback and indicate that the content is cached or may be stale. If no retained body exists and the remote fetch fails, the existing error path should remain visible.

Outlook/Hotmail OAuth accounts that use IMAP fallback must keep the provider message identifier mode with the row. `id_mode=uid` is the default for missing or invalid detail and attachment requests; `id_mode=sequence` is accepted only when the caller is replaying a sequence-based list item. This keeps UID and sequence-number reads from being mixed accidentally.

## Retention statistics

The settings page shows user-visible storage statistics from `/api/settings/normal-mail-retention/status`:

- `saved_message_count`: retained normal mailbox rows.
- `cached_body_count`: retained rows with a cached display body.
- `estimated_retained_bytes`: estimated text payload retained by normal mail rows.
- `db_file_bytes`: current SQLite database file size.
- `clear_status`: process-local cache-cleanup state and message.

These fields are intended for transparency and cleanup decisions, not for precise quota accounting.

## Cache cleanup

The settings page provides a standalone clear-cache action that deletes rows from `retained_normal_mail_messages` without disabling `normal_mail_local_retention_enabled`. This lets users free local storage while keeping future retention enabled.

Turning the retention switch off is a separate settings update. If retained rows exist, the UI asks for destructive confirmation before saving the disabled setting. After confirmation, the browser sends the settings update and then calls `/api/settings/normal-mail-retention/clear`; the backend performs cleanup in a background thread and reports `idle`, `running`, `succeeded`, or `failed` through the clear status object.

While cleanup is running, duplicate clear requests should reuse the current running status instead of starting another destructive job. The worker retries transient SQLite `database is locked` failures before reporting `failed`, and the settings UI polls status with backoff rather than a fixed one-second loop. Once cleanup succeeds, the retained normal mail table should be empty and disabled local-list requests should remain blocked with the disabled local-storage message.

## Explicitly outside this phase

This phase does not retain attachment binaries and does not download or store raw MIME content. Attachment binary retention and raw MIME retention/download behavior must be handled by a later, separate scope.
