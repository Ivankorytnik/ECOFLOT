(function(){
  window.ECOFLOT_METRIKA_ID = 113078729;

  (function(m,e,t,r,i,k,a){
    m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
    m[i].l=1*new Date();
    for(var j=0;j<document.scripts.length;j++){if(document.scripts[j].src===r){return;}}
    k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a);
  })(window,document,'script','https://mc.yandex.ru/metrika/tag.js','ym');

  ym(window.ECOFLOT_METRIKA_ID,'init',{
    clickmap:true,
    trackLinks:true,
    accurateTrackBounce:true,
    webvisor:true
  });

  window.ecoflotGoal = function(name, params){
    try {
      document.dispatchEvent(new CustomEvent('ecoflot:goal', {detail:{name:name,params:params||{}}}));
    } catch(e) {}

    try {
      if(typeof window.ym === 'function'){
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