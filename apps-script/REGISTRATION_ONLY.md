# ECOFLOT registration only

This module adds only Telegram user registration and administrator approval.

Flow:
1. User sends /start.
2. Bot asks for name.
3. Bot asks for phone.
4. User is written to the existing Google Sheet tab "Пользователи бота" with status "Ожидает подтверждения".
5. Administrator receives a Telegram message with the "✅ Подтвердить" button.
6. Only the configured administrator can approve.
7. User status becomes "Подтвержден".
8. Confirmed users are returned by getApprovedTelegramRecipients_() and can receive all normal ECOFLOT broadcasts, including search results.

Integration into the current Apps Script should be limited to registration hooks:
- In handleTelegramUpdate_(update), call regHandleCallback_(update.callback_query) before the existing status callback handler.
- In handleTelegramUpdate_(update), call regHandleMessage_(update.message) before the existing /start fallback.
- Existing business logic for searches, CRM, lead dedupe and statuses should not be changed.
- Existing outbound broadcast code should use getApprovedTelegramRecipients_() as its recipient source. Message content and search logic remain unchanged.
