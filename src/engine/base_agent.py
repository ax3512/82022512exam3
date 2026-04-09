"""Base Agent 인터페이스 — 향후 DB/업무지식/AP소스 Agent 확장용."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from abc import ABC, abstractmethod


@dataclass
class AgentResult:
    """Agent 분석 결과."""
    agent_name: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)  # [{title, content, sources}]
    similar_drs: list[dict[str, Any]] = field(default_factory=list)  # [{dr_number, title, score, summary}]
    warnings: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """모든 Agent의 기본 인터페이스."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def analyze(self, requirement: str, **kwargs) -> AgentResult:
        ...
