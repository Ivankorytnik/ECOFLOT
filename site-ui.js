(function(){
  function add(){
    if(document.querySelector('.ecoflot-mobile-cta')) return;
    var style=document.createElement('style');
    style.textContent='.ecoflot-mobile-cta{display:none}@media(max-width:760px){body{padding-bottom:74px}.ecoflot-mobile-cta{display:flex;position:fixed;left:12px;right:12px;bottom:12px;z-index:9999;background:#17201a;border-radius:14px;padding:10px;gap:10px;box-shadow:0 12px 32px rgba(0,0,0,.24)}.ecoflot-mobile-cta a{flex:1;text-align:center;text-decoration:none;border-radius:10px;padding:12px 10px;font:700 14px Arial,sans-serif}.ecoflot-mobile-cta .primary{background:#1f8f5f;color:#fff}.ecoflot-mobile-cta .secondary{background:#fff;color:#17201a}}';
    document.head.appendChild(style);
    var bar=document.createElement('div');
    bar.className='ecoflot-mobile-cta';
    bar.setAttribute('data-nosnippet','');
    bar.innerHTML='<a class="primary" href="/#leadform">Оставить заявку</a><a class="secondary" href="/ceny/">Цены</a>';
    document.body.appendChild(bar);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',add); else add();
})();