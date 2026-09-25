(function(){
  window.ECOFLOT_METRIKA_ID = window.ECOFLOT_METRIKA_ID || null;

  window.ecoflotGoal = function(name, params){
    try {
      document.dispatchEvent(new CustomEvent('ecoflot:goal', {detail:{name:name,params:params||{}}}));
    } catch(e) {}

    try {
      if(window.ECOFLOT_METRIKA_ID && typeof window.ym === 'function'){
        window.ym(window.ECOFLOT_METRIKA_ID, 'reachGoal', name, params || {});
      }
    } catch(e) {}

    try {
      if(Array.isArray(window.dataLayer)){
        window.dataLayer.push({event:name, ...(params||{})});
      }
    } catch(e) {}
  };
})();