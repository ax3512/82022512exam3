"""
DB 연결 모듈 — PostgreSQL / Oracle 지원.
D:\MCP\mcp_server\db.py 기반으로 IA 챗봇 V2에 맞게 적응.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── DB config 파일 경로 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_CONFIG_FILE = PROJECT_ROOT / "db_config.json"

# ── 드라이버 감지 ────────────────────────────────────────────────
PSYCOPG_VERSION = 0
try:
    import psycopg          # type: ignore
    from psycopg.rows import dict_row  # type: ignore
    PSYCOPG_VERSION = 3
except ImportError:
    try:
        import psycopg2                       # type: ignore
        from psycopg2.extras import RealDictCursor  # type: ignore
        PSYCOPG_VERSION = 2
    except ImportError:
        pass

ORACLE_AVAILABLE = False
ORACLE_THICK_MODE_INITIALIZED = False
try:
    import oracledb  # type: ignore
    ORACLE_AVAILABLE = True
except ImportError:
    pass


# ── 설정 로드/저장 ───────────────────────────────────────────────

def _default_config() -> dict:
    return {
        "active_db_type": "postgres",
        "db_postgres": {
            "user": "postgres",
            "password": "postgres",
            "host": "localhost",
            "port": "5432",
            "dbname": "postgres",
        },
        "db_oracle": {
            "user": "system",
            "password": "oracle",
            "host": "localhost",
            "port": "1521",
            "service_name": "ORCL",
            "sid": None,
            "thick_mode": False,
            "oracle_client_lib_dir": None,
        },
    }


def load_db_config() -> dict:
    """db_config.json 로드. 없으면 기본값 반환."""
    if DB_CONFIG_FILE.exists():
        try:
            with open(DB_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _default_config()


def save_db_config(cfg: dict):
    """db_config.json 저장."""
    with open(DB_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def get_all_db_configs() -> dict:
    """프론트엔드 UI용 전체 DB 설정 반환."""
    cfg = load_db_config()
    defaults = _default_config()
    return {
        "active_db_type": cfg.get("active_db_type", "postgres"),
        "db_postgres": cfg.get("db_postgres", defaults["db_postgres"]),
        "db_oracle": cfg.get("db_oracle", defaults["db_oracle"]),
    }


# ── Oracle Thick 모드 ────────────────────────────────────────────

def _get_bundled_oracle_client_path() -> Optional[str]:
    possible = []
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
    else:
        app_dir = str(PROJECT_ROOT)
    possible.append(os.path.join(app_dir, "oracle"))
    possible.append(os.path.join(app_dir, "oracle_client"))
    for p in possible:
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "oci.dll")):
            return p
    return None


def _init_oracle_thick_mode(lib_dir: str | None = None) -> bool:
    global ORACLE_THICK_MODE_INITIALIZED
    if not ORACLE_AVAILABLE:
        raise ImportError("oracledb 패키지가 설치되어 있지 않습니다.")
    if ORACLE_THICK_MODE_INITIALIZED:
        return True

    if (not lib_dir or lib_dir.strip() == "") and sys.platform == "win32":
        bundled = _get_bundled_oracle_client_path()
        if bundled:
            lib_dir = bundled
            print(f"[Oracle] 번들 클라이언트 사용: {lib_dir}")

    print(f"[Oracle] Thick mode 초기화 중... lib_dir={lib_dir}")
    try:
        if lib_dir:
            if sys.platform == "win32":
                cur_path = os.environ.get("PATH", "")
                if lib_dir not in cur_path:
                    os.environ["PATH"] = lib_dir + os.pathsep + cur_path
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(lib_dir)
            oracledb.init_oracle_client(lib_dir=lib_dir)
        else:
            oracledb.init_oracle_client()
        ORACLE_THICK_MODE_INITIALIZED = True
        print("[Oracle] Thick mode 초기화 완료")
        return True
    except Exception as e:
        err = str(e).lower()
        if "already" in err or "dpy-2017" in err:
            ORACLE_THICK_MODE_INITIALIZED = True
            return True
        raise


# ── 추상 DB 연결 ─────────────────────────────────────────────────

class BaseDatabaseConnection(ABC):
    def __init__(self, db_config: dict):
        self.db_config = db_config
        self._connection = None

    @abstractmethod
    def connect(self): ...

    @abstractmethod
    def close(self): ...

    @abstractmethod
    def get_cursor(self, dict_cursor: bool = True): ...

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]: ...

    @abstractmethod
    def get_db_type(self) -> str: ...

    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            if cursor.description:
                columns = [desc[0].lower() for desc in cursor.description]
                results = cursor.fetchall()
                return [dict(zip(columns, row)) for row in results]
            return []


# ── PostgreSQL ────────────────────────────────────────────────────

class PostgreSQLConnection(BaseDatabaseConnection):
    def connect(self):
        if PSYCOPG_VERSION == 0:
            raise ImportError("PostgreSQL 드라이버가 없습니다. psycopg 또는 psycopg2를 설치하세요.")
        cfg = self.db_config
        if PSYCOPG_VERSION == 3:
            if self._connection is None or self._connection.closed:
                connstr = f"postgresql://{cfg['user']}:{cfg['password']}@{cfg['host']}:{cfg['port']}/{cfg['dbname']}"
                self._connection = psycopg.connect(connstr)
        else:
            if self._connection is None or self._connection.closed:
                self._connection = psycopg2.connect(
                    dbname=cfg["dbname"],
                    user=cfg["user"],
                    password=cfg["password"],
                    host=cfg["host"],
                    port=cfg["port"],
                )
        return self._connection

    def close(self):
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        conn = self.connect()
        if PSYCOPG_VERSION == 3:
            cursor = conn.cursor(row_factory=dict_row) if dict_cursor else conn.cursor()
        else:
            factory = RealDictCursor if dict_cursor else None
            cursor = conn.cursor(cursor_factory=factory)
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            cursor.execute(query, params)
            if cursor.description:
                results = cursor.fetchall()
                return [dict(row) for row in results]
            return []

    def test_connection(self) -> Tuple[bool, str]:
        try:
            with self.get_cursor() as cur:
                cur.execute("SELECT 1")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_db_type(self) -> str:
        return "postgres"


# ── Oracle ────────────────────────────────────────────────────────

class OracleConnection(BaseDatabaseConnection):
    def connect(self):
        if not ORACLE_AVAILABLE:
            raise ImportError("oracledb 패키지가 설치되어 있지 않습니다.")
        if self._connection is None:
            cfg = self.db_config
            if cfg.get("thick_mode", False):
                _init_oracle_thick_mode(cfg.get("oracle_client_lib_dir"))
            if cfg.get("sid"):
                dsn = oracledb.makedsn(cfg["host"], int(cfg["port"]), sid=cfg["sid"])
            else:
                dsn = oracledb.makedsn(cfg["host"], int(cfg["port"]), service_name=cfg.get("service_name", "ORCL"))
            self._connection = oracledb.connect(user=cfg["user"], password=cfg["password"], dsn=dsn)
        return self._connection

    def close(self):
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    @contextmanager
    def get_cursor(self, dict_cursor: bool = True):
        conn = self.connect()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    def test_connection(self) -> Tuple[bool, str]:
        try:
            with self.get_cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
            return True, ""
        except Exception as e:
            return False, str(e)

    def get_db_type(self) -> str:
        return "oracle"


# ── 팩토리 & 싱글턴 ──────────────────────────────────────────────

def create_connection(db_config: dict | None = None) -> BaseDatabaseConnection:
    if db_config is None:
        cfg = load_db_config()
        db_type = cfg.get("active_db_type", "postgres")
        db_config = cfg.get(f"db_{db_type}", cfg.get("db_postgres", {}))
        db_config["_db_type"] = db_type
    db_type = db_config.get("_db_type", db_config.get("db_type", "postgres"))
    if db_type == "oracle":
        return OracleConnection(db_config)
    return PostgreSQLConnection(db_config)


_db_instance: BaseDatabaseConnection | None = None


def get_db() -> BaseDatabaseConnection:
    global _db_instance
    if _db_instance is None:
        _db_instance = create_connection()
    return _db_instance


def reset_db(db_config: dict | None = None):
    global _db_instance
    if _db_instance:
        _db_instance.close()
    _db_instance = create_connection(db_config) if db_config else None


def is_oracle() -> bool:
    return get_db().get_db_type() == "oracle"


def is_postgres() -> bool:
    return get_db().get_db_type() == "postgres"


# ── 스키마 조회 유틸 ──────────────────────────────────────────────

def get_all_tables(schema: str | None = None) -> List[Dict[str, Any]]:
    db = get_db()
    if is_oracle():
        if schema:
            q = """
                SELECT table_name, 'BASE TABLE' as table_type,
                    (SELECT COUNT(*) FROM all_tab_columns c WHERE c.table_name = t.table_name AND c.owner = t.owner) as column_count
                FROM all_tables t WHERE owner = UPPER(:1) ORDER BY table_name
            """
            return db.execute_query(q, (schema,))
        else:
            q = """
                SELECT table_name, 'BASE TABLE' as table_type,
                    (SELECT COUNT(*) FROM user_tab_columns c WHERE c.table_name = t.table_name) as column_count
                FROM user_tables t ORDER BY table_name
            """
            return db.execute_query(q)
    else:
        # PostgreSQL: 스키마 지정이 없으면 시스템 스키마 제외한 전체 테이블 조회
        if schema:
            q = """
                SELECT table_name, table_type, table_schema,
                    (SELECT count(*) FROM information_schema.columns c
                     WHERE c.table_name = t.table_name AND c.table_schema = t.table_schema) as column_count
                FROM information_schema.tables t WHERE table_schema = %s ORDER BY table_name
            """
            return db.execute_query(q, (schema,))
        else:
            q = """
                SELECT table_name, table_type, table_schema,
                    (SELECT count(*) FROM information_schema.columns c
                     WHERE c.table_name = t.table_name AND c.table_schema = t.table_schema) as column_count
                FROM information_schema.tables t
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """
            return db.execute_query(q)

def _find_table_schema(table_name: str) -> str | None:
    """PostgreSQL에서 테이블이 속한 스키마를 자동 감지."""
    db = get_db()
    q = """
        SELECT table_schema FROM information_schema.tables
        WHERE table_name = %s AND table_schema NOT IN ('pg_catalog', 'information_schema')
        LIMIT 1
    """
    rows = db.execute_query(q, (table_name,))
    if not rows:
        # 대소문자 무시 검색
        q2 = """
            SELECT table_schema, table_name FROM information_schema.tables
            WHERE LOWER(table_name) = LOWER(%s) AND table_schema NOT IN ('pg_catalog', 'information_schema')
            LIMIT 1
        """
        rows = db.execute_query(q2, (table_name,))
    return rows[0]["table_schema"] if rows else None


def get_table_schema(table_name: str, schema: str | None = None) -> Dict[str, Any]:
    db = get_db()
    if is_oracle():
        tname = table_name.upper()
        if schema:
            col_q = """
                SELECT column_name, data_type,
                    data_length as character_maximum_length,
                    data_precision as numeric_precision,
                    data_scale as numeric_scale,
                    CASE WHEN nullable='Y' THEN 'YES' ELSE 'NO' END as is_nullable,
                    data_default as column_default, column_id as ordinal_position
                FROM all_tab_columns WHERE owner=UPPER(:1) AND table_name=:2 ORDER BY column_id
            """
            columns = db.execute_query(col_q, (schema, tname))
        else:
            col_q = """
                SELECT column_name, data_type,
                    data_length as character_maximum_length,
                    data_precision as numeric_precision,
                    data_scale as numeric_scale,
                    CASE WHEN nullable='Y' THEN 'YES' ELSE 'NO' END as is_nullable,
                    data_default as column_default, column_id as ordinal_position
                FROM user_tab_columns WHERE table_name=:1 ORDER BY column_id
            """
            columns = db.execute_query(col_q, (tname,))

        # PK
        if schema:
            pk_q = """
                SELECT cc.column_name FROM all_constraints c
                JOIN all_cons_columns cc ON c.constraint_name=cc.constraint_name AND c.owner=cc.owner
                WHERE c.constraint_type='P' AND c.owner=UPPER(:1) AND c.table_name=:2 ORDER BY cc.position
            """
            pks = db.execute_query(pk_q, (schema, tname))
        else:
            pk_q = """
                SELECT cc.column_name FROM user_constraints c
                JOIN user_cons_columns cc ON c.constraint_name=cc.constraint_name
                WHERE c.constraint_type='P' AND c.table_name=:1 ORDER BY cc.position
            """
            pks = db.execute_query(pk_q, (tname,))

        return {
            "table_name": table_name,
            "schema": schema or "current_user",
            "columns": columns,
            "primary_keys": [pk["column_name"] for pk in pks],
        }
    else:
        # PostgreSQL: 스키마 자동 감지
        if not schema:
            schema = _find_table_schema(table_name)
        if not schema:
            return {"table_name": table_name, "schema": None, "columns": [], "primary_keys": []}

        col_q = """
            SELECT column_name, data_type, character_maximum_length,
                numeric_precision, numeric_scale, is_nullable,
                column_default, ordinal_position
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position
        """
        columns = db.execute_query(col_q, (schema, table_name))

        pk_q = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
            WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema=%s AND tc.table_name=%s
        """
        pks = db.execute_query(pk_q, (schema, table_name))

        return {
            "table_name": table_name,
            "schema": schema,
            "columns": columns,
            "primary_keys": [pk["column_name"] for pk in pks],
        }


def execute_select_query(query: str, limit: int = 100) -> Dict[str, Any]:
    """SELECT 쿼리만 실행 (안전)."""
    db = get_db()
    q_stripped = query.strip().upper()
    if not q_stripped.startswith("SELECT"):
        return {"success": False, "error": "SELECT 쿼리만 허용됩니다."}

    # 행 제한
    q_upper = query.upper()
    if is_oracle():
        if "FETCH FIRST" not in q_upper and "ROWNUM" not in q_upper:
            query = f"{query.rstrip(';')} FETCH FIRST {limit} ROWS ONLY"
    else:
        if "LIMIT" not in q_upper:
            query = f"{query.rstrip(';')} LIMIT {limit}"

    try:
        start = time.time()
        results = db.execute_query(query)
        elapsed = time.time() - start
        return {
            "success": True,
            "rows": results,
            "row_count": len(results),
            "execution_time_ms": round(elapsed * 1000, 2),
            "query": query,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "query": query}


def extract_table_names_from_text(text: str) -> List[str]:
    """답변 텍스트에서 테이블명 후보를 추출 (대문자+언더스코어 패턴)."""
    # 1) 일반적 DB 테이블명 패턴: 대문자+숫자+언더스코어, 2단어 이상
    pattern = r'\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b'
    candidates = set(re.findall(pattern, text))
    # 2) SQL FROM/JOIN 뒤의 테이블명
    sql_patterns = [
        r'\bFROM\s+([a-zA-Z_]\w*)',
        r'\bJOIN\s+([a-zA-Z_]\w*)',
    ]
    for p in sql_patterns:
        for m in re.findall(p, text, re.IGNORECASE):
            if m.upper() not in ("SELECT", "WHERE", "AND", "OR", "ON", "AS", "SET", "DUAL"):
                candidates.add(m.upper())
    # 필터: 너무 짧거나 일반 단어 제외
    stop = {"DR_NUMBER", "API_KEY", "BASE_URL", "HTTP_", "UTF_8", "ISO_", "THIS_IS"}
    return [t for t in sorted(candidates) if len(t) >= 4 and t not in stop]
