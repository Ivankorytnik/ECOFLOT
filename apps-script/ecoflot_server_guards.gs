/** ECOFLOT focused server guards. No top-level calls, triggers or credentials.
 * Integrate with the CURRENT deployed project; do not replace its whole source.
 * Keep handleLead_'s existing ScriptLock around duplicate-check + append.
 */
function ecoflotTextV3_(value) {
  return String(value == null ? '' : value).trim();
}
function ecoflotUrlV3_(value) {
  var raw = ecoflotTextV3_(value).replace(/&amp;/g, '&');
  var m = raw.match(/^https?:\/\/([^\/?#]+)([^?#]*)(?:\?([^#]*))?(?:#.*)?$/i);
  if (!m || /[@\s]/.test(m[1])) return '';
  var query = (m[3] || '').split('&').filter(function(x) {
    return x && !/^(utm_[^=]*|yclid|gclid|fbclid)=/i.test(x);
  }).sort().join('&');
  return 'https://' + m[1].toLowerCase().replace(/^www\./, '') +
    (m[2] || '/').replace(/\/$/, '') + (query ? '?' + query : '');
}
function ecoflotSpecificUrlV3_(value) {
  var url = ecoflotUrlV3_(value);
  if (!url) return '';
  var path = url.replace(/^https:\/\/[^/]+/, '');
  if (/^https:\/\/profi\.ru\/(rabota|registration)\//i.test(url)) return '';
  // A Profi response URL is one individual order, unlike a category feed.
  // Ignore non-identity query parameters but do not merge different o= IDs.
  var profi = url.match(/^https:\/\/profi\.ru\/backoffice\/n\.php\?(.+)$/i);
  if (profi) {
    var ids = profi[1].split('&').filter(function(q) { return /^o=/.test(q); });
    if (ids.length !== 1 || !/^o=[1-9]\d{5,11}$/.test(ids[0])) return '';
    return 'https://profi.ru/backoffice/n.php?' + ids[0];
  }
  if (/^https:\/\/(?:[^/]+\.)?spectehinfo\.ru\/arenda\//i.test(url)) return '';
  if (/^https:\/\/nerudonline\.ru\/rabota\/samosvaly(?:\?|$)/i.test(url)) return '';
  if (/^https:\/\/exkavator\.ru\/exchange\/rent\/main\.html/i.test(url)) return '';
  if (/\/search(?:\?|\/|$)/i.test(path) &&
      !/^https:\/\/b2b-center\.ru\/search\/number\/l\d{19}-\d+(?:$|\?)/.test(url)) return '';
  if (/(?:\?|&)(?:regNumber|id|noticeId|purchaseId)=\d{5,}(?:&|$)/i.test(url)) return url;
  if (/^https:\/\/t\.me\/[A-Za-z0-9_]+\/\d+(?:\?|$)/.test(url)) return url;
  if (/\/(?:order|orders|request|purchase|procedure|auction|tender|lot\/show)\/[^?]*\d{5,}/i.test(path)) return url;
  if (/^https:\/\/b2b-center\.ru\/search\/number\/l\d{19}-\d+(?:$|\?)/.test(url)) return url;
  return '';
}
function ecoflotProcurementV3_(requestId) {
  var m = ecoflotTextV3_(requestId).match(/^TENDER-(\d{11}|\d{19})$/);
  return m ? m[1] : '';
}
function ecoflotFindDuplicateV3_(sheet, headers, lead) {
  var idCol = headers.indexOf('Request ID');
  var linkCol = headers.indexOf('\u0421\u0441\u044b\u043b\u043a\u0430');
  if (idCol < 0 || linkCol < 0) throw new Error('DEDUPE_SCHEMA_MISMATCH');
  var requestId = ecoflotTextV3_(lead.requestId);
  if (!requestId) throw new Error('DEDUPE_REQUEST_ID_REQUIRED');
  if (sheet.getLastRow() < 2) return null;
  var rows = sheet.getRange(2, 1, sheet.getLastRow()-1, headers.length).getDisplayValues();
  var specific = ecoflotSpecificUrlV3_(lead.link);
  var procurement = ecoflotProcurementV3_(requestId);
  for (var i=rows.length-1; i>=0; i--) {
    var storedId = ecoflotTextV3_(rows[i][idCol]);
    if (!storedId || /^(CRM_ACTION_|CRM-BULK-ACTION|TEST[-_])/i.test(storedId)) continue;
    if (requestId === storedId) return {row:i+2, reason:'request_id', requestId:storedId};
    if (procurement && procurement === ecoflotProcurementV3_(storedId)) {
      return {row:i+2, reason:'procurement_id', requestId:storedId};
    }
    var storedLink = ecoflotSpecificUrlV3_(rows[i][linkCol]);
    if (specific && storedLink === specific) return {row:i+2, reason:'specific_link', requestId:storedId};
  }
  // Neither a shared category URL nor a phone number is an order identifier.
  // Do not use fuzzy title/address similarity as a destructive merge rule.
  return null;
}
function ecoflotQueueItemV3_(kind, key, raw) {
  if (['lead_one','lead','edit','text','text_one'].indexOf(kind) < 0) throw new Error('UNSUPPORTED_QUEUE_KIND');
  var p;
  try { p = JSON.parse(raw); } catch (err) { throw new Error('INVALID_QUEUE_JSON'); }
  if (!p || typeof p !== 'object' || Array.isArray(p)) throw new Error('INVALID_QUEUE_PAYLOAD');
  if (kind === 'lead_one') {
    var chat = ecoflotTextV3_(p.chatId);
    var cb = ecoflotTextV3_(p.callbackKey);
    if (!/^-?\d+$/.test(chat) || !cb || cb.indexOf('|') >= 0) throw new Error('INVALID_QUEUE_RECIPIENT');
    if (key !== cb+'|'+chat) throw new Error('QUEUE_KEY_MISMATCH');
  } else if (kind === 'lead' || kind === 'edit') {
    if (!ecoflotTextV3_(p.callbackKey)) throw new Error('MISSING_CALLBACK_KEY');
  } else {
    if (!ecoflotTextV3_(p.text) || ecoflotTextV3_(p.text).length > 4096) throw new Error('INVALID_QUEUE_TEXT');
    if (kind === 'text_one') {
      // A summary is for exactly one intended recipient. A forged or
      // mismatched queue key must never redirect it to another chat.
      var targetChat = ecoflotTextV3_(p.chatId);
      if (!/^-?\d+$/.test(targetChat)) throw new Error('INVALID_TEXT_ONE_CHAT');
      if (ecoflotTextV3_(key).slice(-targetChat.length - 1) !== '|' + targetChat ||
          ecoflotTextV3_(key).split('|').length < 3) {
        throw new Error('TEXT_ONE_QUEUE_KEY_MISMATCH');
      }
    }
  }
  return p;
}
function ecoflotReceiptV3_(response, expectedChat) {
  var message = response && response.ok === true && response.result;
  if (!message || !message.chat || String(message.chat.id) !== String(expectedChat) ||
      !/^-?\d+$/.test(String(expectedChat)) || !/^[1-9]\d*$/.test(String(message.message_id))) {
    throw new Error('TELEGRAM_RECEIPT_NOT_CONFIRMED');
  }
  return {chatId:String(message.chat.id), messageId:String(message.message_id)};
}
function ecoflotDuplicateAckV3_(incomingId, existing, reason, approvedChats) {
  var routes = existing.telegramRoute;
  if (typeof routes === 'string') {
    try { routes = JSON.parse(routes); } catch (err) { routes = []; }
  }
  if (!Array.isArray(routes)) routes = [];
  routes = routes.filter(function(r) {
    return r && /^-?\d+$/.test(String(r.chatId)) && /^[1-9]\d*$/.test(String(r.messageId));
  });
  var expected = Array.from(new Set((approvedChats || []).map(String)));
  var delivered = expected.length > 0 && expected.every(function(chat) {
    return routes.some(function(r) { return String(r.chatId) === chat; });
  });
  return {ok:true, duplicate:true, requestedRequestId:incomingId,
          requestId:ecoflotTextV3_(existing.requestId), duplicateReason:reason,
          callbackKey:ecoflotTextV3_(existing.callbackKey),
          routes:routes, telegramSent:delivered, telegramQueued:!delivered};
}

/**
 * Read-only verification in the live GAS editor before redeploy.
 * No spreadsheet reads/writes, no Telegram sends, no triggers.
 */
function ecoflotGuardSelfTest20261021_() {
  var profi = 'https://profi.ru/backoffice/n.php?o=95227492';
  var same = 'https://www.profi.ru/backoffice/n.php?utm_source=telegram&o=95227492';
  var other = 'https://profi.ru/backoffice/n.php?o=95250396';
  var samosval = 'https://samosval.info/doska-obyavleniy/trebuyutsya-samosvaly-i-tonary/detail.php?ID=657269';
  var headers = ['Request ID', '\u0421\u0441\u044b\u043b\u043a\u0430', '\u0422\u0435\u043b\u0435\u0444\u043e\u043d'];
  var existing = [['WEB-PROFI-legacy-1', profi, '-'], ['WEB-SAMOSVALIN-657269', samosval, '-']];
  var sample = {
    getLastRow: function() { return existing.length + 1; },
    getRange: function() {
      return {getDisplayValues: function() { return existing; }};
    }
  };
  var tests = [
    {name:'profi_exact_source_order', ok:ecoflotSpecificUrlV3_(profi) === ecoflotSpecificUrlV3_(same)},
    {name:'different_profi_orders', ok:ecoflotSpecificUrlV3_(profi) !== ecoflotSpecificUrlV3_(other)},
    {name:'profi_duplicate', ok:(ecoflotFindDuplicateV3_(sample,headers,{requestId:'new',link:same})||{}).reason === 'specific_link'},
    {name:'samosval_duplicate', ok:(ecoflotFindDuplicateV3_(sample,headers,{requestId:'new2',link:samosval})||{}).reason === 'specific_link'},
    {name:'different_order_not_merged', ok:ecoflotFindDuplicateV3_(sample,headers,{requestId:'other',link:other}) === null},
    {name:'hook_in_live_findDuplicate', ok:typeof findDuplicate_ === 'function' &&
      String(findDuplicate_).indexOf('ecoflotFindDuplicateV3_') >= 0}
  ];
  var result = {ok:tests.every(function(t){return t.ok;}),build:'2026-10-21-guard-v3',readOnly:true,tests:tests};
  console.log(JSON.stringify(result));
  if (!result.ok) throw new Error('ECOFLOT_GUARD_NOT_INSTALLED_OR_TEST_FAILED: ' + JSON.stringify(result));
  return result;
}
