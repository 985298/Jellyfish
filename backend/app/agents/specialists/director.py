"""DirectorAgent: 总导演，检查项目状态并决定下一步。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_DIRECTOR_SYSTEM_PROMPT = """你是 AI 短剧制作的总导演。

你的职责是检查项目状态并决定下一步。

你必须从以下选项中选择 next_action：
- extract_assets: 提取资产（角色/场景/道具入库）
- generate_asset_refs: 生成角色/场景参考图（锁定外貌）
- divide_shots: 分镜（输出 Agnes 三段式提示词）
- generate_keyframes: 生成关键帧（img2img 引用参考图）
- generate_videos: 生成视频（first_frame 从关键帧起播）
- compose_film: 合成成片（配音/字幕/拼接）
- completed: 全部完成

使用 check_asset_status 检查资产状态，使用 query_shots 查看分镜进度。
不要自己执行具体操作，只做判断和指派。
"""


class DirectorAgent(SpecialistAgent):
    """总导演 Agent：检查状态、决定 next_action。"""

    agent_name: str = "director"
    agent_description: str = "AI 短剧制作总导演，检查状态并决定下一步"

    @property
    def system_prompt(self) -> str:
        return _DIRECTOR_SYSTEM_PROMPT
