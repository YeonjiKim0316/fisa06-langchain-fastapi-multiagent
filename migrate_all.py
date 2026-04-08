import os
import asyncio
from dotenv import load_dotenv

# Force load from .env directly over everything
load_dotenv(".env", override=True)
os.environ["APP_ENV"] = "prod"  # to ensure pydantic loads settings as prod

import alembic.config
import alembic.command

def migrate_db():
    print("--- Running Alembic Migration for User DB ---")
    alembic_cfg = alembic.config.Config("alembic.ini")
    alembic.command.upgrade(alembic_cfg, "head")
    print("User DB migrated successfully!\n")

async def init_services():
    from services.storage_service import ensure_bucket
    from deep_ai.agent import init_checkpointer
    
    print("--- Ensuring S3 Bucket exists ---")
    try:
        ensure_bucket()
        print("S3 Bucket ensured successfully!\n")
    except Exception as e:
        print(f"Error ensuring S3 Bucket: {e}\n")

    print("--- Initializing Checkpointer DB ---")
    try:
        await init_checkpointer()
        print("Checkpointer DB initialized successfully!\n")
    except Exception as e:
        print(f"Error initializing checkpointer DB: {e}\n")

if __name__ == "__main__":
    migrate_db()
    asyncio.run(init_services())
