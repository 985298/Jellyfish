"""剧本分镜 Agent：ScriptDividerAgent"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase, _extract_json_from_text
from app.schemas.skills.script_processing import ScriptDivisionResult

_SCRIPT_DIVIDER_SYSTEM_PROMPT = """\
你是"剧本分镜师"。将完整剧本分割为多个镜头，每个镜头必须包含完整的 Agnes Video 2.5 三段式提示词。

## 输入
- 剧本文本
- 已生成的资产清单（角色名 + 外貌描述 + 参考图编号、场景名 + 环境描述 + 参考图编号）

## 输出要求
每个镜头的 description 字段必须是以下三段式结构：

【参考素材说明】
@图片N 作为人物参考，锁定[角色名]的[外貌特征：面部、发型、服装、体型]。
@图片N 作为场景参考，锁定[场景名]的[环境特征：光线、色调、空间]。
（无素材时跳过此段）

【核心创意】
[时长]秒，16:9横版。[主体(@图片N)]在[场景(@图片N)]中[做什么]。[风格]，[运镜方式]。

【画面过程描述】
0-X秒：[景别]，[运镜]，[角色动作]，台词："[原文]"。音效：[环境音/动作音]。
反向：不要[不想要的元素]。
X-Y秒：[同上格式]
...
不要额外添加背景音乐。（或指定需要的音乐）

## 10 条写作原则（必须遵循）
1. 具体 > 抽象——写看得见的画面，不写比喻
2. 台词 = 原文——必须写出具体台词内容，和镜头时长对齐
3. 素材 = 标注用途——每个参考图写清角色和锁定特征
4. 反向 = 必须写——不想要的元素必须明确排除
5. 景别 = 切镜锚点——每次切镜写明目标景别和主体
6. 一镜到底 ≠ 多分镜——选一种不混用
7. 文字 = 原文——画面中的文字/Logo 写出原文
8. 跨 shot 台词 = 明确标注——写清哪句台词跨了哪些 shot
9. 画外音 = 写清身份——区分画内角色和画外说话人
10. 音频复刻 = 附歌词——对人声保持要求高时附完整歌词

## JSON 转义要求（关键！）
description 字段中包含大量文本，必须正确转义：
- 换行用 \\n（不要直接换行）
- 台词用中文引号「」或''（不要用英文双引号"）
- 所有双引号 " 必须写成 \\"
- 反斜线 \\ 必须写成 \\\\

## 其他字段
- shot_name：镜头标题（一句话）
- script_excerpt：镜头对应的剧本摘录原文
- duration：时长（全景5s、对话6-8s、冲突动作8-12s，最大12s）
- camera_shot / angle / movement：景别/角度/运镜（元数据，用于 UI 展示）
- character_names：本镜出现的角色名称列表
- scene_name：本镜场景名称

只输出 JSON，符合 ScriptDivisionResult 结构。
"""

SCRIPT_DIVIDER_PROMPT = PromptTemplate(
    input_variables=["script_text", "asset_list"],
    template="## 输入脚本\n{script_text}\n\n## 资产清单\n{asset_list}\n\n## 输出\n",
)


class ScriptDividerAgent(AgentBase[ScriptDivisionResult]):
    """剧本自动分镜：输入完整剧本文本，输出分镜列表。"""

    enable_thinking: bool = False

    @property
    def system_prompt(self) -> str:
        return _SCRIPT_DIVIDER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return SCRIPT_DIVIDER_PROMPT

    @property
    def output_model(self) -> type[ScriptDivisionResult]:
        return ScriptDivisionResult

    def format_output(self, raw: str) -> ScriptDivisionResult:
        """
        更强的兜底解析：
        LLM 可能输出：
        - 正常结构：{shots:[...], total_shots:N}
        - 包裹结构：{"ScriptDivisionResult": {...}}
        - 直接列表：[{...}, {...}]（视为 shots）
        """

        json_str = _extract_json_from_text(raw)
        try:
            data: Any = json.loads(json_str)
        except json.JSONDecodeError:
            # LLM 可能输出未转义的控制字符（换行/引号），strict=False 允许
            try:
                data = json.loads(json_str, strict=False)
            except json.JSONDecodeError:
                # 最后尝试：移除 markdown 代码块后重试
                cleaned = json_str.replace("```json", "").replace("```", "").strip()
                data = json.loads(cleaned, strict=False)

        if isinstance(data, list):
            data = {"shots": data}
        elif isinstance(data, dict) and "ScriptDivisionResult" in data:
            inner = data.get("ScriptDivisionResult")
            if isinstance(inner, list):
                data = {"shots": inner}
            elif isinstance(inner, dict):
                data = inner
            else:
                data = {"shots": []}

        if isinstance(data, dict):
            data = self._normalize(data)

        return self.output_model.model_validate(data)  # type: ignore[arg-type]

    def divide_script(self, *, script_text: str, asset_list: str = "") -> ScriptDivisionResult:
        return self.extract(script_text=script_text, asset_list=asset_list)

    async def adivide_script(self, *, script_text: str, asset_list: str = "") -> ScriptDivisionResult:
        return await self.aextract(script_text=script_text, asset_list=asset_list)

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        """规范化脚本分割结果。"""
        data = dict(data)

        # 兼容：LLM 可能输出 {"ScriptDivisionResult": {...}} 或 {"ScriptDivisionResult": [...]}
        if "ScriptDivisionResult" in data:
            inner = data.get("ScriptDivisionResult")
            if isinstance(inner, list):
                data = {"shots": inner}
            elif isinstance(inner, dict):
                data = dict(inner)
            else:
                data = {"shots": []}

        if "shots" in data and isinstance(data["shots"], list):
            shots = []
            for idx, shot in enumerate(data["shots"]):
                shot_dict: dict[str, Any] = (
                    dict(shot) if isinstance(shot, dict) else {"script_excerpt": str(shot), "shot_name": ""}
                )
                if "index" not in shot_dict:
                    shot_dict["index"] = idx + 1
                # 兼容：LLM 可能用 shot_id 代替 index
                if "shot_id" in shot_dict and "index" not in shot_dict:
                    shot_dict["index"] = int(shot_dict.pop("shot_id"))
                elif "shot_id" in shot_dict:
                    shot_dict.pop("shot_id")
                # 兼容：LLM 可能不输出 start_line/end_line
                shot_dict.setdefault("start_line", idx + 1)
                shot_dict.setdefault("end_line", idx + 1)
                # 兼容：LLM 可能用 title/shot_title 代替 shot_name
                if "shot_name" not in shot_dict:
                    if "title" in shot_dict:
                        shot_dict["shot_name"] = str(shot_dict.pop("title"))
                    elif "shot_title" in shot_dict:
                        shot_dict["shot_name"] = str(shot_dict.pop("shot_title"))
                shot_dict.setdefault("shot_name", "")
                shot_dict.pop("character_names_in_text", None)
                shot_dict.pop("character_ids", None)
                # 丢弃 LLM 可能多输出的字段（如画面过程描述、核心创意等中文字段名）
                _ALLOWED = {"index", "start_line", "end_line", "script_excerpt", "shot_name",
                            "time_of_day", "duration", "camera_shot", "angle", "movement",
                            "description", "character_names", "scene_name"}
                shot_dict = {k: v for k, v in shot_dict.items() if k in _ALLOWED}
                shots.append(shot_dict)
            data["shots"] = shots

        if "total_shots" not in data and "shots" in data:
            data["total_shots"] = len(data["shots"])

        return data

