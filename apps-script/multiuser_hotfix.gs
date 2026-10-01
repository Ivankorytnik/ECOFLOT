// ECOFLOT multi-user Telegram hotfix helpers.
// Canonical source for the Apps Script bridge. These helpers are designed
// for the 2026-09-rebuild bridge and use the existing ECOFLOT + telegramApi_ globals.

const ECOFLOT_BOT_USERS_SHEET = 'Пользователи бота';
const ECOFLOT_USER_APPROVED = 'Подтвержден';

function ecoflotApprovedChatIds_() {
  const ids = {};
  const props = PropertiesService.getScriptProperties();

  function addIds(raw) {
    String(raw || '')
      .split(/[\s,;]+/)
      .map(function(v) { return String(v || '').trim(); })
      .filter(Boolean)
      .forEach(function(id) { ids[id] = true; });
  }

  [
    'TELEGRAM_ADMIN_ID',
    'TELEGRAM_ADMIN_CHAT_ID',
    'TELEGRAM_CHAT_ID',
    'TELEGRAM_CHAT_ID_2',
    'TELEGRAM_CHAT_ID_3',
    'TELEGRAM_CHAT_IDS',
    'CHAT_ID',
    'TG_CHAT_ID'
  ].forEach(function(key) {
    addIds(props.getProperty(key));
  });

  const ss = SpreadsheetApp.openById(ECOFLOT.SHEET_ID);
  const sheet = ss.getSheetByName(ECOFLOT_BOT_USERS_SHEET);

  if (sheet && sheet.getLastRow() >= 2) {
    const rows = sheet
      .getRange(2, 1, sheet.getLastRow() - 1, 5)
      .getDisplayValues();

    rows.forEach(function(row) {
      const id = String(row[0] || '').trim();
      const status = String(row[4] || '').trim();
      if (!id) return;
      if (status === 'Бот заблокирован') {
        delete ids[id];
        return;
      }
      if (status === ECOFLOT_USER_APPROVED) ids[id] = true;
    });
  }

  return Object.keys(ids);
}

function ecoflotSendTextToAll_(text, extraPayload) {
  const ids = ecoflotApprovedChatIds_();
  const routes = [];
  const errors = [];

  ids.forEach(function(chatId) {
    try {
      const payload = Object.assign({}, extraPayload || {}, {
        chat_id: chatId,
        text: String(text || '')
      });
      const result = telegramApi_('sendMessage', payload);
      routes.push({
        chatId: String(chatId),
        messageId: String(result.result.message_id)
      });
    } catch (err) {
      errors.push({
        chatId: String(chatId),
        error: String(err && err.message ? err.message : err)
      });
    }
  });

  if (!routes.length && errors.length) {
    throw new Error(
      'Telegram delivery failed for all recipients: ' +
      errors.map(function(x) { return x.chatId + ': ' + x.error; }).join('; ')
    );
  }

  return { routes: routes, errors: errors, sent: routes.length };
}

function ecoflotSendLeadToAll_(lead) {
  return ecoflotSendTextToAll_(
    buildLeadText_(lead),
    {
      parse_mode: 'HTML',
      disable_web_page_preview: true,
      reply_markup: JSON.stringify(buildStatusKeyboard_(lead))
    }
  );
}

function ecoflotParseRoutes_(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;

  const raw = String(value || '').trim();
  if (!raw) return [];

  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed;
    if (parsed && Array.isArray(parsed.routes)) return parsed.routes;
  } catch (ignore) {}

  return [];
}

function ecoflotEditLeadCopies_(lead, fallbackChatId, fallbackMessageId) {
  let routes = ecoflotParseRoutes_(lead.telegramRoute);

  if (!routes.length && lead.telegramChatId && lead.telegramMessageId) {
    routes = [{
      chatId: String(lead.telegramChatId),
      messageId: String(lead.telegramMessageId)
    }];
  }

  if (fallbackChatId && fallbackMessageId) {
    const key = String(fallbackChatId) + ':' + String(fallbackMessageId);
    const exists = routes.some(function(r) {
      return String(r.chatId) + ':' + String(r.messageId) === key;
    });
    if (!exists) {
      routes.push({
        chatId: String(fallbackChatId),
        messageId: String(fallbackMessageId)
      });
    }
  }

  const errors = [];
  routes.forEach(function(route) {
    try {
      telegramApi_('editMessageText', {
        chat_id: route.chatId,
        message_id: Number(route.messageId),
        text: buildLeadText_(lead),
        parse_mode: 'HTML',
        disable_web_page_preview: true,
        reply_markup: JSON.stringify(buildStatusKeyboard_(lead))
      });
    } catch (err) {
      const msg = String(err && err.message ? err.message : err);
      if (msg.indexOf('message is not modified') < 0) {
        errors.push(route.chatId + ':' + route.messageId + ' ' + msg);
      }
    }
  });

  if (errors.length) console.error('Multi-user edit errors: ' + errors.join('; '));
  return routes.length;
}
