#!/usr/bin/env python
from dotenv import load_dotenv
import os

# Явно указываем путь к .env
env_path = os.path.join(os.path.dirname(__file__), '.env')
print(f"Loading .env from: {env_path}")
load_dotenv(env_path, override=True)

DATABASE_URL = os.environ.get('DATABASE_URL')
print(f"DATABASE_URL: {DATABASE_URL[:60] if DATABASE_URL else 'NOT FOUND'}...")

if DATABASE_URL and 'supabase' in DATABASE_URL:
    print("OK: Using Supabase")
    
    from sqlalchemy import create_engine, text
    
    engine = create_engine(DATABASE_URL)
    conn = engine.connect()
    
    result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    tables = [row[0] for row in result]
    print(f"Tables: {tables}")
    
    conn.close()
    print("SUCCESS: Database connection works!")
else:
    print("ERROR: DATABASE_URL not set or not Supabase")
