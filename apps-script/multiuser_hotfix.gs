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

  return Object.keys(ids).filter(function(id) {
    return /^-?\d+$/.test(String(id || '').trim());
  });
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


const ECOFLOT_TELEGRAM_QUEUE_SHEET = 'Очередь Telegram';
const ECOFLOT_OUTBOX_MAX_ATTEMPTS = 6;

function ecoflotProcessTextOutbox_() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) return { ok:false, skipped:true, reason:'LOCK_BUSY' };
  try {
    const ss = SpreadsheetApp.openById(ECOFLOT.SHEET_ID);
    const sheet = ss.getSheetByName(ECOFLOT_TELEGRAM_QUEUE_SHEET);
    if (!sheet || sheet.getLastRow() < 2) return { ok:true, processed:0, sent:0, failed:0 };

    const lastRow = sheet.getLastRow();
    const rows = sheet.getRange(2, 1, lastRow - 1, 7).getValues();
    let processed = 0;
    let sent = 0;
    let failed = 0;

    rows.forEach(function(row, index) {
      const kind = String(row[1] || '').trim();
      const key = String(row[2] || '').trim();
      const raw = String(row[3] || '').trim();
      const attempts = Number(row[4] || 0);
      const status = String(row[6] || '').trim().toUpperCase();
      if (status === 'SENT' || status === 'IGNORED' || attempts >= ECOFLOT_OUTBOX_MAX_ATTEMPTS) return;
      if (kind !== 'text' && kind !== 'text_one') return;

      const sheetRow = index + 2;
      processed += 1;
      try {
        const payload = ecoflotQueueItemV3_(kind, key, raw);
        let routes = [];
        if (kind === 'text_one') {
          const chatId = String(payload.chatId || '').trim();
          if (!/^-?\d+$/.test(chatId)) throw new Error('INVALID_TEXT_ONE_CHAT');
          const result = telegramApi_('sendMessage', {
            chat_id: chatId,
            text: String(payload.text || '')
          });
          const receipt = ecoflotReceiptV3_(result, chatId);
          routes = [receipt];
        } else {
          const result = ecoflotSendTextToAll_(String(payload.text || ''));
          routes = result.routes || [];
          if (!routes.length) throw new Error('NO_TELEGRAM_ROUTES');
        }

        const enriched = Object.assign({}, payload, {
          _ef5: Object.assign({}, payload._ef5 || {}, {
            version: 5,
            finishedAt: new Date().toISOString(),
            routes: routes
          })
        });
        sheet.getRange(sheetRow, 4).setValue(JSON.stringify(enriched));
        sheet.getRange(sheetRow, 5).setValue(attempts + 1);
        sheet.getRange(sheetRow, 6).setValue('');
        sheet.getRange(sheetRow, 7).setValue('SENT');
        sent += 1;
      } catch (err) {
        const msg = String(err && err.message ? err.message : err).slice(0, 500);
        sheet.getRange(sheetRow, 5).setValue(attempts + 1);
        sheet.getRange(sheetRow, 6).setValue(msg);
        sheet.getRange(sheetRow, 7).setValue(attempts + 1 >= ECOFLOT_OUTBOX_MAX_ATTEMPTS ? 'ERROR' : 'PENDING');
        failed += 1;
      }
    });

    SpreadsheetApp.flush();
    return { ok:true, processed:processed, sent:sent, failed:failed };
  } finally {
    lock.releaseLock();
  }
}

function ecoflotInstallOutboxTrigger_() {
  // Prefer the deployed bridge's canonical processor: it handles lead_one,
  // text_one and the rest of the native queue. Fall back to the text processor
  // only in stripped-down projects where the canonical function is absent.
  const handler = (typeof processTelegramOutbox === 'function')
    ? 'processTelegramOutbox'
    : 'ecoflotProcessTextOutbox_';

  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    const current = trigger.getHandlerFunction();
    if (current === handler ||
        current === 'processTelegramOutbox' ||
        current === 'ecoflotProcessTextOutbox_') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger(handler).timeBased().everyMinutes(1).create();
  return { ok:true, handler:handler };
}

function ecoflotOutboxHealth_() {
  const ss = SpreadsheetApp.openById(ECOFLOT.SHEET_ID);
  const sheet = ss.getSheetByName(ECOFLOT_TELEGRAM_QUEUE_SHEET);
  if (!sheet || sheet.getLastRow() < 2) return { ok:true, pending:0, error:0 };
  const rows = sheet.getRange(2, 5, sheet.getLastRow() - 1, 3).getDisplayValues();
  let pending = 0;
  let error = 0;
  rows.forEach(function(row) {
    const status = String(row[2] || '').trim().toUpperCase();
    if (!status || status === 'PENDING') pending += 1;
    if (status === 'ERROR') error += 1;
  });
  return { ok:error === 0, pending:pending, error:error };
}
