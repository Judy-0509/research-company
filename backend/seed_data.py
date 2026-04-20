"""RSS feed URLs and keywords for smartphone market research."""

RSS_FEEDS_KO: dict[str, str] = {
    # 직접 RSS 작동
    "한국경제":       "https://www.hankyung.com/feed/it",
    "매일경제IT":     "https://www.mk.co.kr/rss/30200030/",
    "더일렉":         "https://www.thelec.kr/rss/allArticle.xml",
    # Direct outbound feed is the whole Chosun network (sports/politics/etc.) — too noisy.
    # Route through Google News with smartphone/semiconductor scope instead.
    "조선비즈":       "https://news.google.com/rss/search?q=조선비즈+스마트폰+반도체&hl=ko&gl=KR&ceid=KR:ko",
    "연합뉴스":       "https://www.yna.co.kr/rss/news.xml",
    # Google News 경유 (직접 RSS 불가)
    "전자신문":       "https://news.google.com/rss/search?q=전자신문+스마트폰+반도체&hl=ko&gl=KR&ceid=KR:ko",
    "디지털데일리":   "https://news.google.com/rss/search?q=디지털데일리+스마트폰&hl=ko&gl=KR&ceid=KR:ko",
    "ZDNet Korea":    "https://news.google.com/rss/search?q=zdnet+korea+스마트폰+반도체&hl=ko&gl=KR&ceid=KR:ko",
    "아이뉴스24":     "https://news.google.com/rss/search?q=아이뉴스24+스마트폰&hl=ko&gl=KR&ceid=KR:ko",
}

RSS_FEEDS_EN: dict[str, str] = {
    # Tier 2 — Tech media
    "TechCrunch":        "https://techcrunch.com/feed/",
    "The Verge":         "https://www.theverge.com/rss/index.xml",
    "Engadget":          "https://www.engadget.com/rss.xml",
    "Android Authority": "https://www.androidauthority.com/feed/",
    "GSMArena":          "https://www.gsmarena.com/rss-news-reviews.php3",
    "9to5Google":        "https://9to5google.com/feed/",
    "9to5Mac":           "https://9to5mac.com/feed/",
    "Notebookcheck":     "https://news.google.com/rss/search?q=notebookcheck+smartphone&hl=en-US&gl=US&ceid=US:en",
    "SCMP Tech":         "https://www.scmp.com/rss/5/feed",
    "Digitimes":         "https://www.digitimes.com/rss/daily.xml",
    "PhoneArena":        "https://www.phonearena.com/feed/latest",
    # Tier 3 — Research firms via Google News (direct feeds blocked/404)
    "Counterpoint":      "https://news.google.com/rss/search?q=counterpoint+research+smartphone&hl=en-US&gl=US&ceid=US:en",
    "Canalys":           "https://news.google.com/rss/search?q=canalys+smartphone+shipment&hl=en-US&gl=US&ceid=US:en",
    "TrendForce":        "https://news.google.com/rss/search?q=trendforce+smartphone+shipment&hl=en-US&gl=US&ceid=US:en",
    "IDC":               "https://news.google.com/rss/search?q=IDC+smartphone+shipments+market&hl=en-US&gl=US&ceid=US:en",
    "Reuters":           "https://news.google.com/rss/search?q=reuters+smartphone+apple+samsung&hl=en-US&gl=US&ceid=US:en",
    "Bloomberg":         "https://news.google.com/rss/search?q=bloomberg+smartphone+apple+samsung+market&hl=en-US&gl=US&ceid=US:en",
}

KEYWORDS_KO: list[str] = [
    k.strip().lower() for k in (
        "스마트폰,삼성,갤럭시,아이폰,애플,샤오미,화웨이,아너,오포,비보,트랜시온,"
        "모토로라,구글 픽셀,폴더블,OLED,디스플레이,패널,카메라모듈,"
        "반도체,칩,메모리,낸드,D램,HBM,SK하이닉스,TSMC,퀄컴,미디어텍,"
        "LG이노텍,LG디스플레이,삼성디스플레이,공급망,부품,"
        "출하,시장점유율,판매량"
    ).split(",") if k.strip()
]

KEYWORDS_CASE_SENSITIVE: list[str] = ["AP"]

KEYWORDS_EN: list[str] = [
    k.strip().lower() for k in (
        "smartphone,Samsung,Galaxy,iPhone,Apple,Xiaomi,Huawei,Honor,OPPO,vivo,"
        "Transsion,Motorola,Google Pixel,OnePlus,Realme,foldable smartphone,shipment,market share,"
        "supply chain,semiconductor,chip,application processor,memory,NAND,DRAM,LPDDR,HBM,TSMC,Qualcomm,MediaTek,"
        "OLED,display,panel,IDC,Counterpoint,Canalys,TrendForce,Omdia,GfK,"
        "ASP,price,gross margin,earnings,revenue"
    ).split(",") if k.strip()
]
