(function(){
  try {
    var p = new URLSearchParams(location.search);
    var keys = ['utm_source','utm_medium','utm_campaign','utm_content','utm_term','yclid','gclid'];
    var current = {};
    keys.forEach(function(k){ var v=p.get(k); if(v) current[k]=v; });
    current.landing = location.pathname || '/';
    current.referrer = document.referrer || '';
    current.capturedAt = new Date().toISOString();

    var saved = null;
    try { saved = JSON.parse(localStorage.getItem('ecoflot_first_touch') || 'null'); } catch(e){}
    if(!saved || (!saved.utm_source && current.utm_source)){
      localStorage.setItem('ecoflot_first_touch', JSON.stringify(current));
      saved = current;
    } else if(!saved){
      localStorage.setItem('ecoflot_first_touch', JSON.stringify(current));
      saved = current;
    }
    window.ECOFLOT_ATTRIBUTION = saved || current;
  } catch(e) {
    window.ECOFLOT_ATTRIBUTION = {landing:location.pathname || '/',referrer:document.referrer || ''};
  }
})();