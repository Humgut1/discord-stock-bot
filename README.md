# 📈 증권봇

토스증권 Open API 기반 디스코드 모의투자 봇

실제 시세 데이터를 기반으로 디스코드 서버 안에서 친구들과 모의투자 대회를 즐길 수 있어요.

---

## ✨ 기능

### 시세 조회
- 국내 / 미국 주식 현재가 조회
- 30일 캔들차트 이미지 전송
- 종목명으로 검색 (삼성전자, 엔비디아, 애플 등 별명 지원)

### 모의투자 대회
- 대회 생성 시 채널 자동 생성 (대회정보 / 매수매도 / 체결알림 / 랭킹)
- 자본금 / 기간 / 시장(코스피·코스닥·나스닥 등) 설정
- 지정가 주문 — 실제 시세 도달 시 자동 체결 (3분 폴링)
- 실시간 수익률 랭킹
- 매일 오전 9시 일일 랭킹 자동 공지
- 대회 종료 시 최종 결과 자동 공지

---

## 🚀 실행 방법

### 1. 클론
```bash
git clone https://github.com/YOUR_USERNAME/증권봇.git
cd 증권봇
```

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```

### 3. 환경변수 설정
```bash
cp .env.example .env
```
`.env` 파일을 열어 아래 값을 입력하세요:

| 키 | 설명 | 발급처 |
|----|------|--------|
| `DISCORD_TOKEN` | 디스코드 봇 토큰 | [Discord Developer Portal](https://discord.com/developers/applications) |
| `TOSS_CLIENT_ID` | 토스증권 Client ID | [토스증권 개발자](https://developers.tossinvest.com) |
| `TOSS_CLIENT_SECRET` | 토스증권 Client Secret | 위와 동일 |
| `FILL_CHANNEL_ID` | 일반 체결 알림 채널 ID | 디스코드 채널 우클릭 → ID 복사 |

### 4. 봇 실행
```bash
python main.py
```

---

## 🤖 디스코드 봇 초대 설정

[Discord Developer Portal](https://discord.com/developers/applications) → OAuth2 → URL Generator

**SCOPES:** `bot` + `applications.commands`

**BOT PERMISSIONS:**
- Send Messages
- Embed Links
- Attach Files
- Read Message History
- **Manage Channels** ← 대회 채널 자동 생성에 필요

---

## 📋 명령어

### 시세
| 명령어 | 설명 |
|--------|------|
| `/종목 [이름]` | 현재가 + 30일 차트 조회 |

### 모의투자 대회
| 명령어 | 권한 | 설명 |
|--------|------|------|
| `/대회생성` | 관리자 | 대회 생성 + 채널 자동 생성 |
| `/대회목록` | 누구나 | 진행 중 대회 목록 |
| `/대회참가 [ID]` | 누구나 | 대회 참가 |
| `/대회정보 [ID]` | 누구나 | 대회 상세 확인 |
| `/대회매수 [ID] [종목] [수량] [가격]` | 참가자 | 지정가 매수 주문 |
| `/대회매도 [ID] [종목] [수량] [가격]` | 참가자 | 지정가 매도 주문 |
| `/내잔고 [ID]` | 참가자 | 내 포트폴리오 + 평가손익 |
| `/랭킹 [ID]` | 누구나 | 실시간 수익률 순위 |
| `/대회주문대기 [ID]` | 참가자 | 미체결 주문 목록 |
| `/대회주문취소 [번호]` | 참가자 | 주문 취소 |

### 사용 예시
```
/대회매수 1 삼성전자 10 78000
/대회매수 1 NVDA 5 134
/내잔고 1
/랭킹 1
```

---

## 🗂️ 프로젝트 구조

```
증권봇/
├── main.py                  # 봇 진입점
├── requirements.txt
├── .env.example             # 환경변수 양식
├── .gitignore
├── data/
│   └── game.db              # SQLite DB (자동 생성)
└── bot/
    ├── toss_api.py          # 토스증권 API 호출 + 종목명 매핑
    ├── chart.py             # 캔들차트 이미지 생성
    ├── database.py          # 일반 모의투자 DB
    ├── commands.py          # 일반 슬래시 커맨드
    ├── scheduler.py         # 일반 주문 체결 폴링
    ├── contest_db.py        # 대회 DB
    ├── contest_commands.py  # 대회 슬래시 커맨드
    └── contest_scheduler.py # 대회 체결 폴링 + 랭킹 자동 공지
```

---

## ⚙️ 기술 스택

- **Python 3.11+**
- **discord.py 2.3+** — 디스코드 봇 프레임워크
- **httpx** — 토스증권 API 호출
- **SQLite** — 유저 데이터, 주문, 보유 종목 저장
- **matplotlib** — 캔들차트 이미지 생성

---

## ⚠️ 주의사항

- 이 봇은 **모의투자 전용**입니다. 실제 주문을 실행하지 않습니다.
- 토스증권 Open API는 **REST 폴링** 방식으로 3분 간격으로 시세를 확인합니다.
- 투자에는 항상 리스크가 따릅니다.
