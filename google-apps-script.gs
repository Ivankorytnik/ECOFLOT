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
    return json_({ok:true,requestId:requestId});
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
