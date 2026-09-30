/**
 * ECOFLOT Telegram registration module.
 * Scope: registration + approval + approved-recipient list only.
 * Does not change lead/search/CRM/status business logic.
 *
 * Requires existing globals/functions:
 * - ECOFLOT.SHEET_ID
 * - telegramApi_(method, payload)
 * - jsonResponse(obj) (only if used by caller)
 */

const ECOFLOT_REG = Object.freeze({
  USERS_SHEET: 'Пользователи бота',
  PENDING: 'Ожидает подтверждения',
  APPROVED: 'Подтвержден',
  STATE_PREFIX: 'ECOFLOT_REG_STATE_',
  HEADERS: [
    'Telegram ID',
    'Username',
    'Имя',
    'Телефон',
    'Статус',
    'Дата регистрации',
    'Дата подтверждения',
    'Подтвердил (Telegram ID)'
  ]
});

function regProps_() {
  return PropertiesService.getScriptProperties();
}

function regSafe_(v) {
  return v == null ? '' : String(v).trim();
}

function regAdminChatId_() {
  const props = regProps_();
  const raw =
    props.getProperty('TELEGRAM_ADMIN_CHAT_ID') ||
    props.getProperty('TELEGRAM_ADMIN_ID') ||
    props.getProperty('TELEGRAM_CHAT_ID') ||
    props.getProperty('CHAT_ID') ||
    props.getProperty('TG_CHAT_ID') ||
    '';

  return String(raw)
    .split(/[\s,;]+/)
    .map(function(v) { return String(v || '').trim(); })
    .filter(Boolean)[0] || '';
}

function regLegacyAllowedIds_() {
  const props = regProps_();
  const ids = {};

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
    regSafe_(props.getProperty(key))
      .split(/[\s,;]+/)
      .map(regSafe_)
      .filter(Boolean)
      .forEach(function(id) {
        ids[id] = true;
      });
  });

  return Object.keys(ids);
}

function regUsersSheet_() {
  const ss = SpreadsheetApp.openById(ECOFLOT.SHEET_ID);
  let sheet = ss.getSheetByName(ECOFLOT_REG.USERS_SHEET);

  if (!sheet) {
    sheet = ss.insertSheet(ECOFLOT_REG.USERS_SHEET);
  }

  if (sheet.getLastRow() === 0) {
    sheet.getRange(1, 1, 1, ECOFLOT_REG.HEADERS.length)
      .setValues([ECOFLOT_REG.HEADERS]);
    sheet.setFrozenRows(1);
  } else {
    const row1 = sheet
      .getRange(1, 1, 1, ECOFLOT_REG.HEADERS.length)
      .getDisplayValues()[0];

    const empty = row1.every(function(v) {
      return !regSafe_(v);
    });

    if (empty) {
      sheet.getRange(1, 1, 1, ECOFLOT_REG.HEADERS.length)
        .setValues([ECOFLOT_REG.HEADERS]);
      sheet.setFrozenRows(1);
    }
  }

  const validation = SpreadsheetApp.newDataValidation()
    .requireValueInList(
      [ECOFLOT_REG.PENDING, ECOFLOT_REG.APPROVED],
      true
    )
    .setAllowInvalid(false)
    .build();

  if (sheet.getMaxRows() < 500) {
    sheet.insertRowsAfter(
      sheet.getMaxRows(),
      500 - sheet.getMaxRows()
    );
  }

  sheet.getRange(
    2,
    5,
    Math.max(1, sheet.getMaxRows() - 1),
    1
  ).setDataValidation(validation);

  return sheet;
}

function regFindUser_(telegramId) {
  telegramId = regSafe_(telegramId);
  if (!telegramId) return null;

  const sheet = regUsersSheet_();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return null;

  const found = sheet
    .getRange(2, 1, lastRow - 1, 1)
    .createTextFinder(telegramId)
    .matchEntireCell(true)
    .findNext();

  if (!found) return null;

  const row = found.getRow();
  const v = sheet.getRange(row, 1, 1, 8).getValues()[0];

  return {
    row: row,
    telegramId: regSafe_(v[0]),
    username: regSafe_(v[1]),
    name: regSafe_(v[2]),
    phone: regSafe_(v[3]),
    status: regSafe_(v[4]),
    registeredAt: v[5],
    approvedAt: v[6],
    approvedBy: regSafe_(v[7])
  };
}

function regIsApproved_(telegramId) {
  telegramId = regSafe_(telegramId);
  if (!telegramId) return false;

  if (regLegacyAllowedIds_().indexOf(telegramId) >= 0) {
    return true;
  }

  const user = regFindUser_(telegramId);
  return !!(user && user.status === ECOFLOT_REG.APPROVED);
}

function regApprovedIds_() {
  const ids = {};

  regLegacyAllowedIds_().forEach(function(id) {
    ids[id] = true;
  });

  const sheet = regUsersSheet_();
  const lastRow = sheet.getLastRow();

  if (lastRow >= 2) {
    const rows = sheet
      .getRange(2, 1, lastRow - 1, 5)
      .getDisplayValues();

    rows.forEach(function(r) {
      const id = regSafe_(r[0]);
      const status = regSafe_(r[4]);

      if (id && status === ECOFLOT_REG.APPROVED) {
        ids[id] = true;
      }
    });
  }

  return Object.keys(ids);
}

function regSetState_(telegramId, state) {
  regProps_().setProperty(
    ECOFLOT_REG.STATE_PREFIX + regSafe_(telegramId),
    JSON.stringify(state || {})
  );
}

function regGetState_(telegramId) {
  const raw = regProps_().getProperty(
    ECOFLOT_REG.STATE_PREFIX + regSafe_(telegramId)
  );

  if (!raw) return null;

  try {
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function regClearState_(telegramId) {
  regProps_().deleteProperty(
    ECOFLOT_REG.STATE_PREFIX + regSafe_(telegramId)
  );
}

function regStart_(message) {
  const chatId = regSafe_(message && message.chat && message.chat.id);
  if (!chatId) return false;

  regClearState_(chatId);

  if (regIsApproved_(chatId)) {
    if (typeof ecoflotSendMainMenu_ === 'function') {
      ecoflotSendMainMenu_(
        chatId,
        '✅ Доступ к ECOFLOT активен.\n' +
        'Вы будете получать все сообщения бота, включая результаты поисков.'
      );
    } else {
      telegramApi_('sendMessage', {
        chat_id: chatId,
        text:
          '✅ Доступ к ECOFLOT активен.\n' +
          'Вы будете получать все сообщения бота, включая результаты поисков.'
      });
    }
    return true;
  }

  const existing = regFindUser_(chatId);

  if (existing && existing.status === ECOFLOT_REG.PENDING) {
    telegramApi_('sendMessage', {
      chat_id: chatId,
      text:
        '⏳ Регистрация уже отправлена.\n' +
        'Ожидайте подтверждения администратора.'
    });
    return true;
  }

  const username = regSafe_(
    message.from && message.from.username
  );

  regSetState_(chatId, {
    step: 'name',
    username: username
  });

  telegramApi_('sendMessage', {
    chat_id: chatId,
    text:
      'Добро пожаловать в ECOFLOT.\n\n' +
      'Для регистрации введите ваше имя:'
  });

  return true;
}

function regHandleMessage_(message) {
  if (!message || !message.chat) return false;

  const chatId = regSafe_(message.chat.id);
  const text = regSafe_(message.text);
  const command = text
    .split(/\s+/)[0]
    .split('@')[0]
    .toLowerCase();

  if (command === '/start') {
    return regStart_(message);
  }

  if (regIsApproved_(chatId) && typeof ecoflotHandleMenuMessage_ === 'function') {
    if (ecoflotHandleMenuMessage_(message)) {
      return true;
    }
  }

  if (command === '/status') {
    const user = regFindUser_(chatId);

    if (regIsApproved_(chatId)) {
      telegramApi_('sendMessage', {
        chat_id: chatId,
        text: '✅ Статус: доступ подтверждён.'
      });
    } else if (user && user.status === ECOFLOT_REG.PENDING) {
      telegramApi_('sendMessage', {
        chat_id: chatId,
        text: '⏳ Статус: ожидает подтверждения администратора.'
      });
    } else {
      telegramApi_('sendMessage', {
        chat_id: chatId,
        text: 'Регистрация не завершена. Нажмите /start.'
      });
    }

    return true;
  }

  const state = regGetState_(chatId);
  if (!state) return false;

  const username = regSafe_(
    message.from && message.from.username
  );

  if (state.step === 'name') {
    if (!text || text.charAt(0) === '/') {
      telegramApi_('sendMessage', {
        chat_id: chatId,
        text: 'Введите ваше имя текстом.'
      });
      return true;
    }

    state.name = text;
    state.username = username || state.username || '';
    state.step = 'phone';

    regSetState_(chatId, state);

    telegramApi_('sendMessage', {
      chat_id: chatId,
      text:
        'Спасибо.\n' +
        'Теперь отправьте номер телефона кнопкой ниже или введите его текстом.',
      reply_markup: {
        keyboard: [[
          {
            text: '📱 Отправить телефон',
            request_contact: true
          }
        ]],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });

    return true;
  }

  if (state.step === 'phone') {
    let phone = '';

    if (
      message.contact &&
      message.contact.phone_number
    ) {
      if (
        message.contact.user_id &&
        message.from &&
        String(message.contact.user_id) !== String(message.from.id)
      ) {
        telegramApi_('sendMessage', {
          chat_id: chatId,
          text: 'Пожалуйста, отправьте свой номер телефона.'
        });
        return true;
      }

      phone = regSafe_(message.contact.phone_number);
    } else {
      phone = text;
    }

    const digits = phone.replace(/\D/g, '');

    if (digits.length < 7) {
      telegramApi_('sendMessage', {
        chat_id: chatId,
        text: 'Введите корректный номер телефона.'
      });
      return true;
    }

    const user = regSavePending_(
      chatId,
      username || state.username || '',
      state.name || '',
      phone
    );

    regClearState_(chatId);

    telegramApi_('sendMessage', {
      chat_id: chatId,
      text:
        '✅ Регистрация отправлена.\n\n' +
        'Статус: «Ожидает подтверждения».\n' +
        'После подтверждения вы начнёте получать все сообщения ECOFLOT.',
      reply_markup: {
        remove_keyboard: true
      }
    });

    regNotifyAdmin_(user);
    return true;
  }

  return false;
}

function regSavePending_(telegramId, username, name, phone) {
  const sheet = regUsersSheet_();
  const existing = regFindUser_(telegramId);
  const now = new Date();

  if (existing) {
    sheet.getRange(existing.row, 1, 1, 8).setValues([[
      regSafe_(telegramId),
      regSafe_(username),
      regSafe_(name),
      regSafe_(phone),
      ECOFLOT_REG.PENDING,
      existing.registeredAt || now,
      '',
      ''
    ]]);

    SpreadsheetApp.flush();
    return regFindUser_(telegramId);
  }

  sheet.appendRow([
    regSafe_(telegramId),
    regSafe_(username),
    regSafe_(name),
    regSafe_(phone),
    ECOFLOT_REG.PENDING,
    now,
    '',
    ''
  ]);

  SpreadsheetApp.flush();
  return regFindUser_(telegramId);
}

function regNotifyAdmin_(user) {
  const adminId = regAdminChatId_();
  if (!adminId || !user) return false;

  const lines = [
    '👤 Новая регистрация ECOFLOT',
    '',
    'Имя: ' + (user.name || '-'),
    'Телефон: ' + (user.phone || '-'),
    'Telegram ID: ' + user.telegramId,
    user.username ? ('Username: @' + user.username) : '',
    '',
    'Статус: ожидает подтверждения'
  ].filter(Boolean);

  telegramApi_('sendMessage', {
    chat_id: adminId,
    text: lines.join('\n'),
    reply_markup: {
      inline_keyboard: [[
        {
          text: '✅ Подтвердить',
          callback_data: 'reg|approve|' + user.telegramId
        }
      ]]
    }
  });

  return true;
}

function regHandleCallback_(callbackQuery) {
  const data = regSafe_(
    callbackQuery && callbackQuery.data
  );

  if (data.indexOf('reg|approve|') !== 0) {
    return false;
  }

  const adminId = regAdminChatId_();
  const clickerId = regSafe_(
    callbackQuery &&
    callbackQuery.from &&
    callbackQuery.from.id
  );

  if (!adminId || clickerId !== adminId) {
    telegramApi_('answerCallbackQuery', {
      callback_query_id: callbackQuery.id,
      text: 'Только администратор может подтверждать регистрацию.',
      show_alert: true
    });
    return true;
  }

  const telegramId = data.slice('reg|approve|'.length);
  const user = regApprove_(telegramId, clickerId);

  if (!user) {
    telegramApi_('answerCallbackQuery', {
      callback_query_id: callbackQuery.id,
      text: 'Пользователь не найден.',
      show_alert: true
    });
    return true;
  }

  telegramApi_('answerCallbackQuery', {
    callback_query_id: callbackQuery.id,
    text: 'Пользователь подтверждён.',
    show_alert: false
  });

  if (
    callbackQuery.message &&
    callbackQuery.message.chat &&
    callbackQuery.message.message_id
  ) {
    const lines = [
      '✅ Пользователь подтверждён',
      '',
      'Имя: ' + (user.name || '-'),
      'Телефон: ' + (user.phone || '-'),
      'Telegram ID: ' + user.telegramId,
      user.username ? ('Username: @' + user.username) : ''
    ].filter(Boolean);

    try {
      telegramApi_('editMessageText', {
        chat_id: callbackQuery.message.chat.id,
        message_id: callbackQuery.message.message_id,
        text: lines.join('\n')
      });
    } catch (ignore) {}
  }

  if (typeof ecoflotSendMainMenu_ === 'function') {
    ecoflotSendMainMenu_(
      user.telegramId,
      '✅ Доступ к ECOFLOT подтверждён.\n' +
      'Теперь вы будете получать все сообщения бота, включая результаты поисков.'
    );
  } else {
    telegramApi_('sendMessage', {
      chat_id: user.telegramId,
      text:
        '✅ Доступ к ECOFLOT подтверждён.\n' +
        'Теперь вы будете получать все сообщения бота, включая результаты поисков.'
    });
  }

  return true;
}

function regApprove_(telegramId, approvedBy) {
  const user = regFindUser_(telegramId);
  if (!user) return null;

  const sheet = regUsersSheet_();

  sheet.getRange(user.row, 5).setValue(ECOFLOT_REG.APPROVED);
  sheet.getRange(user.row, 7).setValue(new Date());
  sheet.getRange(user.row, 8).setValue(regSafe_(approvedBy));

  SpreadsheetApp.flush();
  return regFindUser_(telegramId);
}

/**
 * Recipient source for the existing ECOFLOT delivery code.
 * Only approved users + existing legacy configured IDs are returned.
 */
function getApprovedTelegramRecipients_() {
  return regApprovedIds_();
}


/*
============================================================
REGISTRATION WRAPPER
Keeps old ECOFLOT logic intact and protects against duplicate/stale /start
============================================================
*/
function handleTelegramUpdate_(update) {
  try {
    const cache = CacheService.getScriptCache();
    const updateId =
      update && update.update_id != null
        ? String(update.update_id)
        : '';

    if (updateId) {
      const updateKey = 'tg_update_' + updateId;

      if (cache.get(updateKey)) {
        return jsonResponse({
          ok: true,
          ignored: 'duplicate_update'
        });
      }

      cache.put(updateKey, '1', 21600);
    }

    if (
      update &&
      update.message &&
      update.message.text &&
      /^\/start\b/i.test(String(update.message.text).trim())
    ) {
      const messageDate = Number(update.message.date || 0);

      if (messageDate) {
        const ageSeconds =
          Math.floor(Date.now() / 1000) - messageDate;

        if (ageSeconds > 120) {
          return jsonResponse({
            ok: true,
            ignored: 'stale_start',
            ageSeconds: ageSeconds
          });
        }
      }
    }

    if (update && update.callback_query) {
      if (regHandleCallback_(update.callback_query)) {
        return jsonResponse({
          ok: true,
          registration: true
        });
      }
    }

    if (update && update.message) {
      if (regHandleMessage_(update.message)) {
        return jsonResponse({
          ok: true,
          registration: true
        });
      }
    }

    return handleTelegramUpdateOriginal_(update);

  } catch (error) {
    console.error(
      'Registration wrapper error: ' +
      (
        error && error.stack
          ? error.stack
          : error
      )
    );

    return handleTelegramUpdateOriginal_(update);
  }
}
