const SPREADSHEET_ID = '1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws';
const SHEET_NAME = 'Заявки';

function doPost(e) {
  try {
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = ss.getSheetByName(SHEET_NAME);

    if (!sheet) {
      throw new Error('Не найден лист: ' + SHEET_NAME);
    }

    const p = e && e.parameter ? e.parameter : {};

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
      p.comment || ''
    ]);

    SpreadsheetApp.flush();

    return ContentService
      .createTextOutput('OK')
      .setMimeType(ContentService.MimeType.TEXT);

  } catch (error) {
    console.error(error);

    return ContentService
      .createTextOutput('ERROR: ' + error)
      .setMimeType(ContentService.MimeType.TEXT);
  }
}

function doGet() {
  return ContentService
    .createTextOutput('ECOFLOT webhook работает')
    .setMimeType(ContentService.MimeType.TEXT);
}

function testWrite() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);

  sheet.appendRow([
    new Date(),
    'ТЕСТ',
    'Иван',
    '+7 999 000-00-00',
    'Строительный мусор',
    '8 м³',
    'Сегодня',
    'Тестовый адрес',
    'Apps Script',
    'Новая',
    'Проверка подключения ECOFLOT'
  ]);

  SpreadsheetApp.flush();
}
