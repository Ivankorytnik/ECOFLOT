const SPREADSHEET_ID = '1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws';
const SHEET_NAME = 'Заявки';

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function getSheet_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('Не найден лист: ' + SHEET_NAME);
  return sheet;
}

function sendTelegram_(p, requestId) {
  try {
    const props = PropertiesService.getScriptProperties();
    const token = props.getProperty('TELEGRAM_BOT_TOKEN');
    const chatId = props.getProperty('TELEGRAM_CHAT_ID');
    if (!token || !chatId) {
      console.log('Telegram settings are not configured');
      return false;
    }

    const lines = [
      '🔔 Новая заявка ECOFLOT',
      '',
      'Тип: ' + (p.type || 'Заявка'),
      'Имя: ' + (p.name || 'Не указано'),
      'Телефон: ' + (p.phone || 'Не указан'),
      'Что вывозим: ' + (p.wasteType || 'Не указано'),
      'Объём: ' + (p.volume || 'Не указан'),
      'Когда: ' + (p.when || 'Не указано'),
      'Адрес: ' + (p.address || 'Не указан'),
      'Источник: ' + (p.source || 'Сайт ECOFLOT'),
      'Комментарий: ' + (p.comment || 'Нет'),
      'ID: ' + requestId
    ];

    const url = 'https://api.telegram.org/bot' + token + '/sendMessage';
    const response = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({
        chat_id: chatId,
        text: lines.join('\n'),
        disable_web_page_preview: true
      }),
      muteHttpExceptions: true
    });

    return response.getResponseCode() >= 200 && response.getResponseCode() < 300;
  } catch (error) {
    console.error('Telegram error: ' + error);
    return false;
  }
}

function ensureHeaders_(sheet) {
  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'Дата','Тип','Имя','Телефон','Что вывозим','Объём','Когда',
      'Адрес','Источник','Статус','Комментарий','Request ID'
    ]);
  }
}

function doPost(e) {
  try {
    const sheet = getSheet_();
    ensureHeaders_(sheet);
    const p = e && e.parameter ? e.parameter : {};
    const action = p.action || 'create';

    if (action === 'updateStatus') {
      const requestId = String(p.requestId || '');
      const status = String(p.status || '');
      if (!requestId || !status) return json_({ok:false,error:'requestId/status required'});

      const values = sheet.getDataRange().getValues();
      const header = values[0].map(String);
      const requestIdCol = header.indexOf('Request ID');
      const statusCol = header.indexOf('Статус');
      if (requestIdCol < 0 || statusCol < 0) return json_({ok:false,error:'columns not found'});

      for (let r = 1; r < values.length; r++) {
        if (String(values[r][requestIdCol]) === requestId) {
          sheet.getRange(r + 1, statusCol + 1).setValue(status);
          SpreadsheetApp.flush();
          return json_({ok:true,action:'updateStatus'});
        }
      }
      return json_({ok:false,error:'lead not found'});
    }

    const requestId = p.requestId || ('ECO-' + new Date().getTime());
    sheet.appendRow([
      new Date(),
      p.type || '',
      p.name || '',
      p.phone || '',
      p.wasteType || '',
      p.volume || '',
      p.when || '',
      p.address || '',
      p.source || 'Сайт ECOFLOT',
      p.status || 'Новая',
      p.comment || '',
      requestId
    ]);
    SpreadsheetApp.flush();
    const telegramSent = sendTelegram_(p, requestId);
    return json_({ok:true,requestId:requestId,telegramSent:telegramSent});
  } catch (error) {
    console.error(error);
    return json_({ok:false,error:String(error)});
  }
}

function doGet(e) {
  try {
    const action = e && e.parameter ? e.parameter.action : '';
    if (action !== 'leads') {
      return json_({ok:true,service:'ECOFLOT webhook',version:'1.1'});
    }

    const sheet = getSheet_();
    ensureHeaders_(sheet);
    const values = sheet.getDataRange().getValues();
    if (values.length < 2) return json_({ok:true,leads:[]});

    const header = values[0].map(String);
    const col = name => header.indexOf(name);

    const leads = values.slice(1).filter(r => r.some(v => v !== '')).map((r, i) => ({
      id: String(r[col('Request ID')] || ('SHEET-' + (i + 2))),
      createdAt: r[col('Дата')] instanceof Date ? r[col('Дата')].toISOString() : String(r[col('Дата')] || ''),
      typeRequest: String(r[col('Тип')] || ''),
      name: String(r[col('Имя')] || ''),
      phone: String(r[col('Телефон')] || ''),
      wasteType: String(r[col('Что вывозим')] || ''),
      volume: String(r[col('Объём')] || ''),
      when: String(r[col('Когда')] || ''),
      address: String(r[col('Адрес')] || ''),
      source: String(r[col('Источник')] || ''),
      status: String(r[col('Статус')] || ''),
      comment: String(r[col('Комментарий')] || '')
    })).reverse().slice(0, 500);

    return json_({ok:true,leads:leads});
  } catch (error) {
    console.error(error);
    return json_({ok:false,error:String(error),leads:[]});
  }
}

function testWrite() {
  const sheet = getSheet_();
  ensureHeaders_(sheet);
  sheet.appendRow([
    new Date(),'ТЕСТ','Иван','+7 999 000-00-00','Строительный мусор',
    '8 м³','Сегодня','Тестовый адрес','Apps Script','Новая',
    'Проверка подключения ECOFLOT','TEST-' + new Date().getTime()
  ]);
  SpreadsheetApp.flush();
}


// ===== ECOFLOT: автоматический мониторинг тендеров ЕИС -> Telegram =====

const TENDER_SEARCHES = [
  'вывоз мусора Одинцово',
  'вывоз отходов Одинцово',
  'строительный мусор Одинцово',
  'вывоз мусора Московская область',
  'вывоз отходов Московская область',
  'транспортирование отходов Московская область',
  'контейнер мусор Московская область',
  'вывоз мусора Москва',
  'вывоз отходов Москва'
];

function tenderRssUrl_(query) {
  const params = [
    'searchString=' + encodeURIComponent(query),
    'morphology=on',
    'search-filter=' + encodeURIComponent('Дате размещения'),
    'pageNumber=1',
    'sortDirection=false',
    'recordsPerPage=_50',
    'showLotsInfoHidden=false',
    'sortBy=UPDATE_DATE',
    'fz44=on',
    'fz223=on',
    'af=on',
    'currencyIdGeneral=-1'
  ];
  return 'https://zakupki.gov.ru/epz/order/extendedsearch/rss.html?' + params.join('&');
}

function tenderText_(element, names) {
  for (let i = 0; i < names.length; i++) {
    const child = element.getChild(names[i]);
    if (child) return String(child.getText() || '').trim();
  }
  return '';
}

function tenderLink_(element) {
  const direct = element.getChild('link');
  if (direct) {
    const href = direct.getAttribute && direct.getAttribute('href');
    if (href) return String(href.getValue() || '').trim();
    const txt = String(direct.getText() || '').trim();
    if (txt) return txt;
  }
  const links = element.getChildren('link');
  for (let i = 0; i < links.length; i++) {
    const href = links[i].getAttribute('href');
    if (href) return String(href.getValue() || '').trim();
  }
  return '';
}

function stripHtml_(s) {
  return String(s || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

function tenderEntries_(xmlText) {
  const doc = XmlService.parse(xmlText);
  const root = doc.getRootElement();
  const rootName = root.getName().toLowerCase();
  let items = [];

  if (rootName === 'rss') {
    const channel = root.getChild('channel');
    items = channel ? channel.getChildren('item') : [];
  } else if (rootName === 'feed') {
    items = root.getChildren('entry');
    if (!items.length) {
      const ns = root.getNamespace();
      items = root.getChildren('entry', ns);
    }
  }

  return items.map(function(item) {
    const title = tenderText_(item, ['title']);
    const description = tenderText_(item, ['description', 'summary', 'content']);
    const link = tenderLink_(item);
    const id = tenderText_(item, ['guid', 'id']) || link || title;
    const date = tenderText_(item, ['pubDate', 'published', 'updated']);
    return {
      id: id,
      title: stripHtml_(title),
      description: stripHtml_(description),
      link: link,
      date: date
    };
  });
}

function tenderLooksRelevant_(entry) {
  const hay = (entry.title + ' ' + entry.description).toLowerCase();

  const serviceWords = [
    'вывоз мусор', 'вывоз отход', 'транспортировани',
    'строительн', 'крупногабарит', 'кгм',
    'контейнер', 'отход', 'мусор'
  ];
  const geoWords = [
    'одинцов', 'московская область', 'московской области',
    'москва', 'западный административный округ', 'зао '
  ];

  const hasService = serviceWords.some(function(w) { return hay.indexOf(w) >= 0; });
  const hasGeo = geoWords.some(function(w) { return hay.indexOf(w) >= 0; });
  return hasService && hasGeo;
}

function tenderFresh_(entry) {
  if (!entry.date) return true;
  const dt = new Date(entry.date);
  if (isNaN(dt.getTime())) return true;
  return (Date.now() - dt.getTime()) <= 7 * 24 * 60 * 60 * 1000;
}

function sendTenderTelegram_(entry, searchQuery) {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('TELEGRAM_BOT_TOKEN');
  const chatId = props.getProperty('TELEGRAM_CHAT_ID');
  if (!token || !chatId) throw new Error('Telegram settings are not configured');

  const text = [
    '📢 Новый тендер для ECOFLOT',
    '',
    entry.title || 'Закупка без названия',
    entry.description ? ('\n' + entry.description.slice(0, 900)) : '',
    '',
    'Поиск: ' + searchQuery,
    entry.date ? ('Дата: ' + entry.date) : '',
    entry.link ? ('Ссылка: ' + entry.link) : ''
  ].filter(Boolean).join('\n');

  const url = 'https://api.telegram.org/bot' + token + '/sendMessage';
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      chat_id: chatId,
      text: text,
      disable_web_page_preview: true
    }),
    muteHttpExceptions: true
  });

  return response.getResponseCode() >= 200 && response.getResponseCode() < 300;
}

function checkTenders() {
  const props = PropertiesService.getScriptProperties();
  const maxPerRun = Number(props.getProperty('TENDER_MAX_PER_RUN') || '8');
  const sentNow = [];
  const errors = [];

  for (let q = 0; q < TENDER_SEARCHES.length; q++) {
    if (sentNow.length >= maxPerRun) break;

    const query = TENDER_SEARCHES[q];
    const url = tenderRssUrl_(query);

    try {
      const response = UrlFetchApp.fetch(url, {
        method: 'get',
        followRedirects: true,
        muteHttpExceptions: true,
        headers: {
          'User-Agent': 'Mozilla/5.0 ECOFLOT Tender Monitor'
        }
      });

      if (response.getResponseCode() < 200 || response.getResponseCode() >= 300) {
        errors.push(query + ': HTTP ' + response.getResponseCode());
        continue;
      }

      const entries = tenderEntries_(response.getContentText('UTF-8'));

      for (let i = 0; i < entries.length; i++) {
        if (sentNow.length >= maxPerRun) break;

        const e = entries[i];
        if (!e.id || !tenderFresh_(e) || !tenderLooksRelevant_(e)) continue;

        const key = 'TENDER_SENT_' + Utilities.base64EncodeWebSafe(
          Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, e.id)
        ).replace(/=+$/g, '');

        if (props.getProperty(key)) continue;

        if (sendTenderTelegram_(e, query)) {
          props.setProperty(key, new Date().toISOString());
          sentNow.push(e.id);
        }
      }
    } catch (err) {
      errors.push(query + ': ' + err);
    }
  }

  console.log(JSON.stringify({
    ok: errors.length === 0,
    sent: sentNow.length,
    errors: errors
  }));

  cleanupTenderHistory_();
}

function cleanupTenderHistory_() {
  const props = PropertiesService.getScriptProperties();
  const all = props.getProperties();
  const cutoff = Date.now() - 90 * 24 * 60 * 60 * 1000;

  Object.keys(all).forEach(function(k) {
    if (k.indexOf('TENDER_SENT_') !== 0) return;
    const dt = new Date(all[k]);
    if (!isNaN(dt.getTime()) && dt.getTime() < cutoff) {
      props.deleteProperty(k);
    }
  });
}

function installTenderMonitor() {
  const fn = 'checkTenders';
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === fn) ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger(fn)
    .timeBased()
    .everyHours(1)
    .create();

  checkTenders();
}
