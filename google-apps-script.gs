const SPREADSHEET_ID = '1wQQhP81P_07QkAGB5KzI20w9PBqN55y9pUs6WUnA8Ws';
const SHEET_NAME = 'Заявки';

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents || '{}');
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sh = ss.getSheetByName(SHEET_NAME);

    sh.appendRow([
      new Date(),
      data.type || '',
      data.name || '',
      data.phone || '',
      data.wasteType || '',
      data.volume || '',
      data.when || '',
      data.address || '',
      data.source || 'Сайт ECOFLOT',
      data.status || 'Новая',
      data.comment || ''
    ]);

    return ContentService
      .createTextOutput(JSON.stringify({ok:true}))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ok:false,error:String(err)}))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
