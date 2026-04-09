"""Orchestrator — Agent 관리 및 결과 병합.

V4에서는 IAAgent만 사용하지만, 향후 DB Agent, 업무지식 Agent 등
추가 Agent를 등록하여 병렬/순차 실행할 수 있는 구조.
"""
from __future__ import annotations
from typing import Any, Callable

from src.engine.base_agent import BaseAgent, AgentResult


class Orchestrator:
    """Agent 오케스트레이터 — 등록된 Agent들을 실행하고 결과를 병합."""

    def __init__(self, agents: list[BaseAgent] | None = None):
        self._agents: list[BaseAgent] = agents or []

    def register(self, agent: BaseAgent) -> None:
        """Agent를 등록한다."""
        self._agents.append(agent)

    @property
    def agent_names(self) -> list[str]:
        """등록된 Agent 이름 목록."""
        return [a.name for a in self._agents]

    def run(
        self,
        requirement: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
        **kwargs,
    ) -> OrchestratorResult:
        """등록된 모든 Agent의 analyze()를 호출하고 결과를 병합.

        Args:
            requirement: 사용자 요구사항 텍스트.
            cancel_check: 취소 확인 콜백.
            **kwargs: 각 Agent에 전달할 추가 파라미터.

        Returns:
            OrchestratorResult: 병합된 분석 결과.
        """
        agent_results: list[AgentResult] = []

        for agent in self._agents:
            print(f"  [Orchestrator] {agent.name} 실행 중...")
            try:
                result = agent.analyze(
                    requirement,
                    cancel_check=cancel_check,
                    **kwargs,
                )
                agent_results.append(result)
                print(f"  [Orchestrator] {agent.name} 완료 — "
                      f"findings={len(result.findings)}, "
                      f"similar_drs={len(result.similar_drs)}, "
                      f"warnings={len(result.warnings)}")
            except Exception as e:
                print(f"  [Orchestrator] {agent.name} 오류: {e}")
                agent_results.append(AgentResult(
                    agent_name=agent.name,
                    warnings=[f"Agent 실행 오류: {e}"],
                ))

        return OrchestratorResult.merge(agent_results)


class OrchestratorResult:
    """Orchestrator 실행 결과 — 여러 Agent 결과를 병합."""

    def __init__(
        self,
        findings: list[dict[str, Any]],
        similar_drs: list[dict[str, Any]],
        warnings: list[str],
        agent_results: list[AgentResult],
    ):
        self.findings = findings
        self.similar_drs = similar_drs
        self.warnings = warnings
        self.agent_results = agent_results

    @classmethod
    def merge(cls, results: list[AgentResult]) -> OrchestratorResult:
        """여러 AgentResult를 하나의 OrchestratorResult로 병합."""
        all_findings: list[dict[str, Any]] = []
        all_similar_drs: list[dict[str, Any]] = []
        all_warnings: list[str] = []
        seen_drs: set[str] = set()

        for r in results:
            # findings: agent_name 태깅하여 병합
            for f in r.findings:
                f_copy = dict(f)
                f_copy["agent"] = r.agent_name
                all_findings.append(f_copy)

            # similar_drs: DR번호 중복 제거 (높은 score 우선)
            for dr in r.similar_drs:
                dr_num = dr.get("dr_number", "")
                if dr_num not in seen_drs:
                    seen_drs.add(dr_num)
                    dr_copy = dict(dr)
                    dr_copy["agent"] = r.agent_name
                    all_similar_drs.append(dr_copy)

            # warnings: agent_name 접두사 추가
            for w in r.warnings:
                all_warnings.append(f"[{r.agent_name}] {w}")

        # similar_drs를 score 내림차순 정렬
        all_similar_drs.sort(key=lambda x: x.get("score", 0), reverse=True)

        return cls(
            findings=all_findings,
            similar_drs=all_similar_drs,
            warnings=all_warnings,
            agent_results=results,
        )

    def to_dict(self) -> dict[str, Any]:
        """직렬화용 dict 변환."""
        return {
            "findings": self.findings,
            "similar_drs": self.similar_drs,
            "warnings": self.warnings,
            "agents_used": [r.agent_name for r in self.agent_results],
        }
