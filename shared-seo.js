(function(){
  try {
    if(!document.querySelector('link[rel="manifest"]')){
      var ml=document.createElement('link');
      ml.rel='manifest';
      ml.href='/manifest.webmanifest';
      document.head.appendChild(ml);
    }
    if(!document.querySelector('script[data-ecoflot-org]')){
      var s=document.createElement('script');
      s.type='application/ld+json';
      s.setAttribute('data-ecoflot-org','');
      s.textContent=JSON.stringify({
        "@context":"https://schema.org",
        "@type":"Organization",
        "@id":"https://ecoflot.pro/#organization",
        "name":"ECOFLOT",
        "url":"https://ecoflot.pro/",
        "logo":"https://ecoflot.pro/favicon.svg"
      });
      document.head.appendChild(s);
    }
  } catch(e){}
})();