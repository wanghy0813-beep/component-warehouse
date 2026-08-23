# Team Changelog

## v1.2.3 · 高对比与浅色加载态

- 团队端同步采用高对比白色卡片、深墨色文字和石油蓝主操作色。
- 加载前背景、身份校验提示和局部加载器均改为稳定浅色状态。

## v1.2.2 · 共享矿物材质视觉

- 团队端同步使用矿物青、陶瓷白、氧化铜与鼠尾草配色，与个人端保持同一套控件和表格语言。
- 全局加固表格、标签、对话框和窄屏导航的溢出保护，并停用高成本背景模糊。

## v1.1.0 · 团队 Gerber 装配

- 团队项目复用个人版同一套制造包解析、版本预览、装配画布、校准和多板管理。
- 队长和编辑者可操作团队库已链接成员的实时个人库存；只读者只能查看。
- 操作审计同时记录操作者、来源库存成员、团队库、项目、实物板、位号、报损事件和撤销关系。
- 批量操作库存不足时整次回滚，并使用状态版本返回 `409` 防止覆盖他人更新。

## Open-source profile

- Uses local username/password accounts by default.
- Supports team libraries, invitations, member roles, shared components, PCB records, projects, purchases, risks, labels, and logs.
- Uses generic branding and no bundled private logo by default.
- Excludes private deployment data, filing numbers, secrets, and brand assets.
