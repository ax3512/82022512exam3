# IA 영향도검토 플랫폼 - 설치 가이드

---

## 1. 필요 파일

| # | 파일 | 용량 | 비고 |
|---|------|------|------|
| 1 | `ia-chatbot-v3-deploy.zip` | 240KB | 소스코드 + pgvector |
| 2 | `ia_chatbot_backup.dump` | 1.4MB | DB 데이터 (적재된 문서/벡터) |
| 3 | `python-3.10.2-amd64.exe` | 27MB | Python 설치파일 |
| 4 | `postgresql-16-installer.exe` | 329MB | PostgreSQL 설치파일 |
| 5 | `models.zip` | 4.3GB | 임베딩 모델 (메일 또는 USB) |

---

## 2. 설치 순서

### STEP 1. Python 설치(있으면 pass)

1. `python-3.10.2-amd64.exe` 실행
2. **반드시 "Add Python 3.10 to PATH" 체크** (하단 체크박스)
3. "Install Now" 클릭
4. 설치 완료 확인:
```
cmd 열고 입력:
python --version

결과: Python 3.10.2 → 정상
```

---

### STEP 2. PostgreSQL 설치

1. `postgresql-16-installer.exe` 실행
2. 설치 옵션:
   - 설치 경로: 기본값 (`C:\Program Files\PostgreSQL\16`)
   - Components: 전부 체크
   - 비밀번호: `postgres` (또는 원하는 비밀번호 ? **반드시 기억**)
   - 포트: `5432` (기본값)
   - Locale: `Korean, Korea`
3. Stack Builder 창이 뜨면 → 닫기
4. 설치 확인:
```
cmd 열고 입력:
netstat -ano | findstr 5432

결과: TCP 0.0.0.0:5432 ... LISTENING → 정상
```

---

### STEP 3. 소스코드 배포

1. `ia-chatbot-v3-deploy.zip` 압축 해제
2. 원하는 위치에 폴더 배치 (예: `C:\ia-chatbot-v3`)
```
C:\ia-chatbot-v3\
├── src\
├── client\
├── scripts\
├── pgvector\
├── config.yaml
├── install.bat
├── start.bat
└── ...
```

---

### STEP 4. pgvector 설치

> pgvector는 PostgreSQL에서 벡터 검색을 가능하게 하는 확장 모듈입니다.

1. 소스 폴더의 `pgvector\` 안의 파일들을 PostgreSQL 설치 경로에 복사:

```
복사 대상:
  pgvector\vector.dll
    → C:\Program Files\PostgreSQL\16\lib\

  pgvector\vector.control 및 vector*.sql (나머지 전부)
    → C:\Program Files\PostgreSQL\16\share\extension\
```

2. 탐색기에서 직접 복사/붙여넣기 하면 됩니다.
   - 관리자 권한 필요 시 → 마우스 우클릭 "관리자 권한으로 붙여넣기"

---

### STEP 5. DB 초기화 + 데이터 복원

> `setup_db.bat`이 DB 테이블 생성 + 기존 문서 데이터 복원을 자동으로 합니다.

1. `ia_chatbot_backup.dump` 파일을 소스 폴더에 복사 (기존 문서 포함 시)
2. 소스 폴더에서 `setup_db.bat` 더블클릭
3. PostgreSQL 비밀번호 입력 (2회)

```
실행 결과:
[1/2] DB init... CREATE TABLE ... [OK]
[2/2] Restoring data... [OK]
DB Setup Done!
```

> 비밀번호나 포트가 다른 경우, setup_db.bat을 메모장으로 열어 상단의 PORT, USER 값을 수정하세요.

---

### STEP 8. config.yaml 수정

소스 폴더의 `config.yaml` 파일을 메모장으로 열어 DB 정보 수정:

```yaml
storage:
  postgresql:
    host: localhost
    port: 5432          ← PostgreSQL 포트 (기본: 5432)
    dbname: ia_chatbot
    user: postgres
    password: postgres   ← STEP 2에서 설정한 비밀번호
```

LLM API 설정 (변경 필요 시):
```yaml
llm:
  api_key: app-xxxx     ← Dify API 키
  base_url: https://api.abclab.ktds.com/v1
```

---

### STEP 9. 패키지 설치

소스 폴더에서 `install.bat` 더블클릭

```
실행 결과:
[1/4] Python check... Python 3.10.2 [OK]
[2/4] venv setup... [OK] venv created
[3/4] pip install... [OK] packages installed
[4/4] Model check... [OK] model exists - skip
Done!
```

> pip install 시 사내망 환경에 맞게 --trusted-host 옵션이 자동 적용됩니다.

---

### STEP 10. 서버 실행

소스 폴더에서 `start.bat` 더블클릭

```
============================================
  IA Server - http://localhost:8005
============================================

[OK] venv activated
Python 3.10.2
Starting server...
INFO: Uvicorn running on http://0.0.0.0:8005
```

브라우저에서 접속: **http://localhost:8005**

---

## 3. 사용 방법

### 채팅 (질문 응답)
- 좌측 메뉴 "채팅" 선택
- 질문 입력 후 Enter (Shift+Enter: 줄바꿈)
- 예시: "아이폰 단말보험 개발과제 알려줘"
- 연계질문: "테이블 변경사항 알려줘" → 이전 답변 기반 자동 응답
- 중지 버튼으로 LLM 처리 중 취소 가능

### 문서 적재
- 좌측 메뉴 "문서적재" 선택
- DOCX 파일이 있는 폴더 경로 입력 → 스캔 → 적재
- 암호화 문서는 자동 감지하여 안내

### 시각화
- 좌측 메뉴 "시각화" 선택
- 대분류 → 클릭하면 중분류 → 소분류 → 문서(DR번호) 순으로 탐색
- DR번호 검색으로 해당 문서의 카테고리 경로 확인
- 문서 클릭 시 오른쪽에 요약 패널 표시

---

## 4. 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| `python` 명령 안 됨 | PATH 미등록 | Python 재설치 시 "Add to PATH" 체크 |
| pip install 실패 | 사내망 SSL 차단 | `--trusted-host` 자동 적용됨. 프록시 설정 확인 |
| 포트 8005 사용 중 | 기존 서버 실행 중 | `netstat -ano \| findstr 8005`로 PID 확인 후 종료 |
| DB 연결 실패 | 포트/비밀번호 불일치 | config.yaml 확인 |
| 모델 로딩 느림 | 최초 실행 시 정상 | 첫 질문 시 30초~1분 소요, 이후 빠름 |
| 임베딩 실패 알림 | 모델 경로 오류 | models 폴더 위치 확인 |

---

## 5. 시스템 요구사항

| 항목 | 최소 사양 |
|------|----------|
| OS | Windows 10/11 64bit |
| RAM | 8GB 이상 (16GB 권장) |
| 디스크 | 10GB 이상 여유 공간 |
| Python | 3.10 이상 |
| PostgreSQL | 16 + pgvector |
| 네트워크 | LLM API 접근 필요 (Dify) |
