"""LLM Client — Dify API 래퍼.

Dify chat-messages 엔드포인트를 사용하여 LLM 호출.
"""
from __future__ import annotations
import threading
from typing import Any, Callable

import httpx


class CancelledError(Exception):
    """요청이 사용자에 의해 취소됨."""
    pass


class LLMClient:
    """Dify API 기반 LLM 클라이언트."""

    def __init__(self, api_key: str, base_url: str, timeout: float = 300):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, message: str, user: str = "ia-chatbot", cancel_check: Callable[[], bool] | None = None) -> str:
        """Dify chat-messages로 메시지 전송 후 응답 텍스트 반환.

        cancel_check: 호출 시 True를 반환하면 CancelledError를 발생시킨다.
        HTTP 요청을 별도 스레드에서 실행하여 cancel_check를 0.5초 간격으로 폴링한다.
        """
        if cancel_check and cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        # surrogate 문자 제거 (DOCX 파싱 시 깨진 유니코드 방지)
        message = message.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
        url = f"{self.base_url}/chat-messages"
        payload = {
            "inputs": {},
            "query": message,
            "response_mode": "blocking",
            "user": user,
            "temperature": 0,
        }

        if not cancel_check:
            # cancel_check가 없으면 기존 방식으로 바로 호출
            with httpx.Client(timeout=self.timeout, verify=False) as client:
                resp = client.post(url, headers=self.headers, json=payload)
                resp.raise_for_status()
            return resp.json().get("answer", "").strip()

        # cancel_check가 있으면 별도 스레드에서 HTTP 요청 실행
        result_holder: list[dict | None] = [None]
        error_holder: list[Exception | None] = [None]
        done_event = threading.Event()

        def _do_request():
            try:
                with httpx.Client(timeout=self.timeout, verify=False) as client:
                    resp = client.post(url, headers=self.headers, json=payload)
                    resp.raise_for_status()
                    result_holder[0] = resp.json()
            except Exception as e:
                error_holder[0] = e
            finally:
                done_event.set()

        t = threading.Thread(target=_do_request, daemon=True)
        t.start()

        # 0.5초 간격으로 완료 또는 취소 확인
        while not done_event.wait(timeout=0.5):
            if cancel_check():
                print("  🛑 LLM 요청 취소됨 (사용자 중지)")
                raise CancelledError("사용자가 요청을 취소했습니다.")

        # 스레드 완료 후 결과 확인
        if error_holder[0]:
            raise error_holder[0]

        if cancel_check():
            raise CancelledError("사용자가 요청을 취소했습니다.")

        data = result_holder[0]
        return data.get("answer", "").strip()
