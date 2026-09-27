#!/usr/bin/env python3
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://ecoflot.pro"

SERVICES = {
    "arenda-samosvala": {
        "name": "Аренда самосвала",
        "lead": "Самосвалы ECOFLOT для вывоза грунта, строительных отходов, боя бетона и перевозки сыпучих материалов.",
        "works": ["вывоз грунта", "бой бетона и кирпича", "песок и щебень", "очистка строительной площадки"],
        "fleet": "Самосвалы",
    },
    "ekskavator-pogruzchik": {
        "name": "Экскаватор-погрузчик",
        "lead": "Экскаватор-погрузчик ECOFLOT для погрузки, земляных работ, расчистки и подготовки площадки.",
        "works": ["погрузка грунта и мусора", "разработка и обратная засыпка", "расчистка территории", "погрузка самосвалов"],
        "fleet": "Экскаватор-погрузчик",
    },
    "arenda-multilifta": {
        "name": "Аренда мультилифта",
        "lead": "Мультилифт ECOFLOT для сменных контейнеров 20-27 м³, крупных объёмов строительных и производственных отходов.",
        "works": ["контейнеры 20 и 27 м³", "строительные отходы", "крупногабаритный мусор", "производственные отходы"],
        "fleet": "Мультилифты",
    },
    "arenda-bunkerovoza": {
        "name": "Аренда бункеровоза",
        "lead": "Бункеровоз ECOFLOT для контейнеров 8 м³, ремонта, демонтажа и площадок с ограниченным подъездом.",
        "works": ["контейнер 8 м³", "отходы ремонта", "кирпич и бетон", "древесина и КГМ"],
        "fleet": "Бункеровозы",
    },
    "lomovoz-s-greiferom": {
        "name": "Ломовоз с грейфером",
        "lead": "Ломовоз ECOFLOT с КМУ и грейфером для механизированной погрузки металла, древесины и крупногабаритных отходов.",
        "works": ["металлолом", "древесина", "КГМ", "механизированная погрузка"],
        "fleet": "Ломовоз с КМУ и грейфером",
    },
    "raschistka-territorii": {
        "name": "Расчистка территории",
        "lead": "Комплексная расчистка территории техникой ECOFLOT: погрузка, контейнеры, самосвалы и вывоз.",
        "works": ["погрузка отходов", "вывоз грунта", "порубочные остатки", "подготовка площадки"],
        "fleet": "Экскаватор-погрузчик + самосвалы / контейнеры",
    },
    "demontazh-i-vyvoz": {
        "name": "Демонтаж и вывоз",
        "lead": "Демонтажные работы с погрузкой и вывозом отходов собственной техникой ECOFLOT.",
        "works": ["разбор конструкций", "погрузка", "контейнерный вывоз", "бой бетона и кирпича"],
        "fleet": "Экскаватор-погрузчик + контейнерная техника",
    },
    "vyvoz-kgm": {
        "name": "Вывоз КГМ",
        "lead": "Вывоз крупногабаритного мусора, мебели, древесины и хлама техникой ECOFLOT.",
        "works": ["мебель и хлам", "крупногабарит", "древесина", "производственные отходы"],
        "fleet": "Бункеровоз / мультилифт / ломовоз",
    },
}

GEOS = {
    "odincovo": ("Одинцово", "Одинцово и ближайшие районы обслуживаем с приоритетной логистикой от базы ECOFLOT."),
    "zvenigorod": ("Звенигород", "Работаем по Звенигороду и западному направлению Московской области."),
    "krasnogorsk": ("Красногорск", "Выезжаем в Красногорск и прилегающие районы, подбирая технику под ограничения площадки."),
    "istra": ("Истра", "Обслуживаем Истру и запад Московской области, включая строительные и загородные объекты."),
    "aprelevka": ("Апрелевка", "Работаем по Апрелевке и Киевскому направлению с собственной техникой."),
    "naro-fominsk": ("Наро-Фоминск", "Выезжаем в Наро-Фоминск и по Минскому/Киевскому направлениям."),
    "novaya-moskva": ("Новая Москва", "Обслуживаем Новую Москву, строительные площадки, коммерческие и частные объекты."),
    "rublevka": ("Рублёво-Успенское направление", "Работаем по Рублёво-Успенскому направлению с учётом пропусков, подъездов и ограничений площадки."),
}

STYLE = """
body{margin:0;font-family:Arial,sans-serif;color:#17201a;background:#fff}.wrap{width:min(1040px,calc(100% - 32px));margin:auto}.top{display:flex;justify-content:space-between;align-items:center;padding:22px 0}.brand{font-weight:800;font-size:22px;color:#17201a;text-decoration:none}.cta{background:#1f8f5f;color:#fff;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:700}.hero{padding:62px 0 36px}.eyebrow{color:#1f8f5f;font-weight:800;font-size:13px;text-transform:uppercase;letter-spacing:.06em}h1{font-size:46px;line-height:1.06;margin:12px 0 18px;max-width:900px}h2{font-size:30px;margin-top:0}p,li{font-size:17px;line-height:1.65;color:#59665d}.section{padding:42px 0}.alt{background:#f3f6f3}.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}.card{border:1px solid #e5ebe6;border-radius:16px;padding:20px;background:#fff}.quick{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}.quick span{background:#edf6f0;border-radius:999px;padding:8px 11px;font-size:13px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.secondary{border:1px solid #ccd8cf;color:#1f6f4d;text-decoration:none;padding:12px 18px;border-radius:10px;font-weight:700}.footer{border-top:1px solid #e5ebe6;padding:24px 0;color:#7c887f;font-size:13px}@media(max-width:760px){h1{font-size:35px}.grid{grid-template-columns:1fr}}
"""

def page(service_slug, service, geo_slug, geo):
    city, geo_text = geo
    title = f"{service['name']} в {city} | ECOFLOT"
    desc = f"{service['name']} в {city}. {service['lead']} Собственная техника ECOFLOT, заявка онлайн."
    slug = f"{service_slug}-{geo_slug}"
    canonical = f"{BASE}/{slug}/"
    works = "".join(f"<li>{escape(x)}</li>" for x in service["works"])
    related = (
        '<a class="secondary" href="/vyvoz-stroitelnogo-musora/">Строительный мусор</a>'
        '<a class="secondary" href="/vyvoz-grunta/">Вывоз грунта</a>'
        '<a class="secondary" href="/uslugi/">Все услуги</a>'
    )
    schema = f'''{{"@context":"https://schema.org","@type":"Service","name":"{escape(service["name"])} в {escape(city)}","provider":{{"@id":"https://ecoflot.pro/#business"}},"areaServed":"{escape(city)}","url":"{canonical}"}}'''
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(desc)}"><meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{canonical}"><link rel="icon" href="/favicon.svg">
<script type="application/ld+json">{schema}</script><style>{STYLE}</style><script src="/marketing.js" defer></script><script src="/analytics.js" defer></script></head>
<body><header class="wrap top"><a class="brand" href="/">ECOFLOT</a><a class="cta" href="/#urgent">Срочно нужна машина</a></header><main>
<section class="wrap hero"><div class="eyebrow">{escape(service["fleet"])} ECOFLOT</div><h1>{escape(service["name"])} в {escape(city)}</h1><p>{escape(service["lead"])} {escape(geo_text)}</p>
<div class="quick"><span>Собственная техника</span><span>Заявка онлайн</span><span>Частные и B2B-заказы</span><span>Запад Москвы и МО</span></div>
<div class="actions"><a class="cta" href="/#leadform">Оставить заявку</a><a class="secondary" href="/#urgent">Нужна техника сегодня</a></div></section>
<section class="section alt"><div class="wrap grid"><div class="card"><h2>Что выполняем</h2><ul>{works}</ul></div>
<div class="card"><h2>Как подбираем технику</h2><p>Учитываем тип материала, объём, подъезд к объекту, возможность механизированной погрузки и требуемый срок. При необходимости комбинируем экскаватор-погрузчик, самосвал и контейнерную технику.</p></div></div></section>
<section class="section"><div class="wrap"><h2>Заказать в {escape(city)}</h2><p>Укажите адрес, задачу и телефон. Заявка попадёт в CRM ECOFLOT и менеджер увидит её вместе с источником страницы.</p><div class="actions"><a class="cta" href="/#leadform">Отправить заявку</a>{related}</div></div></section>
</main><footer class="footer"><div class="wrap">ECOFLOT · {escape(service["name"])} · {escape(city)}</div></footer></body></html>'''

created = 0
for service_slug, service in SERVICES.items():
    for geo_slug, geo in GEOS.items():
        slug = f"{service_slug}-{geo_slug}"
        dest = ROOT / slug / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page(service_slug, service, geo_slug, geo), encoding="utf-8")
        created += 1

print(f"Generated {created} growth pages")
