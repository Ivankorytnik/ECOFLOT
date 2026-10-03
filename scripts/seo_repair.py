#!/usr/bin/env python3
from pathlib import Path
from html import escape
import json, re

ROOT=Path(__file__).resolve().parents[1]
PHONE_HREF="+79687614666"
PHONE_TEXT="+7 968 761-46-66"
BASE="https://ecoflot.pro"

SERVICES={
"arenda-samosvala":{"name":"Аренда самосвала","fleet":"Самосвалы","lead":"Самосвалы ECOFLOT для вывоза грунта, строительных отходов, боя бетона и перевозки сыпучих материалов.","works":["вывоз грунта и инертных материалов","бой бетона и кирпича","песок и щебень","очистка строительной площадки"],"scenario":"Если материал уже собран и есть подъезд для крупной машины, самосвал подходит для вывоза больших объёмов. Если требуется погрузка, в заявку добавляем экскаватор-погрузчик."},
"ekskavator-pogruzchik":{"name":"Экскаватор-погрузчик","fleet":"Экскаватор-погрузчик","lead":"Экскаватор-погрузчик ECOFLOT для погрузки, земляных работ, расчистки и подготовки площадки.","works":["погрузка грунта и мусора","разработка и обратная засыпка","расчистка территории","погрузка самосвалов"],"scenario":"Подходит, когда отходы или грунт нельзя загрузить вручную. Для вывоза сразу подбираем самосвал или контейнерную технику под объём и доступ к площадке."},
"arenda-multilifta":{"name":"Аренда мультилифта","fleet":"Мультилифты","lead":"Мультилифт ECOFLOT для сменных контейнеров 20–27 м³ и крупных объёмов строительных и производственных отходов.","works":["контейнеры 20 и 27 м³","строительные отходы","крупногабаритный мусор","регулярная смена контейнеров"],"scenario":"Подходит для объектов, где отходы накапливаются партиями. Перед подачей важно проверить место для установки контейнера и возможность манёвра автомобиля."},
"arenda-bunkerovoza":{"name":"Аренда бункеровоза","fleet":"Бункеровозы","lead":"Бункеровоз ECOFLOT для контейнеров 8 м³, ремонта, демонтажа и площадок с ограниченным объёмом отходов.","works":["контейнер 8 м³","отходы ремонта","кирпич и бетон","древесина и КГМ"],"scenario":"Контейнер 8 м³ удобен для ремонта, небольшого демонтажа и поэтапного вывоза. При расчёте проверяем состав отходов, подъезд и место установки."},
"lomovoz-s-greiferom":{"name":"Ломовоз с грейфером","fleet":"Ломовоз с КМУ и грейфером","lead":"Ломовоз ECOFLOT с КМУ и грейфером для механизированной погрузки металла, древесины и крупногабаритных отходов.","works":["металлолом","древесина и ветки","КГМ","механизированная погрузка"],"scenario":"Выбираем ломовоз, когда материал лежит россыпью и его удобнее грузить грейфером. До выезда уточняем габариты, плотность материала и свободное место для работы стрелы."},
"raschistka-territorii":{"name":"Расчистка территории","fleet":"Комплекс техники","lead":"Комплексная расчистка территории техникой ECOFLOT: погрузка, контейнеры, самосвалы и вывоз.","works":["погрузка отходов","вывоз грунта","порубочные остатки","подготовка площадки"],"scenario":"Для расчистки сначала оцениваем, что находится на участке: грунт, КГМ, древесина или смешанные отходы. Затем подбираем связку техники под фактическую задачу."},
"demontazh-i-vyvoz":{"name":"Демонтаж и вывоз","fleet":"Демонтаж + вывоз","lead":"Демонтажные работы с погрузкой и вывозом отходов собственной техникой ECOFLOT.","works":["разбор конструкций","механизированная погрузка","контейнерный вывоз","бой бетона и кирпича"],"scenario":"При демонтаже заранее разделяем этапы: разбор, накопление, погрузка и вывоз. Это помогает подобрать контейнеры и технику без лишних простоев на объекте."},
"vyvoz-kgm":{"name":"Вывоз КГМ","fleet":"Бункеровоз / мультилифт / ломовоз","lead":"Вывоз крупногабаритного мусора, мебели, древесины и хлама техникой ECOFLOT.","works":["мебель и хлам","крупногабаритные отходы","древесина","объёмные отходы после расчистки"],"scenario":"Для КГМ техника зависит не только от объёма, но и от того, нужна ли механизированная погрузка. Небольшие партии можно вывезти контейнером, крупные навалы — техникой с грейфером."}
}
GEOS={
"odincovo":{"name":"Одинцово","loc":"в Одинцово","text":"Одинцово и ближайшие районы обслуживаем с учётом маршрута от базы ECOFLOT.","condition":"При подаче учитываем адрес, время заезда, ограничения двора или стройплощадки и место для манёвра техники.","faq":"Для точного расчёта достаточно адреса, типа материала, примерного объёма и информации о том, нужна ли погрузка."},
"zvenigorod":{"name":"Звенигород","loc":"в Звенигороде","text":"Работаем по Звенигороду и западному направлению Московской области.","condition":"До подтверждения подачи проверяем расстояние, подъезд к объекту и возможность безопасно установить контейнер или работать крупной техникой.","faq":"Для загородного объекта полезно заранее прислать точку на карте и описать ширину подъезда."},
"krasnogorsk":{"name":"Красногорск","loc":"в Красногорске","text":"Выезжаем в Красногорск и прилегающие районы, подбирая технику под условия конкретной площадки.","condition":"В расчёте учитываем городской адрес, режим въезда на объект, стеснённость площадки и необходимость механизированной погрузки.","faq":"Если заезд ограничен по времени или шлагбаумом, это лучше указать сразу."},
"istra":{"name":"Истра","loc":"в Истре","text":"Обслуживаем Истру и запад Московской области, включая строительные и загородные объекты.","condition":"Для загородных адресов заранее проверяем точку подачи, качество подъезда и свободное место для разворота или установки контейнера.","faq":"Если объект находится не в самой Истре, отправьте населённый пункт или геометку."},
"aprelevka":{"name":"Апрелевка","loc":"в Апрелевке","text":"Работаем по Апрелевке и Киевскому направлению с собственной техникой.","condition":"Перед выездом уточняем точный адрес, доступ на территорию и место для контейнера, самосвала или работы погрузчика.","faq":"Для частного участка полезно указать тип покрытия и возможность подъезда тяжёлой техники к месту погрузки."},
"naro-fominsk":{"name":"Наро-Фоминск","loc":"в Наро-Фоминске","text":"Выезжаем в Наро-Фоминск и по западному направлению Московской области.","condition":"Стоимость подачи зависит от конкретного адреса, типа техники, объёма работ и необходимости ожидания или дополнительной погрузки.","faq":"Чтобы не считать маршрут приблизительно, пришлите адрес или точку объекта и коротко опишите задачу."},
"novaya-moskva":{"name":"Новая Москва","loc":"в Новой Москве","text":"Обслуживаем Новую Москву: строительные площадки, коммерческие и частные объекты.","condition":"Учитываем конкретное поселение, пропускной режим объекта, место для манёвра и подходящий тип техники.","faq":"В Новой Москве важен точный адрес: расстояние и условия въезда могут заметно отличаться даже у соседних объектов."},
"rublevka":{"name":"Рублёво-Успенское направление","loc":"на Рублёво-Успенском направлении","text":"Работаем по Рублёво-Успенскому направлению с учётом подъездов и ограничений конкретной площадки.","condition":"Перед подачей уточняем режим доступа, ширину проезда, возможность разворота и место для безопасной работы техники.","faq":"Если въезд на территорию только по предварительному согласованию, сообщите об этом при заявке."}
}
STYLE="""body{margin:0;font-family:Arial,sans-serif;color:#17201a;background:#fff}.wrap{width:min(1040px,calc(100% - 32px));margin:auto}.top{display:flex;justify-content:space-between;align-items:center;padding:22px 0;gap:16px}.brand{font-weight:800;font-size:22px;color:#17201a;text-decoration:none}.top-actions{display:flex;gap:9px;flex-wrap:wrap}.cta{background:#1f8f5f;color:#fff;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:700}.call{border:1px solid #cfdad2;color:#17201a;text-decoration:none;padding:11px 16px;border-radius:10px;font-weight:700}.hero{padding:58px 0 34px}.eyebrow{color:#1f8f5f;font-weight:800;font-size:13px;text-transform:uppercase;letter-spacing:.06em}h1{font-size:44px;line-height:1.08;margin:12px 0 18px;max-width:920px}h2{font-size:29px;margin-top:0}p,li{font-size:17px;line-height:1.65;color:#59665d}.section{padding:40px 0}.alt{background:#f3f6f3}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card{border:1px solid #e5ebe6;border-radius:16px;padding:20px;background:#fff}.quick{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}.quick span{background:#edf6f0;border-radius:999px;padding:8px 11px;font-size:13px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.secondary{border:1px solid #ccd8cf;color:#1f6f4d;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:700}.footer{border-top:1px solid #e5ebe6;padding:24px 0;color:#7c887f;font-size:13px}.footer a{color:#1f6f4d}@media(max-width:760px){h1{font-size:34px}.grid{grid-template-columns:1fr}.top{align-items:flex-start}}"""
CATALOG_STYLE="""body{margin:0;font-family:Arial,sans-serif;color:#17201a}.wrap{width:min(1120px,calc(100% - 32px));margin:auto}.top{display:flex;justify-content:space-between;align-items:center;padding:22px 0}.brand{font-weight:800;font-size:22px;color:#17201a;text-decoration:none}.actions{display:flex;gap:8px}.btn{padding:11px 15px;border-radius:10px;text-decoration:none;font-weight:700}.primary{background:#1f8f5f;color:#fff}.phone{border:1px solid #ccd8cf;color:#17201a}.hero{padding:54px 0 28px}h1{font-size:46px;line-height:1.08;margin:0 0 14px}p{color:#5f6b63;font-size:17px;line-height:1.6}.section{padding:34px 0 54px}.alt{background:#f3f6f3}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card{border:1px solid #e5ebe6;border-radius:16px;padding:20px;background:#fff}.card h2{margin-top:0}.linkgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.linkgrid a{color:#1f6f4d;text-decoration:none;line-height:1.35}.footer{border-top:1px solid #e5ebe6;padding:24px 0;color:#7c887f}.footer a{color:#1f6f4d}@media(max-width:760px){h1{font-size:35px}.grid,.linkgrid{grid-template-columns:1fr}}"""

def growth_page(ss,s,gs,g):
    slug=f"{ss}-{gs}"; canonical=f"{BASE}/{slug}/"
    title=f"{s['name']} {g['loc']} | ECOFLOT"
    desc=f"{s['name']} {g['loc']}: подберём технику под объём, подъезд и задачу. Собственный парк ECOFLOT, заявка онлайн или по телефону."
    works="".join(f"<li>{escape(x)}</li>" for x in s["works"])
    schema=json.dumps({"@context":"https://schema.org","@type":"Service","name":f"{s['name']} {g['loc']}","provider":{"@id":"https://ecoflot.pro/#business"},"areaServed":g["name"],"url":canonical},ensure_ascii=False)
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><meta name="description" content="{escape(desc)}"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{canonical}"><link rel="icon" href="/favicon.svg"><script type="application/ld+json">{schema}</script><style>{STYLE}</style><script src="/marketing.js" defer></script><script src="/analytics.js" defer></script></head><body><header class="wrap top"><a class="brand" href="/">ECOFLOT</a><div class="top-actions"><a class="call" href="tel:{PHONE_HREF}">Позвонить</a><a class="cta" href="/#leadform">Оставить заявку</a></div></header><main><section class="wrap hero"><div class="eyebrow">{escape(s["fleet"])} ECOFLOT</div><h1>{escape(s["name"])} {escape(g["loc"])}</h1><p>{escape(s["lead"])} {escape(g["text"])}</p><div class="quick"><span>Собственная техника</span><span>Москва и МО</span><span>Частные и B2B-заказы</span><span>Расчёт по адресу</span></div><div class="actions"><a class="cta" href="/#leadform">Рассчитать подачу</a><a class="call" href="tel:{PHONE_HREF}">{PHONE_TEXT}</a></div></section><section class="section alt"><div class="wrap grid"><div class="card"><h2>Что выполняем</h2><ul>{works}</ul></div><div class="card"><h2>Условия подачи {escape(g["loc"])}</h2><p>{escape(g["condition"])}</p><p>Финальную стоимость подтверждаем после адреса, объёма, состава материала и требуемого времени подачи.</p></div></div></section><section class="section"><div class="wrap grid"><div class="card"><h2>Типовой сценарий</h2><p>{escape(s["scenario"])}</p><p>Это пример подбора техники, а не выдуманный «выполненный заказ»: фактическая схема зависит от объекта.</p></div><div class="card"><h2>Что сообщить менеджеру</h2><p>{escape(g["faq"])}</p><p>Если есть фото материала и подъезда, приложите их к заявке — это помогает точнее подобрать машину.</p></div></div></section><section class="section alt"><div class="wrap"><h2>Заказать {escape(g["loc"])}</h2><p>Позвоните или оставьте адрес и телефон в форме. Менеджер проверит доступную технику и рассчитает подачу под конкретный объект.</p><div class="actions"><a class="call" href="tel:{PHONE_HREF}">Позвонить {PHONE_TEXT}</a><a class="cta" href="/#leadform">Отправить заявку</a><a class="secondary" href="/uslugi/">Все услуги</a><a class="secondary" href="/zony-raboty/">География</a></div></div></section></main><footer class="footer"><div class="wrap">ECOFLOT · {escape(s["name"])} · {escape(g["name"])} · <a href="tel:{PHONE_HREF}">{PHONE_TEXT}</a></div></footer></body></html>'''

def service_cards():
    blocks=[]
    for ss,s in SERVICES.items():
        links="".join(f'<a href="/{ss}-{gs}/">{escape(g["name"])}</a>' for gs,g in GEOS.items())
        blocks.append(f'<div class="card"><h2>{escape(s["name"])}</h2><p>{escape(s["lead"])}</p><div class="linkgrid">{links}</div></div>')
    return "".join(blocks)

def geo_cards():
    blocks=[]
    for gs,g in GEOS.items():
        links="".join(f'<a href="/{ss}-{gs}/">{escape(s["name"])}</a>' for ss,s in SERVICES.items())
        blocks.append(f'<div class="card"><h2>{escape(g["name"])}</h2><p>{escape(g["text"])}</p><div class="linkgrid">{links}</div></div>')
    return "".join(blocks)

def header():
    return f'<header class="wrap top"><a class="brand" href="/">ECOFLOT</a><div class="actions"><a class="btn phone" href="tel:{PHONE_HREF}">Позвонить</a><a class="btn primary" href="/#leadform">Заявка</a></div></header>'

def footer():
    return f'<footer class="footer"><div class="wrap">ECOFLOT · <a href="tel:{PHONE_HREF}">{PHONE_TEXT}</a></div></footer>'

def catalog_page(kind):
    if kind=="uslugi":
        title="Услуги ECOFLOT: вывоз, погрузка и спецтехника"; canon="/uslugi/"; h1="Услуги ECOFLOT"
        desc="Каталог услуг ECOFLOT и география подачи: самосвалы, мультилифты, бункеровозы, ломовозы, экскаватор-погрузчик, расчистка и вывоз КГМ."
        intro="Вывозим отходы и грунт, выполняем погрузку, расчистку, земляные и демонтажные работы своей техникой."
        body=service_cards()
    elif kind=="zones":
        title="География работы ECOFLOT | Москва и Московская область"; canon="/zony-raboty/"; h1="География работы ECOFLOT"
        desc="География подачи техники ECOFLOT: Одинцово, Звенигород, Красногорск, Истра, Апрелевка, Наро-Фоминск, Новая Москва и Рублёво-Успенское направление."
        intro="Подаём собственную технику по западной части Москвы и Московской области. Возможность подачи и стоимость считаем по точному адресу."
        body=geo_cards()
    else:
        title="Карта сайта ECOFLOT | Услуги и география"; canon="/karta-saita/"; h1="Карта сайта ECOFLOT"
        desc="HTML-карта сайта ECOFLOT: основные услуги, география работы и прямые ссылки на страницы спецтехники по городам и направлениям."
        intro="Основные разделы и все страницы услуг по географии."
        core='<div class="card"><h2>Основные страницы</h2><div class="linkgrid"><a href="/uslugi/">Все услуги</a><a href="/zony-raboty/">География</a><a href="/ceny/">Цены</a><a href="/faq/">Частые вопросы</a><a href="/vyvoz-stroitelnogo-musora/">Строительный мусор</a><a href="/vyvoz-grunta/">Вывоз грунта</a><a href="/arenda-konteynera/">Аренда контейнера</a><a href="/kalkulyator/">Калькулятор</a></div></div>'
        body=core+service_cards()
    return f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><meta name="description" content="{desc}"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{BASE}{canon}"><link rel="icon" href="/favicon.svg"><style>{CATALOG_STYLE}</style><script src="/marketing.js" defer></script><script src="/analytics.js" defer></script></head><body>{header()}<main><section class="wrap hero"><h1>{h1}</h1><p>{intro}</p></section><section class="section alt"><div class="wrap grid">{body}</div></section></main>{footer()}</body></html>'

changed=0
growth=set()
for ss,s in SERVICES.items():
    for gs,g in GEOS.items():
        p=ROOT/f"{ss}-{gs}"/"index.html"
        p.write_text(growth_page(ss,s,gs,g),encoding="utf-8")
        growth.add(p.resolve()); changed+=1

(ROOT/"uslugi"/"index.html").write_text(catalog_page("uslugi"),encoding="utf-8")
(ROOT/"zony-raboty"/"index.html").write_text(catalog_page("zones"),encoding="utf-8")
(ROOT/"karta-saita"/"index.html").write_text(catalog_page("map"),encoding="utf-8")
changed+=3

strip=f'<section data-nosnippet style="border-top:1px solid #e5ebe6;padding:18px 16px;text-align:center;font-family:Arial,sans-serif"><a href="tel:{PHONE_HREF}" style="display:inline-block;text-decoration:none;font-weight:700;color:#1f6f4d">Позвонить ECOFLOT: {PHONE_TEXT}</a></section>'
for p in ROOT.rglob("index.html"):
    if p.resolve() in growth or p == ROOT/"index.html" or p in (ROOT/"uslugi"/"index.html",ROOT/"zony-raboty"/"index.html",ROOT/"karta-saita"/"index.html"):
        continue
    txt=p.read_text(encoding="utf-8")
    if f'href="tel:{PHONE_HREF}"' not in txt and f"href='tel:{PHONE_HREF}'" not in txt:
        txt=re.sub(r"</body>",strip+"</body>",txt,count=1,flags=re.I)
        p.write_text(txt,encoding="utf-8"); changed+=1

m=ROOT/"marketing.js"
txt=m.read_text(encoding="utf-8")
txt=txt.replace('<a class="secondary" href="/ceny/">Цены</a>',f'<a class="secondary" href="tel:{PHONE_HREF}">Позвонить</a>')
m.write_text(txt,encoding="utf-8")

print(f"SEO repair complete; touched {changed} HTML pages")
