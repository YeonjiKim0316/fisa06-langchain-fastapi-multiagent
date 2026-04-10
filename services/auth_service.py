import logging
import jwt
from datetime import datetime, timedelta, timezone
import bcrypt
from core.config import get_settings

logger = logging.getLogger("fisaai6-multi-agent.auth")
settings = get_settings()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7일


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)
    return encoded_jwt


def sign_up(email: str, password: str, full_name: str):
    """새 사용자를 등록한다. (user, access_token)을 반환하거나 예외를 발생시킨다."""
    from core.database import SessionLocal
    from models.user import User
    db = SessionLocal()
    try:
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            raise ValueError("이미 존재하는 이메일입니다.")
        hashed_password = _hash_password(password)
        new_user = User(email=email, hashed_password=hashed_password, full_name=full_name)
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        token = create_access_token(data={"sub": new_user.id})
        class UserObj: pass
        u = UserObj()
        u.id = new_user.id
        u.email = new_user.email
        logger.info(f"User signed up: {email}")
        return u, token
    finally:
        db.close()


def sign_in(email: str, password: str):
    """기존 사용자를 인증한다. (user, access_token)을 반환하거나 예외를 발생시킨다."""
    from core.database import SessionLocal
    from models.user import User
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not _verify_password(password, user.hashed_password):
            raise ValueError("이메일 또는 비밀번호가 올바르지 않습니다.")
        token = create_access_token(data={"sub": user.id})
        class UserObj: pass
        u = UserObj()
        u.id = user.id
        u.email = user.email
        logger.info(f"User signed in: {email}")
        return u, token
    finally:
        db.close()


def sign_out(access_token: str | None = None):
    """로그아웃 처리 (무상태 JWT — 서버 측 상태 불필요)."""
    pass


def get_user_from_token(access_token: str):
    """JWT를 검증하고 유저 객체를 반환한다. 유효하지 않으면 None 반환."""
    from core.database import SessionLocal
    from models.user import User
    try:
        payload = jwt.decode(access_token, settings.secret_key, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None
    except jwt.PyJWTError:
        return None
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            class UserObj: pass
            u = UserObj()
            u.id = user.id
            u.email = user.email
            return u
        return None
    finally:
        db.close()
