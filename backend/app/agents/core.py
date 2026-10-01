"""Agent 系统核心：继承 AgentBase，用 langchain create_agent + tools。

关键设计：
- 继承 AgentBase（from app.chains.agents.base import AgentBase）
- 覆盖 create_agent 方法，传入 tools 参数给 langchain.agents.create_agent
- 无 tools 时走父类原路径 super().create_agent(...)
- _to_structured_tool 里加防御 if ctx is None: raise RuntimeError
- 双命名兼容：tool_map 同时注册 snake_case 名和 Pydantic 类名
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.chains.agents.base import AgentBase

from app.agents.tools.base import Tool

logger = logging.getLogger(__name__)

_USER_INPUT_TEMPLATE = PromptTemplate.from_template("{user_input}")


class AgentContext:
    """Agent 执行上下文，在工具执行时传递。"""

    def __init__(self, project_id: str, chapter_id: str | None = None):
        self.project_id = project_id
        self.chapter_id = chapter_id
        self.tool_results: list[dict] = []
        self.token_usage: int = 0


class AgentResult(BaseModel):
    """Agent 执行结果。"""

    status: str = "completed"  # completed | error
    output: str = ""
    next_action: str | None = None  # Director 专用
    tool_calls_made: list[dict] = []


class SpecialistAgent(AgentBase[AgentResult]):
    """
    专业 Agent：覆盖 create_agent 传入 tools，
    用 langchain.agents.create_agent 处理 tool-calling loop。
    不手动写 loop。
    """

    agent_name: str = "specialist"
    agent_description: str = ""

    def __init__(
        self,
        model: Any,
        *,
        tools: list[Tool] | None = None,
        ctx: AgentContext | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, **kwargs)
        self._tools: list[Tool] = tools or []
        self._ctx: AgentContext | None = ctx
        self.tool_map: dict[str, Tool] = {}
        self._build_tool_map()

    def _build_tool_map(self) -> None:
        """构建 tool_map，双命名兼容：同时注册 snake_case 名和 Pydantic 类名。"""
        for tool in self._tools:
            self.tool_map[tool.name] = tool
            class_name = tool.input_model.__name__
            if class_name not in self.tool_map:
                self.tool_map[class_name] = tool

    @property
    def prompt_template(self) -> PromptTemplate:
        return _USER_INPUT_TEMPLATE

    @property
    def output_model(self) -> type[AgentResult]:
        return AgentResult

    def create_agent(self, *, structured_output: type[BaseModel] | None = None) -> Runnable:
        """
        覆盖父类：有 tools 时传入 tools，无 tools 时走父类原路径。
        """
        if not self._tools:
            return super().create_agent(structured_output=structured_output)

        from langchain.agents import create_agent as _lc_create_agent

        lc_tools = [self._to_structured_tool(t) for t in self._tools]
        kwargs = dict(self._agent_kwargs)
        if structured_output is not None:
            kwargs["response_format"] = structured_output

        agent = _lc_create_agent(
            model=self._model,
            system_prompt=self.system_prompt or "",
            tools=lc_tools,
            **kwargs,
        )
        return RunnableLambda(lambda inputs: self._as_messages_input(**inputs)) | cast(Runnable, agent)

    def _to_structured_tool(self, tool: Tool) -> StructuredTool:
        """把自定义 Tool 转成 LangChain StructuredTool。"""
        ctx = self._ctx
        if ctx is None:
            raise RuntimeError("AgentContext not set")

        async def _arun(**kwargs: Any) -> str:
            result = await tool.execute(ctx=ctx, **kwargs)
            return json.dumps(result, ensure_ascii=False, default=str)

        def _run(**kwargs: Any) -> str:
            import asyncio

            return asyncio.get_event_loop().run_until_complete(_arun(**kwargs))

        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.input_model,
            func=_run,
            coroutine=_arun,
        )

    async def run(self, ctx: AgentContext, user_input: str) -> AgentResult:
        """调用 create_agent 产生的 Runnable，传入用户消息。"""
        self._ctx = ctx  # 更新上下文
        agent = self.create_agent(structured_output=AgentResult)
        result = await agent.ainvoke({"user_input": user_input})

        # 解析结果
        if isinstance(result, dict) and "messages" in result:
            last_msg = result["messages"][-1]
            content = getattr(last_msg, "content", str(last_msg))

            if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                ctx.tool_results.extend(
                    [{"tool": tc["name"], "args": tc["args"]} for tc in last_msg.tool_calls]
                )

            structured = getattr(last_msg, "structured_response", None)
            if structured and isinstance(structured, AgentResult):
                structured.tool_calls_made = ctx.tool_results[-10:]
                return structured

            return AgentResult(output=content, tool_calls_made=ctx.tool_results[-10:])

        return AgentResult(output=str(result))
