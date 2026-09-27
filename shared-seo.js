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
        "@type":"LocalBusiness",
        "@id":"https://ecoflot.pro/#business",
        "name":"ECOFLOT",
        "url":"https://ecoflot.pro/",
        "telephone":"+79687614666",
        "logo":"https://ecoflot.pro/favicon.svg",
        "image":"https://ecoflot.pro/assets/fleet/ecoflot-hero-grapple.webp",
        "address":{
          "@type":"PostalAddress",
          "streetAddress":"ул. Восточная, 25",
          "addressLocality":"Одинцово",
          "addressRegion":"Московская область",
          "addressCountry":"RU"
        },
        "openingHoursSpecification":[{
          "@type":"OpeningHoursSpecification",
          "dayOfWeek":["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
          "opens":"08:00",
          "closes":"20:00"
        }]
      });
      document.head.appendChild(s);
    }
  } catch(e){}
})();