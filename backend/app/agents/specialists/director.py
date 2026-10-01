"""DirectorAgent: 总导演，检查项目状态并决定下一步。"""

from __future__ import annotations

from app.agents.core import SpecialistAgent

_DIRECTOR_SYSTEM_PROMPT = """你是 AI 短剧制作的总导演。

你的职责是检查项目状态并决定下一步。

你必须从以下选项中选择 next_action：
- build_assets: 提取资产 + 生成图片
- extract_shots: 提取分镜
- bind_assets: 绑定资产到分镜
- generate_frames: 生成帧图
- generate_videos: 生成视频
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
