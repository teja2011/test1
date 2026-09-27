#!/usr/bin/env python
from dotenv import load_dotenv
import os

env_path = os.path.join(os.path.dirname(__file__), '.env')
print(f"Loading .env from: {env_path}")
load_dotenv(env_path, override=True)

DATABASE_URL = os.environ.get('DATABASE_URL')
print(f"DATABASE_URL: {DATABASE_URL[:60] if DATABASE_URL else 'NOT FOUND'}...")

if DATABASE_URL and ('mysql' in DATABASE_URL or 'pymysql' in DATABASE_URL):
    print("OK: Using MySQL")

    from sqlalchemy import create_engine, text

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text("SHOW TABLES"))
        tables = [row[0] for row in result]
        print(f"Tables: {tables}")

    print("SUCCESS: Database connection works!")
else:
    print("ERROR: DATABASE_URL not set or not MySQL")