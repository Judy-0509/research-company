"""Brand label assignment — shared by rss_collector and backfill script."""

# Substrings that indicate sports / entertainment / unrelated contexts.
# If any match, we skip brand labeling entirely (bare brand name is not enough).
NON_TECH_CONTEXTS: tuple[str, ...] = (
    # Samsung sports clubs (수원 삼성 FC, 삼성 라이온즈 KBO)
    "수원 삼성", "수원삼성",
    "삼성 라이온즈", "삼성라이온즈",
    # Generic sports markers
    "프로야구", "kbo", "k리그", "프리미어리그", "월드컵",
    "축구단", "야구단", "레전드 매치", "올스타",
    "하프마라톤", "마라톤",
    # Robotics / non-phone contexts that mention brands in passing
    "휴머노이드", "humanoid",
)


def _is_non_tech(text_lower: str) -> bool:
    return any(p in text_lower for p in NON_TECH_CONTEXTS)


BRAND_KEYWORDS: dict[str, list[str]] = {
    "apple": [
        "apple", "iphone", "ios", "macos", "tim cook", "app store", "cupertino",
        "애플", "아이폰",
    ],
    "samsung": [
        "samsung", "galaxy", "exynos", "one ui", "samsung display",
        "삼성", "갤럭시",
    ],
    "huawei": [
        "huawei", "harmonyos", "kirin", "hisilicon", "hms",
        "화웨이", "하모니os",
    ],
    "honor": [
        # Avoid bare "honor" — too many English false positives
        "honor magic", "honor x", "honor 90", "honor 100", "honor 200",
        "honor 400", "honor smartphone", "honor phone", "honor fold",
        "아너",
    ],
    "xiaomi": [
        "xiaomi", "redmi", "poco", "hyperos", "miui",
        "샤오미", "레드미",
    ],
    "oppo": [
        "oppo", "realme", "oneplus", "coloros", "find x",
        "오포",
    ],
    "vivo": [
        "vivo", "iqoo", "funtouch", "originos",
        "비보",
    ],
    "transsion": [
        "transsion", "tecno", "infinix", "itel",
        "트랜시온",
    ],
}

CN_OEM_BRANDS = frozenset({"huawei", "honor", "xiaomi", "oppo", "vivo", "transsion"})


def assign_brand_labels(title: str, description: str) -> str:
    """Returns sentinel-comma format: ',samsung,cn_oem,' or '' if no match."""
    text = f" {title} {description} ".lower()
    if _is_non_tech(text):
        return ""
    matched = {
        brand for brand, kws in BRAND_KEYWORDS.items()
        if any(kw in text for kw in kws)
    }
    if matched & CN_OEM_BRANDS:
        matched.add("cn_oem")
    if not matched:
        return ""
    return "," + ",".join(sorted(matched)) + ","
