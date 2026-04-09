"""DB Agent — LLM Tool Calling 기반 DB 조회.

D:\MCP\agent\agent.py 패턴을 ia-chatbot-v2에 맞게 적용.
Dify API를 사용하여 LLM이 tool을 선택·호출하고 결과를 자연어로 정리.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from src.storage.db_client import (
    get_all_tables,
    get_table_schema,
    execute_select_query,
    extract_table_names_from_text,
)


# ── Tool 정의 (OpenAI function calling 형식) ────────────────────

DB_TOOLS: Dict[str, Dict[str, Any]] = {
    "get_all_tables": {
        "description": "현재 연결된 데이터베이스의 모든 테이블 목록을 조회합니다. 파라미터 없이 호출하세요.",
        "parameters": {"type": "object", "properties": {}},
        "function": get_all_tables,
    },
    "get_table_schema": {
        "description": "테이블의 상세 스키마(컬럼, 타입, PK, nullable 등)를 조회합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "테이블명"},
            },
            "required": ["table_name"],
        },
        "function": get_table_schema,
    },
    "execute_query": {
        "description": "SELECT 쿼리를 실행하여 결과를 반환합니다. SELECT만 허용됩니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "실행할 SQL SELECT 쿼리"},
                "limit": {"type": "integer", "description": "최대 행 수 (기본 50)", "default": 50},
            },
            "required": ["query"],
        },
        "function": execute_select_query,
    },
    "extract_tables_from_text": {
        "description": "텍스트에서 테이블명 후보를 추출합니다.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "테이블명을 추출할 텍스트"},
            },
            "required": ["text"],
        },
        "function": extract_table_names_from_text,
    },
}


# ── 시스템 프롬프트 ─────────────────────────────────────────────

DB_SYSTEM_PROMPT = """당신은 데이터베이스 조회 어시스턴트입니다. PostgreSQL과 Oracle을 지원합니다.
모든 응답은 반드시 한글로 작성해주세요.

사용 가능한 도구:
- get_all_tables: 전체 테이블 목록 조회
- get_table_schema(table_name): 테이블 스키마 조회 (컬럼, 타입, PK)
- execute_query(query, limit): SELECT 쿼리 실행 (읽기 전용)
- extract_tables_from_text(text): 텍스트에서 테이블명 추출

★★★ 지침 ★★★:
사용자가 요청하면 질문하지 말고 즉시 도구를 실행하세요:
- "테이블 목록/조회" → get_all_tables() 호출
- "xxx 테이블 스키마/구조" → get_table_schema(table_name="xxx") 호출
- "xxx 데이터 조회" → execute_query(query="SELECT * FROM xxx", limit=10) 호출
- SQL 쿼리 직접 입력 → execute_query(query="...") 호출

★★★ 최소 정보 원칙 ★★★:
- 요청한 것만 조회하세요. 추가 도구 호출 하지 마세요.
- get_all_tables() 후에 자동으로 get_table_schema()를 추가 호출하지 마세요.
- 같은 도구를 중복 호출하지 마세요.

★★★ 절대 금지 ★★★:
- 스키마 이름을 물어보지 마세요. 기본값이 사용됩니다.
- 추가 정보를 요청하지 마세요. 바로 도구를 호출하세요.
"""


# ── DB Agent ────────────────────────────────────────────────────

class DBAgent:
    """Dify API + Tool Calling 기반 DB 조회 에이전트."""

    MAX_TOOL_ROUNDS = 10

    def __init__(self, api_key: str, base_url: str, timeout: float = 120):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.conversation_id: Optional[str] = None

    # ── public ──────────────────────────────────────────────────

    def query(self, user_message: str) -> Dict[str, Any]:
        """사용자 메시지 → LLM tool calling → 최종 답변 반환.

        Returns:
            {
                "success": bool,
                "answer": str,          # LLM 자연어 답변
                "tools_used": [...],    # 사용된 tool 이름 리스트
                "tool_results": [...],  # 각 tool 호출 결과
            }
        """
        self.conversation_id = None  # 매 요청마다 새 대화

        tools_used: List[str] = []
        tool_results: List[Dict[str, Any]] = []

        # 1) tool 설명을 포함한 query 구성
        tools_desc = self._build_tools_description()
        full_query = tools_desc + "\n[User Request]\n" + user_message

        print(f"\n🤖 DB Agent: LLM 호출 (메시지: {user_message[:60]})")

        # 2) 첫 LLM 호출
        response = self._call_dify(full_query)
        if not response.get("success"):
            return {"success": False, "answer": response.get("error", "LLM 호출 실패"), "tools_used": [], "tool_results": []}

        answer = response["answer"]

        # 3) Tool calling 루프
        for round_num in range(self.MAX_TOOL_ROUNDS):
            tool_calls = self._parse_tool_calls(answer)
            if not tool_calls:
                break  # LLM이 더 이상 tool 호출 안 함

            print(f"  🔧 Round {round_num + 1}: {len(tool_calls)}개 tool 호출")

            # tool 실행
            results_text = ""
            for tc in tool_calls:
                name = tc["name"]
                args = tc["arguments"]

                if name not in tools_used:
                    tools_used.append(name)

                print(f"    → {name}({json.dumps(args, ensure_ascii=False)[:80]})")

                result = self._execute_tool(name, args)
                tool_results.append({"tool": name, "arguments": args, "result": result})

                # 결과를 텍스트로 변환 (LLM에 전달)
                result_json = json.dumps(result, ensure_ascii=False, default=str)
                # 너무 길면 잘라서 전달 (토큰 절약)
                if len(result_json) > 8000:
                    result_json = result_json[:8000] + "\n... (truncated)"
                results_text += f"\nTool Result ({name}):\n{result_json}\n"

            # tool 결과를 LLM에 전달
            followup = f"Based on the tool results below, provide a clear answer to the user:\n{results_text}"
            response = self._call_dify(followup)
            if not response.get("success"):
                # tool 결과라도 반환
                return {
                    "success": True,
                    "answer": f"도구 실행은 완료했지만 LLM 응답 생성에 실패했습니다.\n사용된 도구: {', '.join(tools_used)}",
                    "tools_used": tools_used,
                    "tool_results": tool_results,
                }
            answer = response["answer"]

        # CALL: 패턴 제거 (최종 답변에 남아있을 수 있음)
        answer = self._clean_answer(answer)

        print(f"  ✅ 완료. tools_used={tools_used}")

        return {
            "success": True,
            "answer": answer,
            "tools_used": tools_used,
            "tool_results": tool_results,
        }

    # ── private: Dify API ───────────────────────────────────────

    def _call_dify(self, query: str) -> Dict[str, Any]:
        """Dify chat-messages 호출."""
        url = f"{self.base_url}/chat-messages"
        payload: Dict[str, Any] = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": "ia-db-agent",
        }
        if self.conversation_id:
            payload["conversation_id"] = self.conversation_id

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
            data = resp.json()

            # conversation_id 보존 (멀티턴)
            if "conversation_id" in data:
                self.conversation_id = data["conversation_id"]

            return {"success": True, "answer": data.get("answer", "")}

        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── private: Tool description ───────────────────────────────

    def _build_tools_description(self) -> str:
        """Tool 목록을 LLM이 이해할 수 있는 텍스트로 변환."""
        lines = ['\n[Functions you can call using format: CALL: function_name({"arg": "value"})]']
        for name, tool in DB_TOOLS.items():
            params = tool["parameters"].get("properties", {})
            param_str = ", ".join(params.keys()) if params else ""
            lines.append(f"- {name}({param_str}): {tool['description']}")
        return "\n".join(lines)

    # ── private: Tool call parsing ──────────────────────────────

    def _parse_tool_calls(self, text: str) -> List[Dict[str, Any]]:
        """LLM 응답에서 CALL: tool_name({...}) 패턴 추출."""
        calls = []
        # CALL: tool_name({"arg": "value"}) 또는 CALL: tool_name({})
        pattern = r'CALL:\s*(\w+)\s*\((\{[^}]*\})\)'
        for match in re.finditer(pattern, text):
            name = match.group(1)
            args_str = match.group(2)
            if name in DB_TOOLS:
                try:
                    args = json.loads(args_str)
                except json.JSONDecodeError:
                    args = {}
                calls.append({"name": name, "arguments": args})
        return calls

    # ── private: Tool execution ─────────────────────────────────

    def _execute_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """등록된 tool 실행."""
        if name not in DB_TOOLS:
            return {"success": False, "error": f"Unknown tool: {name}"}
        func = DB_TOOLS[name]["function"]
        try:
            return func(**arguments)
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── private: 답변 정리 ──────────────────────────────────────

    def _clean_answer(self, text: str) -> str:
        """최종 답변에서 CALL: 패턴 제거."""
        return re.sub(r'CALL:\s*\w+\s*\(\{[^}]*\}\)', '', text).strip()


# ── Factory ─────────────────────────────────────────────────────

_db_agent: Optional[DBAgent] = None


def get_db_agent(api_key: str, base_url: str) -> DBAgent:
    """싱글턴 DBAgent 인스턴스 반환."""
    global _db_agent
    if _db_agent is None:
        _db_agent = DBAgent(api_key=api_key, base_url=base_url)
    return _db_agent


def reset_db_agent():
    """설정 변경 시 에이전트 리셋."""
    global _db_agent
    _db_agent = None
