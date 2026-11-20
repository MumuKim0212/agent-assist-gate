# agent-assist-gate

기업 민원센터 상담원이 통화 중에 근거 문서를 찾도록 돕는 **검색 보조 시스템의 데모**버전.
생성형 답변 없이 저장된 원문만 보여 주고, 검색 점수로 **응답 방식(답변 제시, 되묻기 안내, 거절)**을 정하는 게이트를 둔다. 민원인에게 실제로 무엇을 말할지는 상담원이 정한다.

> **이 저장소는 데모다.** 코퍼스와 평가셋은 가상 기관("누리직업능력개발협회")을 위해 새로 쓴 것이고, 실제 협회의 자료는 한 줄도 들어 있지 않다. 
> 이 데모의 점수는 방법이 돌아간다는 표시이지 검색 품질의 증거가 아니다. 실제 자료로 측정한 결과와 그 한계는 [`CASE-STUDY.md`](CASE-STUDY.md)에 있다.

## 왜 이런 설계인가

사용자는 민원인이 아니라 **상담원**이고, 상담원은 결과를 그대로 민원인에게 전달한다. 그래서 가장 나쁜 실패는 "못 찾음"이 아니라 **그럴듯한 오답**이다. 이 데모의 게이트와 평가는 모두 그 비대칭 위에 있다.

| 행동 | 언제 |
|---|---|
| `answer` | 점수가 충분하고 경쟁 문서가 없다 |
| `answer_flagged` | 답은 있지만 내용 확인이 끝나지 않은 문서 (배지와 함께) |
| `clarify` | 비슷한 문서들이 등급, 대상, 행위에서 갈린다 → 민원인에게 되물어야 한다 |
| `refuse` | 점수가 낮거나 애매하다 → 담당 부서를 안내하거나 "문서에 없음" |

## Start a project

```
pip install -r requirements.txt
python -m pytest tests                          # 102개
python -m serve.app                             # http://127.0.0.1:8000 - 예시 질문을 눌러 보는 화면
python -m serve.ask "사진 파일은 어떤 크기로 올려야 하나요"
python -m serve.ask "회비 감면을 받을 수 있는 조건이 있나요"   # 거절 + 담당 부서
python -m eval.score                            # 홀드아웃 채점 (docs/evaluation-method.md)
```

데이터를 다시 만들려면: `python data/build_corpus.py && python data/build_eval.py`. 
임계값을 다시 맞추려면 `python -m eval.fit_thresholds --write`. 
임베딩/리랭크(`core/config.yaml`의 `embedding_model`, `rerank`)는 `GOOGLE_API_KEY`가 필요하며(`.env.example`) 이 데모에서는 키 없이 BM25로 돈다. 
외부 API를 쓰는 경로는 단위 테스트(가짜 전송)로만 검증했고 라이브로는 돌려 보지 않았다.

## 구성

| 위치 | 내용 |
|---|---|
| `core/` | 색인(BM25 / 임베딩 / 하이브리드), 검색, 게이트, 임베딩·리랭크 연동, 질의 비식별 |
| `eval/` | 채점기, 임계값 적합, 가상 평가셋 |
| `serve/` | 예시 질문 화면(`app.py`), 명령줄 질의(`ask.py`), 부서 안내 |
| `data/` | 가상 코퍼스와 평가셋 생성 스크립트 |
| `docs/` | 핵심 설계 결정, 평가 방법, 평가셋 오염 사례 |
| `knowledge/` | 가상 코퍼스(`docs.jsonl`, `data/build_corpus.py`가 생성) |
| `api/`, `vercel.json` | Vercel 배포용 진입점과 설정. `serve.app`과 같은 화면을 서버리스 함수로 제공하며 BM25만 쓰므로 API 키가 필요 없다 |
| `tests/` | 102개 테스트 |

## 읽는 순서

1. [`CASE-STUDY.md`](CASE-STUDY.md) - 프로젝트 전체와 실제 측정 결과, 그리고 한계
2. [`docs/case-study-eval-contamination.md`](docs/case-study-eval-contamination.md) - 평가셋이 점수를 부풀리고 있었던 사례
3. [`docs/decisions.md`](docs/decisions.md) - 핵심 설계 결정 5건(왜 그렇게 정했고 무엇을 기각했는가)
4. [`docs/evaluation-method.md`](docs/evaluation-method.md) - 무엇을 어떻게 재는가

## 이 데모에 없는 것

원본 정제 파이프라인, 릴리스 게이트, 근거 검사(LLM 판정기), 실제 평가 문항.
