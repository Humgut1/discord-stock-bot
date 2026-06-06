import time
import httpx
import os

_token: str | None = None
_token_expires: float = 0

# 환율 캐시 (1분 유효)
_exchange_rate: float | None = None
_exchange_rate_expires: float = 0

BASE = "https://openapi.tossinvest.com"

# 종목명 → 종목코드 매핑 (검색 API 없음)
NAME_TO_SYMBOL: dict[str, str] = {
    # 국내
    "삼성전자": "005930", "삼전": "005930", "삼성": "005930",
    "SK하이닉스": "000660", "에스케이하이닉스": "000660", "하이닉스": "000660", "sk하이닉스": "000660",
    "NAVER": "035420", "네이버": "035420",
    "카카오": "035720",
    "현대차": "005380", "현대자동차": "005380", "현대": "005380",
    "기아": "000270", "기아차": "000270",
    "LG에너지솔루션": "373220", "엘지에너지": "373220", "lg에너지": "373220",
    "셀트리온": "068270", "셀트": "068270",
    "POSCO홀딩스": "005490", "포스코": "005490",
    "삼성바이오로직스": "207940",
    "KB금융": "105560",
    "신한지주": "055550",
    "하나금융지주": "086790",
    "LG화학": "051910",
    "삼성SDI": "006400",
    "카카오뱅크": "323410",
    "크래프톤": "259960",
    "두산에너빌리티": "034020",
    "KODEX200": "069500",
    # 미국
    "NVDA": "NVDA", "엔비디아": "NVDA", "nvidia": "NVDA",
    "AAPL": "AAPL", "애플": "AAPL", "apple": "AAPL",
    "TSLA": "TSLA", "테슬라": "TSLA", "tesla": "TSLA",
    "MSFT": "MSFT", "마이크로소프트": "MSFT", "ms": "MSFT",
    "GOOGL": "GOOGL", "구글": "GOOGL", "알파벳": "GOOGL",
    "AMZN": "AMZN", "아마존": "AMZN",
    "META": "META", "메타": "META", "페이스북": "META",
    "NFLX": "NFLX", "넷플릭스": "NFLX",
    "AMD": "AMD",
    "INTC": "INTC", "인텔": "INTC",
    "PLTR": "PLTR", "팔란티어": "PLTR",
}


def _get_token() -> str:
    global _token, _token_expires
    if _token and time.time() < _token_expires - 60:
        return _token

    resp = httpx.post(
        f"{BASE}/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["TOSS_CLIENT_ID"],
            "client_secret": os.environ["TOSS_CLIENT_SECRET"],
        },
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expires = time.time() + data["expires_in"]
    return _token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}


def resolve_symbol(name: str) -> str:
    """종목명 → 종목코드. 못 찾으면 입력값 그대로 반환."""
    return NAME_TO_SYMBOL.get(name) or NAME_TO_SYMBOL.get(name.upper()) or name.upper()


def get_price(symbol: str) -> dict:
    """현재가 조회. 응답: {symbol, lastPrice, currency, timestamp}"""
    resp = httpx.get(
        f"{BASE}/api/v1/prices",
        params={"symbols": symbol},
        headers=_headers(),
    )
    resp.raise_for_status()
    items = resp.json().get("result", [])
    return items[0] if items else {}


def get_stock_info(symbol: str) -> dict:
    """종목 기본정보 (이름, 시장 등). 응답: {symbol, name, market, currency, ...}"""
    resp = httpx.get(
        f"{BASE}/api/v1/stocks",
        params={"symbols": symbol},
        headers=_headers(),
    )
    resp.raise_for_status()
    items = resp.json().get("result", [])
    return items[0] if items else {}


def get_exchange_rate() -> float:
    """USD → KRW 환율 조회 (1분 캐시)"""
    global _exchange_rate, _exchange_rate_expires
    if _exchange_rate and time.time() < _exchange_rate_expires:
        return _exchange_rate

    resp = httpx.get(
        f"{BASE}/api/v1/exchange-rate",
        params={"baseCurrency": "USD", "quoteCurrency": "KRW"},
        headers=_headers(),
    )
    resp.raise_for_status()
    rate = float(resp.json()["result"]["rate"])
    _exchange_rate = rate
    _exchange_rate_expires = time.time() + 60
    return rate


def usd_to_krw(usd: float) -> float:
    """달러 → 원화 환산"""
    return usd * get_exchange_rate()


def get_candles(symbol: str, interval: str = "1d", count: int = 30) -> list:
    """캔들 데이터. interval: 1m / 1d"""
    resp = httpx.get(
        f"{BASE}/api/v1/candles",
        params={"symbol": symbol, "interval": interval, "count": count},
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json().get("result", {}).get("candles", [])
