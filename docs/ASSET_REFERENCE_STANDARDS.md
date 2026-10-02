# 资产参考图完整标准（唯一权威来源）

> 本文档替代 CHARACTER_ASSET_PLAN.md、CHARACTER_ASSET_OPTIMIZATION.md 中的资产标准部分。凡涉及资产参考图的规格、提示词、背景、尺寸等标准，以本文档为准。

## 〇、背景色冲突说明

历史文档中存在背景色冲突：
- `CHARACTER_ASSET_PLAN.md` 原写 "light gray solid studio background"（浅灰）
- `CHARACTER_ASSET_OPTIMIZATION.md` 写 "纯白背景"
- `MASTER_PLAN.md` 第 433 行权威定义 "白底"

**统一标准：纯白 (#FFFFFF)**，以 MASTER_PLAN 为准。CHARACTER_ASSET_PLAN 的 "light gray" 已废弃。

---

## 一、角色参考图（Character Reference Sheet）

### 1.1 规格
| 项 | 值 |
|---|---|
| 布局 | 左侧大头特写 + 右侧 3 张全身（正面/右侧/背面），合成一张图 |
| 尺寸 | 2048x1152 (16:9) |
| 背景 | 纯白 (#FFFFFF) |
| 风格 | 中国写实风，商业人像摄影，8K |
| 约束 | 同一人、统一五官/发型/服装/配饰、中立站姿、从头到脚不裁切、正交视图无透视 |

### 1.2 一致性规则
- 正面视图先出，作为后续视图（右侧/左侧/背面）的参考图
- 代码已实现：`is_front_view()` 判断为正面时不带 ref，非正面时 `pick_front_ref_file_id()` 取正面图作为 `default_images`
- 同一角色不同状态（换装/受伤）：每状态独立生成一张，状态间不互引

### 1.3 多状态处理
| 角色 | 状态数 | 状态列表 |
|---|---|---|
| 林宸 | 3 | 前期朴素休闲装 / 后期黑色高定西装 / 大结局温柔针织衫 |
| 苏清月 | 3 | 素雅日常装 / 宴会浅礼裙 / 受伤淡妆造型 |
| 苏老太 | 1 | 中式绸缎唐装 |
| 苏浩 | 1 | 浮夸潮牌+廉价大金戒指 |
| 赵天宇 | 1 | 高定西装+名牌腕表+墨镜 |
| 龙九 | 1 | 黑色定制西装+白手套+蓝牙耳机 |
| 江辰 | 1 | 黑色轻奢西装+墨镜 |
| 江沧海 | 1 | 高定深色西装+雪茄 |
| 赵家老爷子 | 1 | 沉稳正装 |
| 暗卫 | 1 | 统一黑西装+白手套 |
| 苏家亲戚 | 1 | 势利多变群体装 |
| 商界权贵 | 1 | 沉稳正装群体 |
| 杀手 | 1 | 黑色劲装 |

总参考图数：17 张

### 1.4 Positive Prompt 模板
+```
Professional real-person character reference sheet, landscape layout,
left side is head/face close-up,
right side 3 full body photos: front, right side, back.
All same person, unified features/hair/outfit/accessories.
Natural neutral standing pose, arms hanging, head to toe no crop,
orthographic view, no perspective distortion.
Pure white solid studio background, even soft studio lighting,
commercial portrait photography, Chinese realistic style,
realistic skin texture, rich detail, 8K HD,
no text, no watermark, no extra objects.
{character_description_with_visual_anchors}
+```

### 1.5 Negative Prompt
+```
Inconsistent features, face change, different person, limb distortion,
crop, close-up misalignment, extra person, scene environment,
strong shadow, text, watermark, perspective, deformed hands/feet,
clothing error, blur, low quality, anime, 2D, 3D render, cartoon, hand-drawn
+```

### 1.6 描述扩充要求
角色描述必须包含以下视觉锚点：
1. 年龄、性别、种族
2. 脸型、五官特征（眉/眼/鼻/唇）
3. 发色、发型
4. 瞳色
5. 身高/肤色
6. 身高比例、体型（肩宽/骨架/肌肉量）
7. 服装颜色、款式、材质（具体到颜色词+面料词）
8. 配饰（具体物品+材质+颜色）
9. 标识性特征（疤痕/纹身/胎记）
10. 气质关键词（隐忍/锐利/温婉/嚣张）

---

## 二、场景参考图（Scene Reference）

### 2.1 规格
| 项 | 值 |
|---|---|
| 布局 | 广角环境建立镜头，无人物 |
| 尺寸 | 1080x1920 (9:16 竖屏) |
| 风格 | 电影级写实，与角色参考图同一视觉风格 |
| 约束 | 展示完整环境空间、灯光氛围、陈设道具 |

### 2.2 Positive Prompt 模板
+```
Cinematic establishing shot, wide angle, 9:16 vertical,
no people, empty environment.
{scene_description_with_lighting_and_props}
Realistic photo texture, cinematic lighting, 8K HD,
no text, no watermark.
+```

### 2.3 Negative Prompt
+```
People, characters, faces, text, watermark, cartoon, anime,
2D, 3D render, low quality, blur, oversaturated, fisheye distortion
+```

### 2.4 场景列表
13 个场景，每场景 1 张参考图

---

## 三、道具参考图（Prop Reference）

### 3.1 规格
| 项 | 值 |
|---|---|
| 布局 | 产品特写，多角度（正面+侧面+使用状态），合成一张 |
| 尺寸 | 1024x1024 (方形) |
| 背景 | 纯白 |
| 风格 | 产品摄影，高细节 |
| 约束 | 材质纹理清晰、无杂物、无手部遮挡 |

### 3.2 Positive Prompt 模板
+```
Product photography, multiple angles on white background,
studio lighting, macro detail, material texture visible,
high quality commercial shot, 8K.
{prop_description_with_material_and_color}
+```

### 3.3 Negative Prompt
+```
Hands, human, background clutter, blur, low quality, text, watermark,
cartoon, anime, 2D, 3D render, deformed, cropped
+```

### 3.4 道具列表
16 个道具，每道具 1 张参考图
核心特写道具：黑金战神令牌、弹片戒指、红木拐杖

---

## 四、服装参考图（Costume Reference）

### 4.1 规格
| 项 | 值 |
|---|---|
| 布局 | 平铺全套（flat-lay），展示所有组件 |
| 尺寸 | 1024x1024 (方形) |
| 背景 | 纯白 |
| 风格 | 服装平铺摄影，面料质感 |
| 约束 | 全套可见、面料纹理清晰、配色准确 |

### 4.2 Positive Prompt 模板
+```
Flat lay clothing photography, full outfit laid out on white background,
all pieces visible, fabric texture detail, accurate colors,
commercial fashion photography, 8K.
{costume_description_with_colors_and_materials}
+```

### 4.3 Negative Prompt
+```
Human model, mannequin, body, background clutter, blur, low quality,
text, watermark, cartoon, anime, 2D, 3D render, deformed, cropped
+```

### 4.4 服装列表
11 套服装，每套 1 张参考图

---

## 五、自动化要求

| 步骤 | 目标 |
|---|---|
| 角色描述 | 提取确认时 AI 自动填充（空值才填，不覆盖已有值） |
| 提示词 | 使用参考图模板，自动拼接正向 + 负向 |
| 尺寸 | 强制 2048x1152 (16:9) 角色 / 1080x1920 场景 / 1024x1024 道具服装 |
| 负向提示词 | 强制传入 negative_prompt |
| 触发 | 一键批量生成，前端按钮触发 |
| 一致性 | 正面先出，后续以正面为参考图 |

---

## 六、执行流程

### 步骤
1. 扩充角色描述（补充视觉锚点）
2. 修改 GenerateAssetRefsTool 支持四种资产类型
3. 修改 direct_image_generate 支持 negative_prompt（已完成）
4. 删除旧数据（角色+场景参考图）
5. 重新生成全部资产：
   - 角色 17 张（13 角色，林宸/苏清月各 3 状态）
   - 场景 13 张
   - 道具 16 张
   - 服装 11 张
   - 合计 57 张
6. 预估时间：约 10 分钟（每张 ~9 秒）

### 验收标准
- 角色图：4 视图布局、纯白背景、同一人物一致性
- 场景图：无人物、竖屏 9:16、灯光氛围正确
- 道具图：纯白背景、多角度、材质纹理清晰
- 服装图：平铺全套、纯白背景、面料质感
- 所有图：8K 质感、无文字水印、风格统一

---

## 七、标准与代码的映射

### 7.1 PromptCategory 枚举映射

| 资产类型 | 正面视图 (front) | 其他视图 (other) | 代码位置 |
|---|---|---|---|
| Character | `combined` | `combined` | `build_character_image_base_draft()` |
| Actor | `actor_image_front` | `actor_image_other` | `build_actor_image_base_draft()` |
| Prop | `prop_image_front` | `prop_image_other` | `build_asset_image_base_draft()` |
| Scene | `scene_image_front` | `scene_image_other` | `build_asset_image_base_draft()` |
| Costume | `costume_image_front` | `costume_image_other` | `build_asset_image_base_draft()` |

> Character 统一使用 `PromptCategory.combined`；Actor/Prop/Scene/Costume 使用 `_*_front` / `_*_other` 分视图对。
> 映射逻辑在 `app/services/studio/image_tasks.py` 的 `asset_prompt_category()` 函数中。

### 7.2 一致性链代码路径

+```
build_character_image_base_draft
  -> PromptCategory.combined（角色提示词模板）
  -> pick_ordered_ref_file_ids（取 actor/costume 正面图作为 ref）
  -> default_images = [front_ref_file_ids]

build_asset_image_base_draft (prop/scene/costume)
  -> asset_prompt_category（按 relation_type + is_front_view 选 category）
  -> is_front_view? -> 不带 ref
  -> !is_front_view? -> pick_front_ref_file_id -> default_images = [front_ref]
+```

> 正面先出、非正面引用正面图的规则已在代码层实现，文档标准与代码行为一致。

---

## 八、变更流程

修改资产标准时，以下三处必须同步更新：

1. **本文档** (`Jellyfish/docs/ASSET_REFERENCE_STANDARDS.md`) — 更新规格/模板/约束
2. **prompt_templates 表** — 更新对应 `PromptCategory` 的正向/负向提示词模板内容
3. **代码常量** — 如涉及尺寸/背景色等硬编码值，更新 `app/services/studio/image_tasks.py` 及 `build_base.py`

> 三者不同步将导致：文档说纯白、数据库模板写浅灰、代码默认纯白的歧义状态。
> 变更前先在本文档记录旧值->新值，再逐项更新。
