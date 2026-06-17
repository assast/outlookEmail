## ADDED Requirements

### Requirement: Outlook accounts can be reauthorized

The system SHALL allow a logged-in user to reauthorize an existing Outlook OAuth account by using a Microsoft OAuth callback URL for that specific account.

#### Scenario: Reauthorize an existing Outlook account

- **WHEN** the user submits a valid OAuth callback URL for an existing Outlook account
- **THEN** the system MUST exchange the authorization code for new authorization data for that account

#### Scenario: Reject non-Outlook account

- **WHEN** the user submits a reauthorization request for an IMAP account
- **THEN** the system MUST reject the request and MUST NOT modify the account

#### Scenario: Reject missing account

- **WHEN** the user submits a reauthorization request for an account ID that does not exist
- **THEN** the system MUST return an account-not-found error and MUST NOT create a new account

### Requirement: Reauthorization updates only authorization data

The system SHALL update only the target Outlook account authorization fields and required refresh-state fields during reauthorization.

#### Scenario: Preserve non-authorization account fields

- **WHEN** reauthorization succeeds for an Outlook account
- **THEN** the system MUST preserve the account email, password, group, status, forwarding settings, proxy settings, sort order, remark, aliases, tags, and provider configuration

#### Scenario: Store new authorization fields

- **WHEN** reauthorization succeeds for an Outlook account
- **THEN** the system MUST store the new `client_id`, encrypted `refresh_token`, and a non-empty `refresh_token_updated_at`

### Requirement: Reauthorization clears stale refresh failure before validation

The system SHALL clear stale refresh failure state after a successful authorization update and before automatic validation refresh is applied.

#### Scenario: Clear previous failure state

- **WHEN** an Outlook account with `last_refresh_status` set to `failed` is successfully reauthorized
- **THEN** the system MUST clear the old `last_refresh_error` before running the automatic validation refresh

#### Scenario: Do not mark success without validation

- **WHEN** the authorization update succeeds but the automatic validation refresh has not yet succeeded
- **THEN** the system MUST NOT mark `last_refresh_status` as `success` solely because authorization data was updated

### Requirement: Reauthorization automatically validates by refreshing the account

The system SHALL automatically trigger a single-account token refresh after successful reauthorization and persist the real refresh result.

#### Scenario: Automatic validation refresh succeeds

- **WHEN** reauthorization succeeds and the automatic single-account refresh succeeds
- **THEN** the system MUST set `last_refresh_status` to `success`, update `last_refresh_at`, and clear `last_refresh_error`

#### Scenario: Automatic validation refresh fails

- **WHEN** reauthorization succeeds and the automatic single-account refresh fails
- **THEN** the system MUST set `last_refresh_status` to `failed`, update `last_refresh_at`, and store the new refresh error

#### Scenario: Response includes validation result

- **WHEN** the reauthorization request finishes
- **THEN** the API response MUST include whether authorization was updated and the result of the automatic validation refresh

### Requirement: User interface exposes account reauthorization

The system SHALL expose reauthorization actions only for Outlook OAuth accounts and guide the user through OAuth authorization, callback URL submission, authorization update, and automatic refresh validation.

#### Scenario: Show action for Outlook account

- **WHEN** the user opens an Outlook account edit view or refresh-failure context
- **THEN** the interface MUST provide a reauthorization action for that account

#### Scenario: Hide action for IMAP account

- **WHEN** the user opens an IMAP account edit view
- **THEN** the interface MUST NOT show a reauthorization action

#### Scenario: Display final validation result

- **WHEN** reauthorization and automatic validation refresh complete
- **THEN** the interface MUST refresh account state and show success or the new refresh failure result for that account
