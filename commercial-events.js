(function(){
  function send(name, params){
    try{
      if(typeof window.ecoflotGoal==='function'){
        window.ecoflotGoal(name, params||{});
      }
    }catch(e){}
  }

  function bind(){
    document.addEventListener('click',function(e){
      var a=e.target && e.target.closest ? e.target.closest('a') : null;
      if(!a) return;
      var href=a.getAttribute('href')||'';
      if(href.indexOf('tel:')===0){
        send('phone_click',{path:location.pathname});
      }else if(href==='/#leadform' || href==='#leadform'){
        send('lead_cta_click',{path:location.pathname,text:(a.textContent||'').trim().slice(0,80)});
      }else if(href.indexOf('/kalkulyator/')===0){
        send('calculator_open',{path:location.pathname});
      }
    },true);
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',bind);
  }else{
    bind();
  }
})();