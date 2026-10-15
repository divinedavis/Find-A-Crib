#!/usr/bin/env python3
"""The App Store listing in New York's other big languages (owner,
2026-10-13: "lets support multiple languages").

Spanish, Chinese (Simplified and Traditional), Russian and Korean — the
largest non-English languages among NYC renters that the App Store
supports (Bengali and Haitian Creole are NYC top-ten languages but not App
Store locales). English stays in asc_metadata.py.

    ~/.venvs/dhcr-map/bin/python scripts/asc_localizations.py          # dry run: lengths only
    ~/.venvs/dhcr-map/bin/python scripts/asc_localizations.py --apply  # write to the editable version

Apple only accepts these on an editable (PREPARE_FOR_SUBMISSION) version
and app info, so --apply runs as part of the next App Store submission.
Limits: name 30, subtitle 30, keywords 100 (comma-separated, no spaces
needed), promotional text 170, description 4000.
"""
import sys

LOCALES = {
    "es-MX": {
        "subtitle": "Rentas estabilizadas en NYC",
        "keywords": "renta estabilizada,apartamentos,nueva york,lotería de vivienda,section 8,vivienda asequible,brooklyn",
        "promo": "Los edificios de renta estabilizada de Nueva York en un mapa, las loterías de vivienda abiertas y herramientas para inquilinos: reparaciones, aumentos y tus derechos.",
        "description": """Find A Crib muestra en un mapa los edificios donde la renta está limitada por ley en Nueva York, Los Ángeles, San Francisco y Washington DC, usando el registro público de cada ciudad.

EN NUEVA YORK
- Los 47,000 edificios de renta estabilizada del registro de NYS HCR
- Las loterías de vivienda abiertas, con límites de ingresos, fechas límite y un enlace directo para aplicar
- Edificios que aceptan Section 8 y CityFHEPS
- El historial de cada edificio: violaciones abiertas de HPD, chinches y ratas, y quién lo administra

¿YA TIENES DÓNDE VIVIR?
- Pide una reparación: lo que exige la ley de NYC y una carta lista para enviar a tu casero
- ¿Es legal mi aumento de renta? Revisa las pautas del Rent Guidelines Board y la ley Good Cause
- Conoce tus derechos como inquilino, en palabras sencillas

FIND A CRIB PLUS
Alertas en tiempo real cuando abre una lotería, búsqueda en tus propias palabras, revisión de contrato, el Renewal coach y sin anuncios. El primer mes va por nuestra cuenta; después, $4.99 al mes, cobrado a tu cuenta de Apple y renovado automáticamente salvo que lo canceles al menos 24 horas antes del fin del periodo.
Términos de uso (EULA): https://www.apple.com/legal/internet-services/itunes/dev/stdeula/
Privacidad: https://findacrib.com/privacy/

Find A Crib es una herramienta informativa e independiente. No es un corredor, no publica apartamentos y no cobra comisiones. La información general sobre leyes no es asesoría legal.""",
    },
    "zh-Hans": {
        "subtitle": "纽约租金稳定公寓地图",
        "keywords": "租金稳定,纽约租房,公寓,住房抽签,廉租房,第八类住房,布鲁克林,法拉盛,皇后区",
        "promo": "纽约所有租金稳定楼宇一图尽览，开放中的住房抽签，以及租户工具：报修、涨租是否合法、了解你的权利。",
        "description": """Find A Crib 根据各城市的公开登记，在地图上标出纽约、洛杉矶、旧金山和华盛顿特区法律限制租金的楼宇。

在纽约
- 纽约州 HCR 登记的全部 47,000 栋租金稳定楼宇
- 正在开放的住房抽签：收入限制、截止日期和直接申请链接
- 接受 Section 8 和 CityFHEPS 住房券的楼宇
- 每栋楼的记录：HPD 未结违规、臭虫和老鼠记录，以及管理方

已经有住处了？
- 报修：纽约法律的要求，以及一封可直接寄给房东的信
- 涨租合法吗？对照租金指导委员会 (RGB) 标准和 Good Cause 法
- 用浅显的语言了解你作为租户的权利

FIND A CRIB PLUS
住房抽签实时提醒、自然语言搜索、租约审核、续租助手 (Renewal coach)，并且无广告。新订阅首月免费，之后每月 $4.99，从你的 Apple 账户扣款，除非在当期结束前至少 24 小时取消，否则自动续订。
使用条款 (EULA)：https://www.apple.com/legal/internet-services/itunes/dev/stdeula/
隐私政策：https://findacrib.com/privacy/

Find A Crib 是独立的信息工具，不是中介，不发布房源，不收取任何费用。法律信息仅供参考，不构成法律建议。""",
    },
    "zh-Hant": {
        "subtitle": "紐約租金穩定公寓地圖",
        "keywords": "租金穩定,紐約租屋,公寓,住房抽籤,平價住房,第八類住房,布魯克林,法拉盛,皇后區",
        "promo": "紐約所有租金穩定大樓一圖盡覽，開放中的住房抽籤，以及租戶工具：報修、漲租是否合法、了解你的權利。",
        "description": """Find A Crib 根據各城市的公開登記，在地圖上標出紐約、洛杉磯、舊金山和華盛頓特區法律限制租金的大樓。

在紐約
- 紐約州 HCR 登記的全部 47,000 棟租金穩定大樓
- 正在開放的住房抽籤：收入限制、截止日期和直接申請連結
- 接受 Section 8 和 CityFHEPS 住房券的大樓
- 每棟樓的紀錄：HPD 未結違規、臭蟲和老鼠紀錄，以及管理方

已經有住處了？
- 報修：紐約法律的要求，以及一封可直接寄給房東的信
- 漲租合法嗎？對照租金指導委員會 (RGB) 標準和 Good Cause 法
- 用淺白的語言了解你作為租戶的權利

FIND A CRIB PLUS
住房抽籤即時提醒、自然語言搜尋、租約審核、續租助手 (Renewal coach)，而且沒有廣告。新訂閱首月免費，之後每月 $4.99，從你的 Apple 帳號扣款，除非在當期結束前至少 24 小時取消，否則自動續訂。
使用條款 (EULA)：https://www.apple.com/legal/internet-services/itunes/dev/stdeula/
隱私權政策：https://findacrib.com/privacy/

Find A Crib 是獨立的資訊工具，不是仲介，不刊登房源，不收取任何費用。法律資訊僅供參考，不構成法律建議。""",
    },
    "ru": {
        "subtitle": "Регулируемая аренда в NYC",
        "keywords": "аренда,нью-йорк,квартира,rent stabilized,лотерея жилья,section 8,бруклин,брайтон,доступное жильё",
        "promo": "Все дома с регулируемой арендой Нью-Йорка на одной карте, открытые жилищные лотереи и инструменты для жильцов: ремонт, законность повышения аренды, ваши права.",
        "description": """Find A Crib показывает на карте дома, где арендная плата ограничена законом, в Нью-Йорке, Лос-Анджелесе, Сан-Франциско и Вашингтоне — по открытым реестрам каждого города.

В НЬЮ-ЙОРКЕ
- Все 47 000 домов с регулируемой арендой (rent stabilized) из реестра NYS HCR
- Открытые жилищные лотереи: лимиты дохода, сроки и прямая ссылка для заявки
- Дома, принимающие ваучеры Section 8 и CityFHEPS
- История каждого дома: открытые нарушения HPD, клопы и крысы, кто управляет домом

УЖЕ ЕСТЬ ЖИЛЬЁ?
- Ремонт: что требует закон Нью-Йорка, и готовое письмо арендодателю
- Законно ли повышение аренды? Проверка по нормам Rent Guidelines Board и закону Good Cause
- Ваши права как арендатора — простыми словами

FIND A CRIB PLUS
Мгновенные уведомления о лотереях, поиск обычными словами, проверка договора аренды, Renewal coach и никакой рекламы. Первый месяц — за наш счёт, затем $4.99 в месяц со списанием с вашей учётной записи Apple и автоматическим продлением, если не отменить подписку минимум за 24 часа до конца периода.
Условия использования (EULA): https://www.apple.com/legal/internet-services/itunes/dev/stdeula/
Конфиденциальность: https://findacrib.com/privacy/

Find A Crib — независимый информационный сервис. Это не брокер: мы не публикуем объявления и не берём комиссий. Общая информация о законах не является юридической консультацией.""",
    },
    "ko": {
        "subtitle": "뉴욕 렌트 안정화 아파트 지도",
        "keywords": "렌트 안정화,뉴욕 아파트,렌트,하우징 로터리,저렴한 주택,섹션8,플러싱,퀸즈,브루클린",
        "promo": "뉴욕의 모든 렌트 안정화 건물을 한 지도에, 진행 중인 하우징 로터리, 그리고 세입자 도구: 수리 요청, 렌트 인상 합법 여부, 세입자 권리.",
        "description": """Find A Crib은 각 도시의 공공 등록부를 바탕으로 뉴욕, 로스앤젤레스, 샌프란시스코, 워싱턴 DC에서 법으로 렌트가 제한된 건물을 지도에 보여줍니다.

뉴욕에서는
- NYS HCR 등록부의 렌트 안정화 건물 47,000곳 전체
- 진행 중인 하우징 로터리: 소득 기준, 마감일, 바로 신청할 수 있는 링크
- Section 8 및 CityFHEPS 바우처를 받는 건물
- 건물별 기록: HPD 미해결 위반, 빈대·쥐 기록, 관리 회사

이미 집이 있다면?
- 수리 요청: 뉴욕 법이 요구하는 것과 집주인에게 보낼 편지
- 렌트 인상이 합법인가요? Rent Guidelines Board 기준과 Good Cause 법으로 확인
- 세입자로서의 권리를 쉬운 말로

FIND A CRIB PLUS
로터리 실시간 알림, 일상 언어 검색, 임대 계약서 검토, Renewal coach, 광고 없음. 첫 달은 무료이며, 이후 월 $4.99가 Apple 계정으로 청구되고 기간 종료 최소 24시간 전에 취소하지 않으면 자동 갱신됩니다.
이용 약관 (EULA): https://www.apple.com/legal/internet-services/itunes/dev/stdeula/
개인정보 처리방침: https://findacrib.com/privacy/

Find A Crib은 독립적인 정보 도구입니다. 중개인이 아니며, 매물을 올리지 않고, 수수료를 받지 않습니다. 법률 정보는 일반 정보이며 법률 자문이 아닙니다.""",
    },
}

LIMITS = {"subtitle": 30, "keywords": 100, "promo": 170, "description": 4000}


def check():
    bad = []
    for loc, f in LOCALES.items():
        for k, n in LIMITS.items():
            if len(f[k]) > n:
                bad.append(f"{loc} {k}: {len(f[k])} > {n}")
    return bad


def apply():
    """Create or update each locale on the editable version and app info."""
    import asc_metadata as M
    M.refuse_if_frozen()
    cfg = M.load_config(); asc = M.ASC(cfg)
    ids = M.resolve(asc, cfg["ASC_APP_ID"])
    vlocs = {r["attributes"]["locale"]: r["id"] for r in asc.get(f"/appStoreVersions/{ids['version']}/appStoreVersionLocalizations")["data"]}
    ilocs = {r["attributes"]["locale"]: r["id"] for r in asc.get(f"/appInfos/{ids['info']}/appInfoLocalizations")["data"]}
    for loc, f in LOCALES.items():
        va = {"description": f["description"], "keywords": f["keywords"], "promotionalText": f["promo"],
              "marketingUrl": M.SITE, "supportUrl": M.SUPPORT}
        if ids["version_string"] != "1.0":
            va["whatsNew"] = f.get("whats_new") or WHATS_NEW[loc]
        if loc in vlocs:
            asc.patch(f"/appStoreVersionLocalizations/{vlocs[loc]}", {"data": {"type": "appStoreVersionLocalizations", "id": vlocs[loc], "attributes": va}})
        else:
            asc.post("/appStoreVersionLocalizations", {"data": {"type": "appStoreVersionLocalizations", "attributes": dict(va, locale=loc),
                     "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": ids["version"]}}}}})
        # Adding a version language makes Apple create the app-info row for
        # it too, so look again before deciding to create one.
        ilocs = {r["attributes"]["locale"]: r["id"] for r in asc.get(f"/appInfos/{ids['info']}/appInfoLocalizations")["data"]}
        ia = {"name": "Find A Crib", "subtitle": f["subtitle"], "privacyPolicyUrl": M.PRIVACY}
        if loc in ilocs:
            asc.patch(f"/appInfoLocalizations/{ilocs[loc]}", {"data": {"type": "appInfoLocalizations", "id": ilocs[loc], "attributes": ia}})
        else:
            asc.post("/appInfoLocalizations", {"data": {"type": "appInfoLocalizations", "attributes": dict(ia, locale=loc),
                     "relationships": {"appInfo": {"data": {"type": "appInfos", "id": ids["info"]}}}}})
        print(f"    {loc}: listing + subtitle")


WHATS_NEW = {
    "es-MX": "• Nuevo: Your Crib. Escribe tu dirección y mira cada llamada al 311 sobre tu edificio en el último año (cucarachas, ratones, ratas, calefacción, goteras) y los delitos reportados a media milla. Con Plus, recibe alertas.\n• Cada edificio de Nueva York ahora muestra bufetes de abogados de vivienda de su distrito, justo debajo de los cafés cercanos.\n• Iniciar sesión es más fácil: el botón queda sobre el teclado y al tocar fuera se cierra el teclado.\n• Las alertas de loterías, a un toque en Buscar.\n• Muchas mejoras.",
    "zh-Hans": "• 新功能 Your Crib：输入地址，查看过去一年你所在楼的所有 311 投诉（蟑螂、老鼠、暖气、漏水）以及半英里内的报案犯罪。Plus 会员可接收提醒。\n• 纽约每栋楼现在都会列出所在区的住房律师事务所，就在附近咖啡馆下方。\n• 登录更方便：登录按钮停在键盘上方，点按空白处即可收起键盘。\n• 在“搜索”下一点即可开启住房抽签提醒。\n• 多项改进。",
    "zh-Hant": "• 新功能 Your Crib：輸入地址，查看過去一年你所在大樓的所有 311 投訴（蟑螂、老鼠、暖氣、漏水）以及半英里內的報案犯罪。Plus 會員可接收提醒。\n• 紐約每棟大樓現在都會列出所在區的住房律師事務所，就在附近咖啡館下方。\n• 登入更方便：登入按鈕停在鍵盤上方，點按空白處即可收起鍵盤。\n• 在「搜尋」下一點即可開啟住房抽籤提醒。\n• 多項改進。",
    "ru": "• Новое: Your Crib. Введите адрес и посмотрите все звонки в 311 о вашем доме за год (тараканы, мыши, крысы, отопление, протечки) и преступления в радиусе полумили. С Plus — уведомления.\n• Для каждого дома в Нью-Йорке теперь указаны юридические фирмы по жилищным вопросам в его районе — сразу под ближайшими кафе.\n• Вход стал проще: кнопка остаётся над клавиатурой, а касание вне поля скрывает клавиатуру.\n• Уведомления о лотереях — в одно касание в Поиске.\n• Множество улучшений.",
    "ko": "• 새 기능 Your Crib: 주소를 입력하면 지난 1년간 건물에 접수된 모든 311 신고(바퀴벌레, 쥐, 난방, 누수)와 반경 0.5마일 내 범죄 신고를 볼 수 있습니다. Plus는 알림 제공.\n• 뉴욕의 각 건물에 해당 자치구의 주택 전문 법률사무소가 주변 카페 바로 아래에 표시됩니다.\n• 더 쉬워진 로그인: 로그인 버튼이 키보드 위에 머물고, 바깥을 탭하면 키보드가 닫힙니다.\n• 검색 아래에서 바로 로터리 알림을 켤 수 있습니다.\n• 그 밖의 다양한 개선.",
}


if __name__ == "__main__":
    problems = check()
    for loc, f in LOCALES.items():
        print(f"{loc:8} subtitle {len(f['subtitle']):>3}/30  keywords {len(f['keywords']):>3}/100  promo {len(f['promo']):>3}/170  description {len(f['description']):>4}/4000")
    if problems:
        sys.exit("over the limit:\n  " + "\n  ".join(problems))
    if "--apply" in sys.argv:
        apply()
