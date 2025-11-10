import os
import time
import json
import psycopg2
from datetime import datetime, timezone

# 1. 환경 변수에서 설정 읽기
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME")
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", 60)) #
MOUNT_PATH = os.environ.get("MOUNT_PATH") #
NODE_NAME = os.environ.get("MY_NODE_NAME") #

def get_db_connection():
    """DB 연결 시도"""
    print(f"Connecting to DB_HOST: {DB_HOST}", flush=True)
    conn = psycopg2.connect(
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        dbname=DB_NAME
    )
    return conn

def ensure_table_exists(conn):
    """애플리케이션 시작 시 테이블 자동 생성 """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS file_monitor (
                id SERIAL PRIMARY KEY,
                NodeName TEXT NOT NULL,
                MountPath TEXT NOT NULL,
                FileList JSONB,
                CollectedAt TIMESTAMPTZ NOT NULL
            );
        """) #
        conn.commit()
    print("Table 'file_monitor' is ready.", flush=True)

def scan_files(path):
    """지정된 경로의 파일 목록을 스캔하여 JSON 문자열로 반환 """
    print(f"Scanning directory: {path}", flush=True)
    try:
        files = os.listdir(path)
        return json.dumps(files) # JSON 형태로 반환 
    except Exception as e:
        print(f"Error scanning {path}: {e}", flush=True)
        return json.dumps() # 오류 발생 시 빈 리스트

def insert_data(conn, file_list_json):
    """스캔한 데이터를 DB에 삽입 """
    try:
        with conn.cursor() as cur:
            collected_time = datetime.now(timezone.utc)
            cur.execute(
                """
                INSERT INTO file_monitor (NodeName, MountPath, FileList, CollectedAt)
                VALUES (%s, %s, %s, %s)
                """,
                (NODE_NAME, MOUNT_PATH, file_list_json, collected_time)
            )
            conn.commit()
        print(f"Successfully saved data from node {NODE_NAME}.", flush=True)
    except Exception as e:
        print(f"Error saving to DB: {e}", flush=True)
        conn.rollback() # 오류 시 롤백

def main_loop():
    """주기적 실행을 위한 메인 루프 """
    conn = None
    while True:
        try:
            if conn is None or conn.closed:
                print("Connecting to database...", flush=True)
                conn = get_db_connection()
                ensure_table_exists(conn)

            file_list_json = scan_files(MOUNT_PATH)
            insert_data(conn, file_list_json)

        except Exception as e:
            print(f"Main loop error: {e}", flush=True)
            if conn:
                conn.close()
            conn = None # 다음 루프에서 재연결 시도

        print(f"Scan complete. Sleeping for {SCAN_INTERVAL} seconds.", flush=True)
        time.sleep(SCAN_INTERVAL) # time.sleep을 이용한 Ticker 구현 

if __name__ == "__main__":
    print("Harman Agent Started.", flush=True)
    if not all():
        print("Error: Missing required environment variables.", flush=True)
        exit(1)
    main_loop()
