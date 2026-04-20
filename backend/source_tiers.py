"""Source tier classification (1-3, higher = more authoritative)."""
from urllib.parse import urlparse

SOURCE_TIERS: dict[str, int] = {
    # Market research firms — Tier 3
    "counterpointresearch.com": 3,
    "canalys.com": 3,
    "idc.com": 3,
    "trendforce.com": 3,
    "press.trendforce.com": 3,
    "omdia.com": 3,
    "gfk.com": 3,
    "strategy-analytics.com": 3,
    # Wire services — Tier 3
    "reuters.com": 3,
    "bloomberg.com": 3,
    "apnews.com": 3,
    "ft.com": 3,
    "wsj.com": 3,
    # Korean financial/IT press — Tier 2
    "etnews.com": 2,
    "ddaily.co.kr": 2,
    "zdnet.co.kr": 2,
    "hankyung.com": 2,
    "mk.co.kr": 2,
    "biz.chosun.com": 2,
    "inews24.com": 2,
    "yna.co.kr": 2,
    "thelec.kr": 2,
    "thelec.net": 2,
    "newspim.com": 2,
    "g-enews.com": 2,
    "edaily.co.kr": 2,
    "mt.co.kr": 2,
    # Major tech media — Tier 2
    "techcrunch.com": 2,
    "theverge.com": 2,
    "engadget.com": 2,
    "wired.com": 2,
    "arstechnica.com": 2,
    "9to5mac.com": 2,
    "9to5google.com": 2,
    "androidauthority.com": 2,
    "gsmarena.com": 2,
    "phonearena.com": 2,
    "notebookcheck.net": 2,
    "scmp.com": 2,
    "nikkei.com": 2,
    "asia.nikkei.com": 2,
    "digitimes.com": 2,
    "sammobile.com": 2,
    "xda-developers.com": 2,
    "eetimes.com": 2,
}

SOURCE_NAME_TIERS: dict[str, int] = {
    "counterpoint": 3,
    "canalys": 3,
    "idc": 3,
    "trendforce": 3,
    "omdia": 3,
    "gfk": 3,
    "strategy analytics": 3,
    "reuters": 3,
    "bloomberg": 3,
    "financial times": 3,
    "wall street journal": 3,
    "nikkei": 3,
    "etnews": 2,
    "전자신문": 2,
    "zdnet": 2,
    "hankyung": 2,
    "한국경제": 2,
    "chosun": 2,
    "조선비즈": 2,
    "inews24": 2,
    "아이뉴스24": 2,
    "yonhap": 2,
    "연합뉴스": 2,
    "digitaldaily": 2,
    "디지털데일리": 2,
    "thelec": 2,
    "더일렉": 2,
    "maeil": 2,
    "매일경제": 2,
    "techcrunch": 2,
    "the verge": 2,
    "engadget": 2,
    "9to5mac": 2,
    "9to5google": 2,
    "gsmarena": 2,
    "digitimes": 2,
}


def get_source_tier(url: str, source_name: str = "") -> int:
    try:
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if "google.com" not in domain:
            if domain in SOURCE_TIERS:
                return SOURCE_TIERS[domain]
            for key, tier in SOURCE_TIERS.items():
                if domain.endswith("." + key):
                    return tier
    except Exception:
        pass
    if source_name:
        name_lower = source_name.lower()
        for key, tier in SOURCE_NAME_TIERS.items():
            if key in name_lower:
                return tier
    return 1
