# ID 生成策略文档

> 适用范围：Jellyfish 后端与 Gateway 上游实体 ID 的生成、透传与幂等处理。

> **决策：B1 — 角色 ID 由 Jellyfish 生成，Gateway 透传。**

## 1. 实体与 ID 生成方

| 实体 | 生成方 | 格式 | 说明 |
|------|--------|------|------|
| `project` | Jellyfish 后端 | `project_{uuid4().hex[:12]}` | 由 `internal.py` 或 `entity_crud.py` 生成 |
| **`character`** | **Jellyfish 后端** | **`char_{uuid4().hex[:12]}`** | **Jellyfish 生成，Gateway 透传** |
| `actor` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 无专门导入接口 |
| `scene` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 同上 |
| `prop` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 同上 |
| `costume` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 同上 |

## 2. B1 决策理由

1. **现有代码天然偏向 B1**：`/characters/import` 已是"带 ID 导入"，`CharacterImportItem.character_id` 为必填，语义符合 B1。
2. **幂等收益最大**：角色 ID 只在 Jellyfish 生成一次，Gateway 后续重试、断点续传都直接带 `character_id`，不需要重新生成。
3. **职责划分更干净**：角色元数据由 Jellyfish 持有，Gateway 只负责编排、计费、透传，不应负责 ID 生成。

## 3. B1 要锁死的 3 件事

1. **ID 生成方**：角色 ID 只在 Jellyfish 内部生成，格式 `char_{uuid4().hex[:12]}`，带前缀避免和其他实体类型 ID 撞车。
2. **幂等键**：`character_id`，已存在则跳过并返回 `skipped`，不报错；新增的才创建。
3. **Gateway 语义**：Gateway 调一次 → 拿到/确认角色 ID 列表 → 后续一律带 `character_id` 调导入，**Gateway 侧不生成、不持久化、不修改角色 ID**。

## 4. 幂等策略

### 4.1 角色导入（`POST /internal/v1/projects/{project_id}/characters/import`）
- **幂等键**：`character_id`
- **生成方**：Jellyfish 后端
- **行为**：已存在则跳过，返回 `skipped_count` +1，不抛异常；不存在则创建
- **日志字段**：`id_source = "gateway_upstream"`

### 4.2 普通实体创建（`POST /api/v1/studio/entities/{type}`）
- **幂等键**：`id`
- **生成方**：调用方（Jellyfish 后端）
- **行为**：已存在则抛 `HTTP 400`
- **日志字段**：`id_source = "backend"`

### 4.3 `/characters/import` 语义澄清

`/characters/import` 承担"不存在则创建、已存在则跳过"的语义。

**关键前提**：Jellyfish 侧必须先有"创建角色"动作（如剧本解析后批量 insert），然后 Gateway 再调 `/characters/import` 做幂等确认/补齐。

也就是说：
- 第一次：Jellyfish 创建角色 → Gateway 拿到 `character_id`
- 后续：Gateway 带 `character_id` 调 `/characters/import` → 幂等跳过

## 5. 日志字段规范

所有 ID 生成/校验操作需记录以下字段：
```python
{
    "entity_type": "character",
    "entity_id": "char_abc123",
    "id_source": "gateway_upstream" | "backend" | "backend_generated",
    "idempotency_key": "character_id",
    "project_id": "<project_id>",
    "created": true
}
```

## 6. 注意事项

1. **角色 ID 来源**：角色 ID 由 Jellyfish 后端生成，Gateway 仅作为透传层，不负责 ID 生成或唯一约束。
2. **业务去重**：当前系统未实现基于名称/位置的业务去重。若需要此功能，请在 `unique_index` 中添加联合约束（例如 `(project_id, character_id)`）。
3. **幂等键**：所有幂等检查均基于 `id` 字段，避免因 ID 生成方式不一致导致的重复操作。
4. **日志完整性**：所有 ID 生成/校验操作必须记录日志，确保可追溯性。

> 适用范围：Jellyfish 后端与 Gateway 上游实体 ID 的生成、透传与幂等处理。

> **决策：B1 — 角色 ID 由 Jellyfish 生成，Gateway 透传。**

## 1. 实体与 ID 生成方

| 实体 | 生成方 | 格式 | 说明 |
|------|--------|------|------|
| `project` | Jellyfish 后端 | `project_{uuid4().hex[:12]}` | 由 `internal.py` 或 `entity_crud.py` 生成 |
| **`character`** | **Jellyfish 后端** | **`char_{uuid4().hex[:12]}`** | **Jellyfish 生成，Gateway 透传** |
| `actor` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 无专门导入接口 |
| `scene` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 同上 |
| `prop` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 同上 |
| `costume` | Jellyfish 后端 | `{uuid4().hex[:12]}` | 同上 |

## 2. B1 决策理由

1. **现有代码天然偏向 B1**：`/characters/import` 已是"带 ID 导入"，`CharacterImportItem.character_id` 为必填，语义符合 B1。
2. **幂等收益最大**：角色 ID 只在 Jellyfish 生成一次，Gateway 后续重试、断点续传都直接带 `character_id`，不需要重新生成。
3. **职责划分更干净**：角色元数据由 Jellyfish 持有，Gateway 只负责编排、计费、透传，不应负责 ID 生成。

## 3. B1 要锁死的 3 件事

1. **ID 生成方**：角色 ID 只在 Jellyfish 内部生成，格式 `char_{uuid4().hex[:12]}`，带前缀避免和其他实体类型 ID 撞车。
2. **幂等键**：`character_id`，已存在则跳过并返回 `skipped`，不报错；新增的才创建。
3. **Gateway 语义**：Gateway 调一次 → 拿到/确认角色 ID 列表 → 后续一律带 `character_id` 调导入，**Gateway 侧不生成、不持久化、不修改角色 ID**。

## 4. 幂等策略

### 4.1 角色导入（`POST /internal/v1/projects/{project_id}/characters/import`）
- **幂等键**：`character_id`
- **生成方**：Jellyfish 后端
- **行为**：已存在则跳过，返回 `skipped_count` +1，不抛异常；不存在则创建
- **日志字段**：`id_source = "gateway_upstream"`

### 4.2 普通实体创建（`POST /api/v1/studio/entities/{type}`）
- **幂等键**：`id`
- **生成方**：调用方（Jellyfish 后端）
- **行为**：已存在则抛 `HTTP 400`
- **日志字段**：`id_source = "backend"`

### 4.3 `/characters/import` 语义澄清

`/characters/import` 承担"不存在则创建、已存在则跳过"的语义。

**关键前提**：Jellyfish 侧必须先有"创建角色"动作（如剧本解析后批量 insert），然后 Gateway 再调 `/characters/import` 做幂等确认/补齐。

也就是说：
- 第一次：Jellyfish 创建角色 → Gateway 拿到 `character_id`
- 后续：Gateway 带 `character_id` 调 `/characters/import` → 幂等跳过

## 5. 日志字段规范

所有 ID 生成/校验操作需记录以下字段：
```python
{
    "entity_type": "character",
    "entity_id": "char_abc123",
    "id_source": "gateway_upstream" | "backend",
    "idempotency_key": "character_id",
    "project_id": "<project_id>",
    "created": true
}
```

## 6. 注意事项

1. **角色 ID 来源**：角色 ID 由 Jellyfish 后端生成，Gateway 仅作为透传层，不负责 ID 生成或唯一约束。
2. **业务去重**：当前系统未实现基于名称/位置的业务去重。若需要此功能，请在 `unique_index` 中添加联合约束（例如 `(project_id, character_id)`）。
3. **幂等键**：所有幂等检查均基于 `id` 字段，避免因 ID 生成方式不一致导致的重复操作。
4. **日志完整性**：所有 ID 生成/校验操作必须记录日志，确保可追溯性。
