# tradroom

**한국 증시 퀀트 트레이딩 — 추세추종 멀티팩터 의사결정 지원 엔진**

[`korea_quant_trading_blueprint.md`](./korea_quant_trading_blueprint.md) 설계서를 코드로 구현한 프로젝트입니다.
"지금 살만한 종목"을 추천하고, 내 포트폴리오의 **보유/축소/매도/교체**를 매일 판단합니다.

> ⚠️ 자동매매가 아니라 **의사결정 지원(decision-support)** 도구입니다. 최종 주문은 사람이 합니다.
> 목표는 *높은 승률*이 아니라 **양(+)의 기대값 + 통제된 최대낙폭(MDD)**.

---

## 핵심 설계 — Top-down 깔때기

```
1. 매크로 레짐    위험자산 들고 있어도 되는 국면인가? (Risk-On/Neutral/Off)
2. 섹터 로테이션  돈이 어디로? RS 상위 섹터만 사냥터로
3. 종목 선정      하드 게이트 → 멀티팩터 종합점수(추세35·RS20·퀄리티20·수급15·밸류10)
4. 진입 타이밍    지금 자리가 사도 되나? 돌파/눌림 + 거래량
5. 사이징·리스크  변동성 기반 + 고정분율 리스크 + 종목/섹터 한도
6. 청산 규칙      손절/트레일링/추세훼손/RS악화/수급이탈
7. 포트 모니터링  매일 재평가 → 보유/축소/매도/교체(마찰 임계치)
```

## 아키텍처 (레이어)

| 레이어 | 모듈 | 역할 |
|---|---|---|
| 데이터 | `tradroom/data/` | 수집·저장·표준 컨테이너(`MarketData`). 라이브/샘플/디스크 |
| 팩터 | `tradroom/features/` | 기술·퀄리티·수급·밸류 → 횡단면 백분위 정규화 |
| 시그널 | `tradroom/signals/` | 레짐(L1)·섹터(L2)·스코어링(L3)·타이밍(L4) |
| 포트폴리오 | `tradroom/portfolio/` | 사이징(L5)·청산(L6)·모니터링/교체(L7)·추천 |
| 백테스트 | `tradroom/backtest/` | 비용·유동성·look-ahead 반영, 지표, 워크포워드 |
| API | `tradroom/api/` | FastAPI 읽기 전용 |
| 프론트 | `frontend/` | React 대시보드 |

> 설계 규칙: 화면은 **읽기 전용 뷰**. 모든 계산은 signal/backtest/portfolio 에서 끝나고
> 백테스트와 실전이 *같은 로직*을 쓴다(코드 일원화).

---

## 빠른 시작

### 1) 백엔드 (API 키 불필요 — 합성 샘플 데이터로 즉시 동작)

```bash
pip install -r requirements.txt        # 또는: pip install -e ".[api,dev]"

# 백테스트 (Phase 1, ★최우선★)
PYTHONPATH=. python scripts/run_backtest.py --walkforward

# 일일 추천 + 포트폴리오 진단 (Phase 2)
PYTHONPATH=. python scripts/run_recommend.py --holdings my_portfolio.json --equity 50000000

# API 서버 (Phase 3 백엔드)
uvicorn tradroom.api.main:app --reload
```

`my_portfolio.json` 예시:
```json
[{"ticker": "000105", "shares": 100, "avg_price": 50000}]
```

### 2) 프론트엔드 대시보드

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (API 8000 으로 프록시)
```

레짐 신호등 · 주도 섹터 · 매수 후보(BUY/WATCH) · 내 포트 진단 · 백테스트 차트.

### 3) 실제 무료 데이터 연동 (선택)

```bash
cp .env.example .env      # DART/ECOS/FRED 키 입력 (없어도 일부만 채워짐)
# .env 에서 TRADROOM_USE_LIVE_DATA=true
pip install -e ".[live]"
PYTHONPATH=. python scripts/run_ingest.py --source live --start 2021-01-01
```

데이터 소스(블루프린트 3장): **KIS / KRX(pykrx) / DART / ECOS / FRED**.
키·네트워크가 없거나 일부 실패하면 자동으로 샘플 데이터로 폴백합니다.

---

## 샘플 데이터 백테스트 결과 (예시)

추세추종의 전형적 시그니처가 재현됩니다:

| 지표 | 값(예시) | 해석 |
|---|---|---|
| 승률 | ~40% | **낮음 (정상)** — KPI 아님, 모니터링용 |
| 손익비 | ~6:1 | 이기는 거래가 훨씬 큼 |
| 기대값 | 양(+) | 우리가 진짜 최대화하는 것 |
| MDD | ~-7% | **통제됨** — "질 때 적게 진다" |

> 합성 데이터 기준 예시이며 실제 성과를 보장하지 않습니다.

---

## 테스트

```bash
pytest          # 파이프라인 통합 테스트 (look-ahead 방지·게이트·비용 검증 포함)
```

## 로드맵 (블루프린트 9장)

- [x] **Phase 0** 데이터 파이프라인 (수집·저장·표준 컨테이너, 라이브 어댑터)
- [x] **Phase 1** 백테스트 엔진 + 코어 전략 (비용·유동성·look-ahead·워크포워드)
- [x] **Phase 2** 일일 추천 + 포트폴리오 엔진 (보유/축소/매도/교체)
- [x] **Phase 3** 대시보드 (레짐/섹터/후보/포트 진단/백테스트)
- [ ] **Phase 4** 유료 컨센서스(추정치 리비전 팩터), DART 재무 본격 수집, 페이퍼 트레이딩

## 면책

이 문서·코드는 일반적 시스템 설계 정보이며 투자자문이 아닙니다. 과거 성과는 미래를 보장하지 않습니다.
세법·거래비용·규제는 매년 바뀌므로 시행 시점에 재확인하세요. 실거래 전 페이퍼 트레이딩으로 검증하고 소액으로 시작하세요.
