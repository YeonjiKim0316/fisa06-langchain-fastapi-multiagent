import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("deepresearch.storage")

class StorageBackend:
    def ensure_bucket(self): pass
    def upload(self, path: str, data: bytes): pass
    def download(self, path: str) -> bytes | None: pass
    def remove(self, path: str) -> bool: pass


class LocalDiskStorage(StorageBackend):
    def __init__(self, local_dir: str):
        self.local_dir = local_dir

    def ensure_bucket(self):
        os.makedirs(self.local_dir, exist_ok=True)

    def upload(self, path: str, data: bytes):
        full_path = os.path.join(self.local_dir, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)

    def download(self, path: str) -> bytes | None:
        full_path = os.path.join(self.local_dir, path)
        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                return f.read()
        return None

    def remove(self, path: str) -> bool:
        full_path = os.path.join(self.local_dir, path)
        if os.path.exists(full_path):
            os.remove(full_path)
            return True
        return False


class S3Storage(StorageBackend):
    def __init__(self, bucket: str, aws_access_key: str, aws_secret_key: str, region: str):
        import boto3
        self.bucket = bucket
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=region
        )

    def ensure_bucket(self):
        pass

    def upload(self, path: str, data: bytes):
        self.s3.put_object(Bucket=self.bucket, Key=path, Body=data)

    def download(self, path: str) -> bytes | None:
        import botocore
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=path)
            return response['Body'].read()
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "NoSuchKey":
                return None
            raise

    def remove(self, path: str) -> bool:
        self.s3.delete_object(Bucket=self.bucket, Key=path)
        return True


def get_storage() -> StorageBackend:
    from core.config import get_settings
    settings = get_settings()
    if settings.app_env == "prod":
        return S3Storage(
            settings.s3_bucket_name,
            settings.aws_access_key_id,
            settings.aws_secret_access_key,
            settings.aws_region
        )
    return LocalDiskStorage(settings.local_storage_dir)


def ensure_bucket():
    storage = get_storage()
    storage.ensure_bucket()


def save_report(user_id: str, topic: str, content: str, logs: list = None) -> str | None:
    from core.database import SessionLocal
    from models.report import Report
    
    KST = timezone(timedelta(hours=9))
    ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
    # 토픽을 파일시스템에서 안전한 파일명으로 변환
    safe_topic = re.sub(r'[^\x00-\x7F]', '', topic.replace(' ', '_').replace('/', '_'))
    safe_topic = re.sub(r'[&:?#<>{}|\\^~\[\]`\'"]', '_', safe_topic)
    safe_topic = re.sub(r'_+', '_', safe_topic).strip('_') or "report"

    file_name = f"{safe_topic}_{ts}.md"
    json_name  = f"{safe_topic}_{ts}.json"
    file_path  = f"{user_id}/{file_name}"
    json_path  = f"{user_id}/{json_name}"

    logs_data = logs or []
    logs_json_str = json.dumps(logs_data, ensure_ascii=False, indent=2)

    storage = get_storage()
    try:
        # 마크다운 보고서 저장
        storage.upload(file_path, content.encode("utf-8"))

        # 리서치 로그를 JSON 사이드카 파일로 저장
        storage.upload(json_path, logs_json_str.encode("utf-8"))
        
        db = SessionLocal()
        try:
            report = Report(
                user_id=user_id,
                topic=topic,
                filename=file_name,
                logs_json=logs_json_str
            )
            db.add(report)
            db.commit()
            logger.info(f"Saved report '{topic}' for user {user_id} → {file_path} + {json_path}")
            return file_path
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error saving report: {e}")
        return None


def load_saved_reports(user_id: str) -> list[dict]:
    """DB에서 사용자의 보고서 메타데이터 목록을 내림차순으로 반환한다."""
    from core.database import SessionLocal
    from models.report import Report
    db = SessionLocal()
    try:
        reports = db.query(Report).filter(Report.user_id == user_id).order_by(Report.timestamp.desc()).all()
        return [
            {
                "topic": r.topic,
                "timestamp": r.timestamp,
                "filename": r.filename,
                "path": f"{user_id}/{r.filename}"
            } for r in reports
        ]
    finally:
        db.close()


def get_report_content(user_id: str, filename: str) -> str | None:
    basename = filename.split("/")[-1]
    file_path = f"{user_id}/{basename}"

    storage = get_storage()
    data = storage.download(file_path)
    if data:
        return data.decode("utf-8")
    return None


def get_report_logs(user_id: str, filename: str) -> list:
    from core.database import SessionLocal
    from models.report import Report
    
    basename = filename.split("/")[-1]
    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.user_id == user_id, Report.filename == basename).first()
        if report and report.logs_json:
            return json.loads(report.logs_json)
        return []
    finally:
        db.close()


def delete_report(user_id: str, filename: str) -> bool:
    from core.database import SessionLocal
    from models.report import Report
    
    basename = filename.split("/")[-1]
    file_path = f"{user_id}/{basename}"
    json_path = f"{user_id}/{basename.replace('.md', '.json')}"

    storage = get_storage()
    storage.remove(file_path)
    storage.remove(json_path)   # JSON 사이드카 파일도 함께 삭제

    db = SessionLocal()
    try:
        report = db.query(Report).filter(Report.user_id == user_id, Report.filename == basename).first()
        if report:
            db.delete(report)
            db.commit()
            return True
        return False
    finally:
        db.close()
