# Local Mail Retention Scope

## Scope

This first phase covers normal mailbox reading for Outlook/Hotmail accounts and generic IMAP accounts. The retained data is intended to keep the normal mail list and message detail body usable across app restarts, temporary provider failures, and offline starts.

Included mailbox paths:

- Outlook/Hotmail OAuth accounts using Microsoft Graph list/detail reads.
- Outlook/Hotmail OAuth accounts that fall back to IMAP for normal mailbox reads.
- Standard IMAP provider accounts.

## Local-first list load

Normal mailbox list views should load retained local rows first for the selected account and folder. The UI can render this retained list immediately without waiting for Microsoft Graph or IMAP, preserving the normal received-date ordering and pagination semantics.

If the remote provider is unavailable, rate limited, or slow, the retained list remains the user-visible fallback instead of being cleared. Local rows should be treated as cached mailbox state, not as a separate mailbox mode.

## Background remote sync

After the local-first list is shown, the app may start a background remote sync for the same account and folder when credentials and network access are available. A successful remote sync should upsert list metadata into SQLite using the provider identity for the message, update cache timestamps, and avoid duplicates for the same account, folder, provider message id, and id mode.

Remote sync must not block initial list rendering. A failed sync should leave the retained list intact and surface an error or stale-state hint only where the existing UI has a place to do so.

## New-message notice

When background sync finds messages that were not already retained locally, the client should show a non-destructive new-message notice. The notice tells the user that newer remote messages are available without abruptly replacing the list while they are reading.

After the user refreshes or accepts the notice, the list can be reloaded from the retained store so newly discovered messages appear in the normal ordering.

## Detail body retention

Opening a message detail should prefer a retained body when one is already cached for that retained list row. If the retained row has no body yet, the app should fetch the body from the active provider path, then store the normalized display body and related body metadata for future reads.

If a remote detail fetch fails but a retained body exists, the detail view should show the retained body as a fallback and indicate that the content is cached or may be stale. If no retained body exists and the remote fetch fails, the existing error path should remain visible.

## Explicitly outside this phase

This phase does not retain attachment binaries and does not download or store raw MIME content. Attachment binary retention and raw MIME retention/download behavior must be handled by a later, separate scope.
