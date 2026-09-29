# ECOFLOT Apps Script multi-user hotfix

The deployed 2026-09 rebuild regressed from multi-user delivery to a single `getChatId_()` recipient.

## Required integration points in the current bridge

Use `ecoflotApprovedChatIds_()` as the recipient source. The spreadsheet tab `Пользователи бота` is authoritative for users whose status is `Подтвержден`; legacy Script Properties remain supported.

Replace single-recipient text sends in:
- `handleSearchComplete_`
- `maybeSendCycleReport_`
- `handleLegacyNotify_`
- `processTelegramOutbox` for `kind === 'text'`

with `ecoflotSendTextToAll_(text)`.

Replace `sendLeadTelegram_` delivery with `ecoflotSendLeadToAll_(lead)`. Store all returned routes as JSON in the existing `Telegram route` column, while keeping the first route in the legacy `Telegram Chat ID` / `Telegram Message ID` columns for compatibility.

When a status button changes a lead, call `ecoflotEditLeadCopies_` so both Telegram accounts see the same updated status.

The confirmed recipients currently expected in the `Пользователи бота` sheet are:
- 262661708
- 584620734

Do not concatenate Telegram IDs into a numeric cell. Each ID must be stored as its own text value in column A.
