# JWT 인증 완전 정복 — FastAPI 입문자를 위한 가이드

이 문서는 현재 프로젝트(FISA AI Multi-Agent DeepResearcher)에서 JWT를 어떻게 쓰는지를 중심으로, FastAPI를 막 배우기 시작한 분들이 이해할 수 있도록 작성되었습니다.

---

## 1. JWT가 필요한 이유

### "로그인 상태"를 어떻게 기억할까?

웹 서버는 기본적으로 **무상태(stateless)** 입니다. HTTP 요청 하나가 끝나면 서버는 그 사용자를 기억하지 않습니다. 그래서 "로그인 후 내 정보 보기" 같은 기능을 만들려면, **"이 요청을 보낸 사람이 누구인지"를 매 요청마다 증명하는 수단**이 필요합니다.

전통적인 방법은 **세션(Session)** 입니다.

```
[전통적 세션 방식]

1. 로그인 → 서버가 세션 ID 발급 → DB에 저장
2. 이후 요청마다 → 클라이언트가 세션 ID 전송 → 서버가 DB에서 조회
```

단점: 요청마다 DB를 찌르기 때문에 **부하가 생기고, 서버를 여러 대 운영하면 복잡**해집니다.

JWT는 이 문제를 다르게 풉니다.

```
[JWT 방식]

1. 로그인 → 서버가 JWT(토큰) 발급 → 클라이언트에 저장
2. 이후 요청마다 → 클라이언트가 JWT 전송 → 서버가 서명만 검증 (DB 조회 없음)
```

서버는 DB를 보지 않아도 토큰의 **서명**만 확인하면 누구의 요청인지 알 수 있습니다.

---

## 2. JWT 구조 — 세 조각의 비밀

JWT는 점(`.`)으로 구분된 세 부분으로 이루어진 문자열입니다.

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOjEsImV4cCI6MTc0OTk4MDAwMH0.abc123xyz
         ↑ Header                              ↑ Payload                    ↑ Signature
```

| 부분 | 내용 | 예시 |
|------|------|------|
| **Header** | 알고리즘 정보 | `{"alg": "HS256", "typ": "JWT"}` |
| **Payload** | 실제 데이터 (클레임) | `{"sub": 42, "exp": 1749980000}` |
| **Signature** | 위변조 방지 서명 | Header + Payload를 SECRET_KEY로 서명한 값 |

> Header와 Payload는 Base64로 인코딩된 것이지 암호화된 게 아닙니다.  
> 누구나 디코딩해서 내용을 볼 수 있습니다. **민감한 정보(비밀번호 등)를 절대 넣으면 안 됩니다.**

### Signature가 핵심

서버만 알고 있는 `SECRET_KEY`로 서명하기 때문에, 누군가가 Payload를 조작하면 Signature가 맞지 않아 **서버가 즉시 위변조를 감지**합니다.

---

## 3. 이 프로젝트에서 JWT를 어떻게 쓰는가

### 전체 흐름

```
[로그인/회원가입]
사용자 → POST /auth/login → sign_in() → create_access_token() → JWT 발급
                                                                     ↓
                                              HTTP 쿠키(access_token)에 저장

[보호된 페이지 접근]
사용자 → GET /dashboard → require_user() → get_user_from_token() → 유저 객체 반환
          쿠키에서 JWT 읽기 ↑
```

### 관련 파일

| 파일 | 역할 |
|------|------|
| [services/auth_service.py](services/auth_service.py) | JWT 생성·검증, 로그인·회원가입 로직 |
| [core/dependencies.py](core/dependencies.py) | FastAPI Depends()에 사용할 인증 의존성 함수 |
| [routers/auth.py](routers/auth.py) | 로그인/로그아웃 라우터, 쿠키 처리 |
| [core/config.py](core/config.py) | `SECRET_KEY` 등 설정값 관리 |

---

## 4. 코드로 보는 JWT 사용 패턴

### Step 1 — 토큰 생성 (`services/auth_service.py`)

```python
import jwt
from datetime import datetime, timedelta, timezone

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7일

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})                          # 만료 시각 추가
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt
```

- `data`에는 `{"sub": user.id}` 형태로 사용자 ID를 담습니다.
  - `sub`(subject)는 JWT 표준 클레임으로, "이 토큰의 주체"를 나타냅니다.
- `exp`(expiration)을 추가하면 PyJWT가 만료된 토큰을 자동으로 거부합니다.
- `jwt.encode(payload, secret_key, algorithm)` 한 줄로 서명된 JWT 문자열이 만들어집니다.

로그인 성공 시 이렇게 호출됩니다:

```python
# sign_in() 내부
token = create_access_token(data={"sub": user.id})
return user, token
```

---

### Step 2 — 쿠키에 저장 (`routers/auth.py`)

```python
@router.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    user, token = sign_in(email, password)
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,   # JS에서 접근 불가 → XSS 방어
        samesite="lax",  # 외부 사이트에서의 전송 제한 → CSRF 방어
        max_age=60 * 60 * 24,  # 24시간 후 브라우저가 쿠키 삭제
    )
    return response
```

JWT를 저장하는 방법은 크게 두 가지입니다.

| 저장 위치 | 장점 | 단점 |
|-----------|------|------|
| **localStorage** | JS로 쉽게 읽기 가능 | XSS 공격에 취약 |
| **HttpOnly 쿠키** (이 프로젝트) | JS에서 접근 불가 → XSS 안전 | CSRF 주의 필요 (samesite로 방어) |

이 프로젝트는 `httponly=True` 쿠키를 사용해 보안을 강화했습니다.

---

### Step 3 — 토큰 검증 (`services/auth_service.py`)

```python
def get_user_from_token(access_token: str):
    try:
        payload = jwt.decode(
            access_token,
            settings.secret_key,
            algorithms=[ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            return None
    except jwt.PyJWTError:   # 서명 불일치, 만료, 형식 오류 모두 여기서 잡힘
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        ...
        return user
    finally:
        db.close()
```

- `jwt.decode()`는 서명 검증 + 만료 확인을 동시에 합니다.
- 검증 실패 시 `jwt.PyJWTError` 예외가 발생하고, `None`을 반환해 인증 실패로 처리합니다.
- 검증 성공 후에는 `sub`(user_id)로 DB에서 실제 유저를 조회합니다.

---

### Step 4 — 라우터 보호 (`core/dependencies.py`)

```python
from fastapi import Request
from services.auth_service import get_user_from_token

def get_current_user(request: Request):
    """쿠키에서 토큰을 꺼내 검증 → 유저 or None"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_user_from_token(token)


def require_user(request: Request):
    """로그인 필수 라우트용 — 미인증 시 로그인 페이지로 리다이렉트"""
    user = get_current_user(request)
    if not user:
        raise StarletteHTTPException(
            status_code=302,
            headers={"Location": "/auth/login"},
        )
    return user
```

FastAPI의 `Depends()`와 결합하면 라우터마다 인증을 한 줄로 적용할 수 있습니다.

```python
from fastapi import Depends
from core.dependencies import require_user

@router.get("/dashboard")
async def dashboard(request: Request, user=Depends(require_user)):
    # 여기까지 도달했다면 user는 반드시 인증된 유저
    return templates.TemplateResponse("dashboard.html", {"user": user})
```

> `Depends(require_user)`를 쓰면 FastAPI가 라우터 함수 실행 전에 자동으로 `require_user`를 호출합니다. 인증에 실패하면 라우터 함수 자체가 실행되지 않습니다.

---

### Step 5 — 로그아웃 (`routers/auth.py`)

```python
@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token")  # 쿠키 삭제
    return response
```

JWT 방식의 특징: 서버에 저장된 세션이 없으므로 **클라이언트의 쿠키만 지우면 로그아웃**이 완료됩니다. `sign_out()` 함수 내부가 비어 있는 것도 이 이유입니다.

---

## 5. 비밀번호는 어떻게 처리하나? — bcrypt

JWT와 함께 쓰이는 비밀번호 해싱도 간단히 살펴봅니다.

```python
import bcrypt

def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def _verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
```

- `bcrypt.gensalt()`가 매번 다른 salt를 생성하므로, 같은 비밀번호도 해시 결과가 달라집니다.
- DB에는 원본 비밀번호가 아닌 해시값만 저장됩니다.
- 비교 시에는 `checkpw()`를 사용합니다. 직접 `==`로 비교하면 안 됩니다.

---

## 6. SECRET_KEY 관리

```python
# core/config.py
class Settings(BaseSettings):
    secret_key: str = "change-me-in-production"
```

`SECRET_KEY`는 JWT 서명의 핵심입니다. 유출되면 누구나 유효한 토큰을 만들 수 있습니다.

- 로컬 개발: `.env` 파일에 적당한 값 사용
- 운영 환경: 충분히 길고 무작위한 값 사용 (예: `openssl rand -hex 32`)
- **절대 코드에 하드코딩하거나 git에 커밋하지 않습니다**

---

## 7. 전체 흐름 요약 다이어그램

```
[회원가입 / 로그인]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
브라우저                     FastAPI 서버               DB
   │                              │                      │
   │  POST /auth/login            │                      │
   │  email, password ──────────>│                      │
   │                              │  SELECT * FROM users │
   │                              │─────────────────────>│
   │                              │<─────────────────────│
   │                              │  bcrypt 검증         │
   │                              │  JWT 생성            │
   │<── Set-Cookie: access_token ─│  (sub=user_id, exp)  │
   │    (httponly)                │                      │


[보호된 페이지 접근]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
브라우저                     FastAPI 서버               DB
   │                              │                      │
   │  GET /dashboard              │                      │
   │  Cookie: access_token ──────>│                      │
   │                              │  jwt.decode() 검증   │
   │                              │  서명 OK + 미만료?   │
   │                              │  sub → user_id       │
   │                              │  DB에서 유저 조회    │
   │                              │─────────────────────>│
   │                              │<─────────────────────│
   │<── 200 OK (대시보드 HTML) ───│                      │


[로그아웃]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
브라우저                     FastAPI 서버
   │                              │
   │  POST /auth/logout ─────────>│
   │<── Set-Cookie: access_token= │  (쿠키 삭제)
   │    Max-Age=0                 │
```

---

## 8. 핵심 요약

| 개념 | 이 프로젝트에서 |
|------|----------------|
| JWT 라이브러리 | `PyJWT` (`import jwt`) |
| 서명 알고리즘 | `HS256` (대칭키) |
| Payload | `{"sub": user_id, "exp": 만료시각}` |
| 저장 방식 | `HttpOnly` 쿠키 (`access_token`) |
| 토큰 유효기간 | 생성 시 7일, 쿠키는 24시간 |
| 검증 함수 | `get_user_from_token()` |
| 라우터 보호 | `Depends(require_user)` |
| 비밀번호 해싱 | `bcrypt` |
| 로그아웃 | 쿠키 삭제 (서버 상태 변경 없음) |
