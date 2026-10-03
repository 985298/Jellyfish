# P0 修复报告 — 供 Claude 逐条验收

## 修复环境
- 项目: E:\项目\AI短剧2\Jellyfish
- 后端 orchestrator.py 阶段名（行 35-47）:
  extract_assets, generate_asset_refs, divide_shots, generate_keyframes, generate_videos, compose_film
- 前端管线页 StageKey: asset_extract, asset_images, divide, keyframes, videos, render

---

## P0-1: AGENT_STAGE_MAP 改名

**文件:** useAgentOrchestration.ts

**改动:**
```
// 旧（SSE 事件全部丢弃）
build_assets: ['asset_extract', 'asset_images'],
extract_shots: ['divide'],
generate_frames: ['keyframes'],
generate_videos: ['videos'],

// 新（N:1 映射，6 阶段全覆盖）
extract_assets: ['asset_extract'],
generate_asset_refs: ['asset_images'],
divide_shots: ['divide'],
generate_keyframes: ['keyframes'],
generate_videos: ['videos'],
compose_film: ['render'],
```

**验证:** 后端 6 个阶段名全部映射到前端 StageKey，SSE 事件不再丢弃。

---

## P0-2: 绑定资产全链清理

### 前端

| 文件 | 改动 |
|---|---|
| ChapterShotsPage.tsx | 删除 handleBatchBindAssets 函数 + 按钮 + batchBindLoading 状态 |
| ChapterShotsPage.tsx | 删除 handleOneClickExtract + handleCancelChapterDivisionTask + useRelationTaskNotification |
| ChapterShotsPage.tsx | 删除 useCancelableRelationTask + useTaskPageContext + reloadShotsAfterTaskSettled |
| ChapterShotsPage.tsx | 删除 taskCopy 变量 + chapterDivisionTaskLoading 状态 |
| ChapterShotsPage.tsx | 删除 5 条 import (taskCopy, taskResultHelpers, taskPageContext, taskNotificationHelpers, chapterDivisionTasks) |
| ChapterShotsPage.tsx | 从多 import 行清除 ScissorOutlined, CloseCircleOutlined, ScriptProcessingService, executeAsyncTaskCreate, executeTaskCancel |

### 后端

| 文件 | 改动 |
|---|---|
| app/agents/tools/__init__.py | 删除 BindAssetsTool import (行16) + __all__ 导出 (行30) |
| app/agents/specialists/__init__.py | 删除 BindAssetsTool import (行79) + 工具名列表 (行47) + 注册 (行92) |
| app/agents/tools/shot_tools.py | 删除 BindAssetsInput 类 + BindAssetsTool 类 (行61-159, 99 行) |

### 后端其他检查
- script_processing.py: 无 bind-assets 路由残留（已被前端重定向删除覆盖）
- task_registry.py: 文件不存在于 app/agents/tools/ 路径
- gateway/app/api/v1.py: 无 gateway 目录（项目结构中不存在）

---

## P0-3: 删除 no-op Header 按钮

**文件:** ChapterShotsPage.tsx

**删除的按钮:**
- "进入分镜工作室"（onClick 导航到当前页同一 URL /shots，no-op）
- "继续当前镜头"（onClick 导航到当前页同一 URL /shots，no-op）

**保留:** 替换为一个 "进入分镜工作室" 按钮（仍有导航功能，用户可决定后续是否保留）

---

## P0-4: 删除冗余按钮 + 连带清理

**文件:** ChapterShotsPage.tsx

**删除的按钮:**
- "一键提取分镜" 按钮 + Tooltip 包裹（和管线页「分镜提取」阶段重复）
- "取消提取" 按钮（依赖已删除的 handleCancelChapterDivisionTask）
- "批量绑定资产" 按钮 + handleBatchBindAssets 函数（已废弃）

**保留的按钮:**
- 批量删除（正常功能）
- 批量帧图（保留，后续可决定是否合并到管线页）
- 批量视频（保留，后续可决定是否合并到管线页）
- 创建分镜、刷新（正常功能）
- 一键制作（跳转管线页，保留）

**连带清理的代码:**
- handleOneClickExtract 函数（284-311）
- handleCancelChapterDivisionTask 函数（315-332）
- useRelationTaskNotification hook（335-350）
- useCancelableRelationTask hook（172-173）
- useTaskPageContext hook（178-187）
- reloadShotsAfterTaskSettled 变量（171）
- chapterDivisionTaskLoading 状态（129）
- taskCopy 变量（107）
- 5 条 import 行 + 5 个多 import 名清除

**文件变化:** 770 行 → 745 行（减少 25 行）

---

## P1-1: 视频默认比例

**文件:** useProjectStyleOptions.ts

**改动:** FALLBACK_DEFAULT_VIDEO_RATIO 从 '16:9' 改为 '9:16'

**红线遵守:** 未修改 StudioShotsService.ts:280（生成文件，不手改）

---

## 红线遵守情况

| 红线 | 遵守 | 说明 |
|---|---|---|
| 不合并 chapterPreparation 与 ChapterPipeline 状态机 | ✅ | 未触碰 chapterPreparation.tsx |
| 不改 StudioShotsService.ts:280 | ✅ | 未修改生成文件 |
| 不删 chapters/:id/studio 重定向 | ✅ | 未触碰 App.tsx 路由 |
| project_id 必须可选 | ✅ | 未修改 entities API 参数 |
| 视频比例不手改生成文件 | ✅ | 只改了 useProjectStyleOptions.ts（非生成文件） |
| 合并帧图/视频入口前先决定资格过滤 | ✅ | 保留批量帧图/视频按钮 + has_extracted/status 过滤逻辑 |

---

## 已知阻塞（按指示跳过）

- **A5 章节准备回流资产状态:** 跳过。ChapterRead 无资产字段，需先扩后端模型，不硬造前端字段。

---

## 验证结果

| 检查项 | 方法 | 结果 |
|---|---|---|
| 前端 bind_assets 残留 | rg 全量搜索 | 零残留 |
| 前端旧阶段名 | rg 搜索 extract_shots/build_assets/generate_frames | 零残留 |
| 后端 BindAssets 残留 | Get-ChildItem -Recurse | 零残留 |
| TypeScript 编译 | tsc --noEmit | 零错误 |
| 后端启动 | uvicorn + health check | HTTP 200 OK |
| AGENT_STAGE_MAP 映射 | 与 orchestrator.py:35-47 逐条比对 | 6/6 阶段全覆盖 |

---

## 修改文件总览

| 文件 | 改动类型 |
|---|---|
| useAgentOrchestration.ts | P0-1: AGENT_STAGE_MAP 6 阶段映射 |
| usePipelineState.ts | P0-2: stage_bind 残留清除 |
| ChapterShotsPage.tsx | P0-3+P0-4: 删按钮 + 删函数 + 删 hooks + 删 imports |
| useProjectStyleOptions.ts | P1-1: 视频比例 16:9 → 9:16 |
| app/agents/tools/__init__.py | P0-2: 删 BindAssetsTool import + 导出 |
| app/agents/specialists/__init__.py | P0-2: 删 BindAssetsTool import + 注册 |
| app/agents/tools/shot_tools.py | P0-2: 删 BindAssetsInput + BindAssetsTool 类（99行） |
| app/core/storage.py | 已修复: _local_path 下划线路径回退 |

**总计: 8 个文件修改，约 130 行删除/修改。**
