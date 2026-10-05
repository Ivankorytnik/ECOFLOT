/**
 * ECOFLOT Telegram main menu features.
 *
 * Adds:
 * 1) Excel export with open leads only.
 * 2) Manual launch of all 4 current GitHub Actions searches.
 * 3) Lead analytics summary.
 *
 * Existing lead/status/search logic is not replaced.
 */

const ECOFLOT_MENU = Object.freeze({
  EXPORT: '📥 Выгрузить в Excel',
  SEARCH: '🔎 Запустить внеплановый поиск',
  ANALYTICS: '📊 Показать аналитику'
});

const ECOFLOT_MANUAL_SEARCH_WORKFLOWS = Object.freeze([
  'full-cycle.yml'
]);

function ecoflotMainMenuKeyboard_() {
  return {
    keyboard: [
      [{ text: ECOFLOT_MENU.EXPORT }],
      [{ text: ECOFLOT_MENU.SEARCH }],
      [{ text: ECOFLOT_MENU.ANALYTICS }]
    ],
    resize_keyboard: true,
    is_persistent: true
  };
}

function ecoflotSendMainMenu_(chatId, text) {
  telegramApi_('sendMessage', {
    chat_id: String(chatId),
    text: text || 'Меню ECOFLOT',
    reply_markup: ecoflotMainMenuKeyboard_()
  });
  return true;
}

function ecoflotHandleMenuMessage_(message) {
  if (!message || !message.chat) return false;

  const chatId = String(message.chat.id || '').trim();
  const raw = String(message.text || '').trim();
  if (!chatId || !raw) return false;

  const command = raw.split(/\s+/)[0].split('@')[0].toLowerCase();

  if (command === '/menu') {
    ecoflotSendMainMenu_(chatId, 'Меню ECOFLOT');
    return true;
  }

  if (command === '/export' || raw === ECOFLOT_MENU.EXPORT || /^выгрузить\s+в\s+(excel|ексель)$/i.test(raw)) {
    ecoflotExportOpenLeadsToExcel_(chatId);
    return true;
  }

  if (command === '/search' || raw === ECOFLOT_MENU.SEARCH || /^запустить\s+внеплановый\s+поиск$/i.test(raw)) {
    ecoflotTriggerManualSearch_(chatId);
    return true;
  }

  if (command === '/analytics' || raw === ECOFLOT_MENU.ANALYTICS || /^показать\s+аналитику$/i.test(raw)) {
    ecoflotSendAnalytics_(chatId);
    return true;
  }

  return false;
}

function ecoflotSpreadsheetId_() {
  try {
    if (typeof ECOFLOT !== 'undefined' && ECOFLOT && ECOFLOT.SHEET_ID) {
      return String(ECOFLOT.SHEET_ID);
    }
  } catch (ignore) {}

  try {
    if (typeof SPREADSHEET_ID !== 'undefined' && SPREADSHEET_ID) {
      return String(SPREADSHEET_ID);
    }
  } catch (ignore) {}

  return '1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws';
}

function ecoflotNormHeader_(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[^a-zа-я0-9]+/gi, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

function ecoflotFindHeaderIndex_(headers, variants) {
  const normalized = headers.map(ecoflotNormHeader_);

  for (let i = 0; i < variants.length; i++) {
    const needle = ecoflotNormHeader_(variants[i]);
    const exact = normalized.indexOf(needle);
    if (exact >= 0) return exact;
  }

  for (let c = 0; c < normalized.length; c++) {
    for (let i = 0; i < variants.length; i++) {
      const needle = ecoflotNormHeader_(variants[i]);
      if (needle && normalized[c].indexOf(needle) >= 0) return c;
    }
  }

  return -1;
}

function ecoflotLeadSheetInfo_() {
  const ss = SpreadsheetApp.openById(ecoflotSpreadsheetId_());
  const preferred = ['Заявки', 'Leads', 'Лиды'];

  for (let p = 0; p < preferred.length; p++) {
    const sheet = ss.getSheetByName(preferred[p]);
    if (!sheet || sheet.getLastRow() < 1 || sheet.getLastColumn() < 1) continue;

    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
    const statusCol = ecoflotFindHeaderIndex_(headers, ['Статус', 'Status']);
    if (statusCol >= 0) {
      return {
        ss: ss,
        sheet: sheet,
        headers: headers,
        statusCol: statusCol
      };
    }
  }

  const sheets = ss.getSheets();

  for (let s = 0; s < sheets.length; s++) {
    const sheet = sheets[s];
    if (sheet.getLastRow() < 1 || sheet.getLastColumn() < 1) continue;

    const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getDisplayValues()[0];
    const statusCol = ecoflotFindHeaderIndex_(headers, ['Статус', 'Status']);
    const requestCol = ecoflotFindHeaderIndex_(headers, ['Request ID', 'RequestId', 'ID заявки', 'Номер заявки']);

    if (statusCol >= 0 && requestCol >= 0) {
      return {
        ss: ss,
        sheet: sheet,
        headers: headers,
        statusCol: statusCol
      };
    }
  }

  throw new Error('Не найден лист заявок со столбцом «Статус».');
}

function ecoflotNormStatus_(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/\s*\/\s*/g, ' / ')
    .replace(/\s+/g, ' ')
    .trim();
}

function ecoflotIsClosedStatus_(status) {
  const s = ecoflotNormStatus_(status);
  if (!s) return false;

  return [
    'выполнена',
    'выполнен',
    'отказ',
    'закрыта',
    'закрыт',
    'closed',
    'done'
  ].indexOf(s) >= 0;
}

function ecoflotExportOpenLeadsToExcel_(chatId) {
  ecoflotSendText_(chatId, '⏳ Формирую Excel только по незакрытым заявкам...');

  let tempFileId = '';

  try {
    const info = ecoflotLeadSheetInfo_();
    const sheet = info.sheet;
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();

    if (lastRow < 2) {
      ecoflotSendText_(chatId, 'Незакрытых заявок нет.');
      return true;
    }

    const raw = sheet.getRange(1, 1, lastRow, lastCol).getValues();
    const display = sheet.getRange(1, 1, lastRow, lastCol).getDisplayValues();

    const out = [raw[0]];
    for (let r = 1; r < raw.length; r++) {
      const rowHasData = display[r].some(function(v) {
        return String(v || '').trim() !== '';
      });
      if (!rowHasData) continue;

      const status = display[r][info.statusCol];
      if (!ecoflotIsClosedStatus_(status)) {
        out.push(raw[r]);
      }
    }

    if (out.length === 1) {
      ecoflotSendText_(chatId, 'Незакрытых заявок нет.');
      return true;
    }

    const now = new Date();
    const stamp = Utilities.formatDate(
      now,
      Session.getScriptTimeZone() || 'Europe/Moscow',
      'yyyy-MM-dd_HH-mm'
    );

    const temp = SpreadsheetApp.create('ECOFLOT_open_leads_' + stamp);
    tempFileId = temp.getId();

    const target = temp.getSheets()[0];
    target.setName('Незакрытые заявки');
    target.getRange(1, 1, out.length, lastCol).setValues(out);
    target.setFrozenRows(1);
    target.autoResizeColumns(1, Math.min(lastCol, 30));
    SpreadsheetApp.flush();

    const exportUrl =
      'https://docs.google.com/spreadsheets/d/' +
      encodeURIComponent(tempFileId) +
      '/export?format=xlsx';

    const blob = UrlFetchApp.fetch(exportUrl, {
      method: 'get',
      headers: {
        Authorization: 'Bearer ' + ScriptApp.getOAuthToken()
      },
      muteHttpExceptions: false
    })
      .getBlob()
      .setName('ECOFLOT_open_leads_' + stamp + '.xlsx');

    ecoflotSendDocument_(
      chatId,
      blob,
      'Незакрытые заявки ECOFLOT: ' + (out.length - 1) + ' шт.'
    );

    return true;
  } catch (error) {
    console.error('Excel export error: ' + (error && error.stack ? error.stack : error));
    ecoflotSendText_(
      chatId,
      '⚠️ Не удалось сформировать Excel. ' +
      String(error && error.message ? error.message : error)
    );
    return true;
  } finally {
    if (tempFileId) {
      try {
        DriveApp.getFileById(tempFileId).setTrashed(true);
      } catch (ignore) {}
    }
  }
}

function ecoflotSendAnalytics_(chatId) {
  try {
    const info = ecoflotLeadSheetInfo_();
    const sheet = info.sheet;
    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();

    if (lastRow < 2) {
      ecoflotSendText_(chatId, '📊 Аналитика ECOFLOT\n\nЗаявок пока нет.');
      return true;
    }

    const rows = sheet.getRange(2, 1, lastRow - 1, lastCol).getDisplayValues();
    const headers = info.headers;

    const statusCol = info.statusCol;
    const cityCol = ecoflotFindHeaderIndex_(headers, ['Город', 'City', 'Населенный пункт']);
    const sourceCol = ecoflotFindHeaderIndex_(headers, ['Источник', 'Source', 'Ресурс']);

    const statusCounts = {};
    const cityCounts = {};
    const sourceCounts = {};

    let total = 0;
    let open = 0;
    let closed = 0;
    let newCount = 0;
    let inWork = 0;
    let completed = 0;
    let rejected = 0;

    rows.forEach(function(row) {
      const rowHasData = row.some(function(v) {
        return String(v || '').trim() !== '';
      });
      if (!rowHasData) return;

      total += 1;

      const statusRaw = String(row[statusCol] || '').trim() || 'Без статуса';
      const statusNorm = ecoflotNormStatus_(statusRaw);

      statusCounts[statusRaw] = (statusCounts[statusRaw] || 0) + 1;

      if (ecoflotIsClosedStatus_(statusRaw)) {
        closed += 1;
      } else {
        open += 1;
      }

      if (statusNorm === 'новая') newCount += 1;
      if (statusNorm === 'выполнена' || statusNorm === 'выполнен') completed += 1;
      if (statusNorm === 'отказ') rejected += 1;

      if (
        !ecoflotIsClosedStatus_(statusRaw) &&
        statusNorm !== 'новая' &&
        statusNorm !== 'без статуса'
      ) {
        inWork += 1;
      }

      if (cityCol >= 0) {
        const city = String(row[cityCol] || '').trim();
        if (city) cityCounts[city] = (cityCounts[city] || 0) + 1;
      }

      if (sourceCol >= 0) {
        const source = String(row[sourceCol] || '').trim();
        if (source) sourceCounts[source] = (sourceCounts[source] || 0) + 1;
      }
    });

    const lines = [
      '📊 Аналитика ECOFLOT',
      '',
      'Всего заявок: ' + total,
      'Незакрытые: ' + open,
      'Закрытые: ' + closed,
      'Новые: ' + newCount,
      'В работе: ' + inWork,
      'Выполнено: ' + completed,
      'Отказ: ' + rejected,
      '',
      'По статусам:'
    ];

    ecoflotTopEntries_(statusCounts, 20).forEach(function(item) {
      lines.push('• ' + item.key + ': ' + item.value);
    });

    if (cityCol >= 0 && Object.keys(cityCounts).length) {
      lines.push('', 'Топ городов:');
      ecoflotTopEntries_(cityCounts, 5).forEach(function(item) {
        lines.push('• ' + item.key + ': ' + item.value);
      });
    }

    if (sourceCol >= 0 && Object.keys(sourceCounts).length) {
      lines.push('', 'Топ источников:');
      ecoflotTopEntries_(sourceCounts, 5).forEach(function(item) {
        lines.push('• ' + item.key + ': ' + item.value);
      });
    }

    ecoflotSendMainMenu_(chatId, lines.join('\n'));
    return true;
  } catch (error) {
    console.error('Analytics error: ' + (error && error.stack ? error.stack : error));
    ecoflotSendText_(
      chatId,
      '⚠️ Не удалось построить аналитику. ' +
      String(error && error.message ? error.message : error)
    );
    return true;
  }
}

function ecoflotTopEntries_(obj, limit) {
  return Object.keys(obj || {})
    .map(function(key) {
      return { key: key, value: Number(obj[key] || 0) };
    })
    .sort(function(a, b) {
      if (b.value !== a.value) return b.value - a.value;
      return a.key.localeCompare(b.key);
    })
    .slice(0, limit || 10);
}

function ecoflotTriggerManualSearch_(chatId) {
  const props = PropertiesService.getScriptProperties();
  const lock = LockService.getScriptLock();

  if (!lock.tryLock(3000)) {
    ecoflotSendText_(chatId, '⏳ Запуск уже обрабатывается. Повторите чуть позже.');
    return true;
  }

  try {
    const lastRun = Number(props.getProperty('ECOFLOT_MANUAL_SEARCH_STARTED_AT') || 0);
    const now = Date.now();
    const cooldownMs = 5 * 60 * 1000;

    if (lastRun && now - lastRun < cooldownMs) {
      const remain = Math.ceil((cooldownMs - (now - lastRun)) / 60000);
      ecoflotSendText_(
        chatId,
        '⏳ Внеплановый поиск уже запускался недавно. Повторный запуск будет доступен примерно через ' +
        remain +
        ' мин.'
      );
      return true;
    }

    const token =
      props.getProperty('ECOFLOT_GITHUB_TOKEN') ||
      props.getProperty('GITHUB_TOKEN') ||
      props.getProperty('GH_TOKEN') ||
      '';

    if (!token) {
      ecoflotSendText_(
        chatId,
        '⚠️ Кнопка готова, но для запуска GitHub Actions нужно один раз добавить Script Property ECOFLOT_GITHUB_TOKEN.'
      );
      return true;
    }

    const owner = 'Ivankorytnik';
    const repo = 'ECOFLOT';
    const results = [];

    ECOFLOT_MANUAL_SEARCH_WORKFLOWS.forEach(function(workflow) {
      const url =
        'https://api.github.com/repos/' +
        encodeURIComponent(owner) +
        '/' +
        encodeURIComponent(repo) +
        '/actions/workflows/' +
        encodeURIComponent(workflow) +
        '/dispatches';

      const response = UrlFetchApp.fetch(url, {
        method: 'post',
        contentType: 'application/json',
        payload: JSON.stringify({ ref: 'main' }),
        headers: {
          Authorization: 'Bearer ' + token,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28'
        },
        muteHttpExceptions: true
      });

      const code = response.getResponseCode();
      results.push({
        workflow: workflow,
        ok: code === 204,
        code: code,
        body: response.getContentText()
      });
    });

    const failed = results.filter(function(x) { return !x.ok; });

    if (failed.length) {
      const details = failed
        .map(function(x) { return x.workflow + ': HTTP ' + x.code; })
        .join(', ');

      ecoflotSendText_(
        chatId,
        '⚠️ Не все поиски запустились. ' + details
      );
      return true;
    }

    props.setProperty('ECOFLOT_MANUAL_SEARCH_STARTED_AT', String(now));

    ecoflotSendMainMenu_(
      chatId,
      [
        '🚀 Внеплановый поиск запущен по действующему ТЗ.',
        '',
        'Запущен единый последовательный full-cycle:',
        '• Internet Leads',
        '• Telegram / MAX / VK',
        '• Tender Watch',
        '• Object Leads',
        '',
        'Новые результаты будут отправлены в Telegram и записаны в текущий контур CRM / Google Sheets после проверки на дубли.'
      ].join('\n')
    );

    return true;
  } catch (error) {
    console.error('Manual search error: ' + (error && error.stack ? error.stack : error));
    ecoflotSendText_(
      chatId,
      '⚠️ Не удалось запустить внеплановый поиск. ' +
      String(error && error.message ? error.message : error)
    );
    return true;
  } finally {
    try { lock.releaseLock(); } catch (ignore) {}
  }
}

function ecoflotSendText_(chatId, text) {
  telegramApi_('sendMessage', {
    chat_id: String(chatId),
    text: String(text || ''),
    reply_markup: ecoflotMainMenuKeyboard_()
  });
}

function ecoflotSendDocument_(chatId, blob, caption) {
  const props = PropertiesService.getScriptProperties();

  const token =
    props.getProperty('TELEGRAM_BOT_TOKEN') ||
    props.getProperty('BOT_TOKEN') ||
    props.getProperty('TG_BOT_TOKEN') ||
    '';

  if (!token) {
    throw new Error('Не найден TELEGRAM_BOT_TOKEN в Script Properties.');
  }

  const url = 'https://api.telegram.org/bot' + token + '/sendDocument';

  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    payload: {
      chat_id: String(chatId),
      document: blob,
      caption: String(caption || '')
    },
    muteHttpExceptions: true
  });

  const body = response.getContentText();
  let parsed = null;

  try {
    parsed = JSON.parse(body);
  } catch (ignore) {}

  if (response.getResponseCode() < 200 || response.getResponseCode() >= 300 || !parsed || !parsed.ok) {
    throw new Error(
      'Telegram sendDocument HTTP ' +
      response.getResponseCode() +
      ': ' +
      body.slice(0, 500)
    );
  }

  return parsed;
}

/**
 * Optional helper. Run once from Apps Script editor if you want Telegram's
 * slash-command menu in addition to the persistent reply keyboard.
 */
function ecoflotInstallTelegramCommands_() {
  return telegramApi_('setMyCommands', {
    commands: [
      { command: 'menu', description: 'Показать меню ECOFLOT' },
      { command: 'export', description: 'Выгрузить незакрытые заявки в Excel' },
      { command: 'search', description: 'Запустить внеплановый поиск' },
      { command: 'analytics', description: 'Показать аналитику по заявкам' }
    ]
  });
}
