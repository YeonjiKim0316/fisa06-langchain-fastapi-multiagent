from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from core.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    topic = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False, unique=True, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),  # 앱 레벨: 밀리초 정밀도
        nullable=False,
    )
    logs_json = Column(Text, nullable=True)
