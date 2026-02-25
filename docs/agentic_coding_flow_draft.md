# Agentic Coding 流程图（初稿）

说明：本稿用于后续逐步完善的基线版本。  
状态约定：**绿色=已完成**，**置灰=待完善（尚未完成）**。

```mermaid
flowchart TD
    A["需求输入 / Task 创建"] --> B{"任务模式"}
    B -->|PLAN| C["生成 Plan（Claude）"]
    C --> D["Plan 解析与结构化"]
    D --> E["人工确认 Plan"]
    E --> F["进入 EXEC 阶段"]

    B -->|EXEC| G["创建隔离 worktree"]
    F --> G
    G --> H["Claude 执行编码"]
    H --> I{"是否产生有效变更"}
    I -->|否| J["任务失败（NO_CHANGES）"]
    I -->|是| K["提交 Commit（当前为固定模板）"]
    K --> L["Rebase 到主分支"]
    L --> M["执行测试命令"]
    M --> N["Push 分支"]
    N --> O["创建 PR（gh / API 回退）"]
    O --> P["进入 REVIEW 状态"]

    %% 后续优化（置灰）
    K --> Q["PR 前 Commit Message 规范校验 / 自动生成"]
    Q --> R["PR 描述自动补全（变更摘要/风险/测试结果）"]
    R --> S["合并前质量门禁（可配置）"]

    classDef done fill:#dcfce7,stroke:#166534,color:#14532d,stroke-width:1px;
    classDef todo fill:#e5e7eb,stroke:#9ca3af,color:#6b7280,stroke-width:1px,stroke-dasharray: 4 3;
    classDef fail fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d,stroke-width:1px;

    class A,B,C,D,E,F,G,H,I,K,L,M,N,O,P done;
    class J fail;
    class Q,R,S todo;
```

## 节点状态清单（初稿）

| 节点 | 当前状态 | 备注 |
|---|---|---|
| Task 创建、PLAN/EXEC 分流 | 已完成 | 后端已有任务模式与状态流转 |
| PLAN 生成、解析、人工确认 | 已完成 | `PLAN_RUNNING -> PLAN_REVIEW -> EXEC` |
| worktree 隔离执行 | 已完成 | 执行前创建、结束后清理 |
| Commit/Rebase/Test/Push/PR | 已完成 | 已在执行流水线中串联 |
| PR 前 commit message 规范化 | 待完善（置灰） | 当前 commit message 为固定模板，缺少规范校验与增强 |
| PR 描述自动补全 | 待完善（置灰） | 当前 PR body 固定为默认文案 |
| 合并前质量门禁 | 待完善（置灰） | 建议加入可配置策略（如测试覆盖/标签/审批） |

## 建议的下一步完善顺序

1. `PR 前 commit message 规范化`（优先）  
2. `PR 描述自动补全`（次优先）  
3. `合并前质量门禁`（最后接入，可配置化）

