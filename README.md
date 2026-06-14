# Component Warehouse

个人元器件库存管理系统，用于管理已购买电子元器件，并辅助后续 PCB 设计选型。

## 功能

- 元器件新增、编辑、删除、查询
- 分类、标签、状态、关键词筛选
- 元器件库默认按分类卡片展示，支持紧凑表格视图和右侧详情抽屉
- 元器件卡片按稳定顺序展示：分类按默认分类顺序，分类内按元器件创建顺序固定，AI 后台更新不会打乱列表
- 电阻、电容、晶振等被动器件会在卡片上突出阻值、容值或频率，型号与封装作为辅助信息
- 电阻、电容、电感卡片提供常用单位换算，例如 Ω/kΩ/MΩ、pF/nF/µF、nH/µH/mH，方便快速选型
- 默认分类初始化：电阻、电容、电感、二极管、三极管、MOS管、芯片、电源、接口、连接件、时钟源、开关、开发板、功能模块、通信模块、显示模块、机电件、散热件、保护器件、传感器、结构件、其他
- AI 元器件规范化会按规则边界让 MiMo 生成短名称、分类、规格和标签；原始购物标题保存到 `source_title`
- 分类颜色系统：分类标签、卡片和 BOM 分组使用克制浅色识别
- 项目 BOM 管理、分类分组、库存占用、取料状态、缺料清单、CSV 导出
- BOM 单项状态重新梳理：预占/待取料、已取料、已释放；“完成”只用于项目整体
- BOM 导入预览会保留低置信候选、显示可能作用和缺料搜索建议，不再让未匹配行空着
- 立创商城物料明细 Excel 预览导入，支持 `.xls` / `.xlsx`，确认后按立创编号或名称/型号/封装合并
- 支持淘宝、拼多多、1688、立创等购物截图的 AI 图片识别预览导入，确认后再新增或合并库存
- 立创订单导入记录，按“订单编号 + 商品编号”去重，避免同一订单重复入库
- 支持立创商城移动端搜索跳转，优先用立创编号、型号或名称构造搜索 URL
- 排针、螺丝、螺母、铜柱支持粗分类和规格归一化统计，杜邦线默认不进入重点统计
- AI 助手接入小米 MiMo：缓存元器件说明、风险提示、PCB 注意、替代料、项目规划、BOM 分析
- AI 知识卡片按设计洞察、关键参数、手册核对项、风险、PCB 注意、替代料检查等分组显示，并使用彩色卡片增强可读性
- AI 后台整理队列：新导入或参数变化的元器件会进入待整理状态，可手动启动/暂停
- 首页显示库存总览、分类分布、最近项目 BOM 和常用入口
- 关于页面展示版本更新、引用信息、系统统计、登录日志和操作变更日志
- Docker Compose 部署

## 目录

```text
backend/   FastAPI + SQLite
frontend/  Vue 3 + Vite + Element Plus
data/      SQLite 数据库挂载目录
```

## 本地开发

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python init_db.py
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

默认前端开发地址为 `http://localhost:5173`，API 通过 Vite 代理到 `http://127.0.0.1:8000`。

## Docker 部署

```bash
docker compose up -d --build
```

默认访问地址：

```text
http://localhost:8080/cw/
```

SQLite 数据库保存在宿主机 `./data/component_warehouse.db`。

## 简单访问保护

Docker Compose 默认启用简单访问保护。首次部署请复制 `.env.example` 为 `.env`，修改 `APP_ACCESS_TOKEN` 和 `APP_PASSWORD`：

```bash
cp .env.example .env
docker compose up -d --build
```

启用后前端会显示登录页。密码校验通过后，前端保存 token 并通过 `Authorization: Bearer ...` 访问 API。

### 公网安全建议

系统面向个人使用，部署到公网域名时建议至少保留以下配置：

- 修改 `.env` 中的 `APP_PASSWORD` 和 `APP_ACCESS_TOKEN`，不要使用默认值。
- `ENABLE_API_DOCS=0` 默认关闭 `/docs`、`/redoc` 和 OpenAPI JSON，减少被扫描面。
- `ALLOWED_HOSTS` 限制允许访问的 Host，默认包含 `wxylab.ltd`、子域名和本地调试地址。
- 登录接口带有内存级 IP 限流，默认 10 分钟最多 8 次失败尝试。
- 前端 Nginx 默认添加安全响应头、禁止 iframe 嵌入、隐藏 dotfile、限制上传大小。
- 建议在外层 Nginx/Caddy 继续启用 HTTPS、访问日志、Fail2ban 或云防火墙。

## 小米 MiMo AI

AI 功能通过后端调用小米 MiMo OpenAI 兼容接口。API Key 只能放在环境变量或 `.env`，不要写入代码：

```env
MIMO_API_KEY=sk-your-mimo-key
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5
MIMO_TIMEOUT_SECONDS=90
```

当前 AI 功能包括：

- 自动分类：根据名称、型号、参数推荐分类
- 用途说明：生成用途、封装和 PCB 选型注意事项
- 项目规划：根据项目目标推荐已有库存、缺失物料和风险
- 需求找料：输入功能需求，先检索本地库存，再由 MiMo 生成选型建议
- 器件说明：输入器件名称/型号和已有规格，生成规格、用途、PCB 注意事项和库存字段补全建议
- BOM 分析：根据当前项目 BOM 生成完整度、缺料建议、替代方案、PCB 风险提示
- 项目 AI 咨询：围绕当前 BOM 提问，优先推荐已有库存，缺失物料提供立创搜索入口
- 图片识别导入：上传购物截图后生成候选物料、匹配已有库存、置信度和立创搜索链接
- 元器件规范化：由 AI 整理名称、分类、标签、连接件/机械件/设备模块规格

AI 生成内容会缓存到数据库的 AI 字段和知识卡片，用于列表摘要、详情页和后续检索；库存数量、型号、位置等核心用户数据不会被 AI 自动覆盖。

风扇、温湿度传感器、TOF 测距模块、OLED 屏、通信模块、电源模块等已购买设备建议同样录入库存。系统把它们视为可被 BOM 占用的库存物料，而不是只管理基础电阻电容。分类边界如下：

- `传感器`：温湿度、TOF、光照、气体、IMU、压力、电流检测等传感器芯片、探头或小板。
- `机电件`：风扇、电机、水泵、蜂鸣器、喇叭、电磁铁、继电器模组等会产生机械、声学或热管理动作的物料。
- `散热件`：散热片、导热垫、风扇支架等热管理附件。
- `通信模块`：Wi-Fi、蓝牙、LoRa、GNSS、蜂窝、射频收发模块；相关单颗芯片仍归 `芯片`。
- `显示模块`：OLED/LCD/数码管屏、触摸屏、带驱动显示小板；单颗 LED 仍归 `二极管`。
- `功能模块`：非开发板、非传感器、非通信、非电源、非显示的成品小板或可直接接线模块。
- `结构件`：外壳、支架、面板、固定座、亚克力板等非电气结构件。

AI 元器件知识卡片会尽量避免重复名称、阻值、容值、封装等已知字段，重点输出这些更适合选型决策的信息：

- 设计洞察：降额建议、工作边界、常见误用和经验规则
- 关键参数：耐压、电流、功率、精度、温漂、输入/输出范围等
- 手册核对项：需要从数据手册确认的 TCR、DC Bias、SOA、Rds(on)、热阻、补偿网络等字段
- 风险提示：替代风险、热设计风险、参数余量风险、封装限制
- PCB 注意：电源回路、地、去耦、反馈走线、散热焊盘、接口保护等
- 替代料检查：不是只列型号，而是提示替代时必须核对哪些参数

### AI 缓存逻辑

元器件 AI 缓存使用以下字段生成 `ai_cache_key`：

```text
name, model, parameters, package, category_id, lcsc_number, datasheet_url, remark, tags
```

如果字段未变化，读取缓存结果，不重复调用 MiMo。字段变化后组件标记为 `stale`，可由后台任务或详情页手动刷新重新分析。

系统还会把内部 `AI_ANALYSIS_VERSION` 纳入缓存 key。当 AI 分析逻辑升级时，旧的浅层缓存会自动过期并重新整理一次；整理完成后不会在字段不变的情况下重复调用 AI。

详情页提供：

- AI 重新分析
- 刷新用途
- 刷新风险
- 刷新替代料

### AI 后台任务

后台任务表 `ai_tasks` 用于管理自动整理：

- `pending`：等待分析
- `processing`：分析中
- `completed`：已完成
- `failed`：失败
- `stale`：缓存过期

服务启动后会自动扫描缺少 AI 信息或缓存过期的元器件，加入队列并按单并发后台整理；缓存 key 不变且已经完成的器件不会重复调用 MiMo。确认 Excel 导入后，新建/合并的元器件也会自动进入 AI 队列。

首页的“AI 后台整理”区域可以查看数量、整理缺失项、开始和暂停后台任务。失败项不会在每次重启时无限自动重试，需要手动重新分析或重新入队。当前实现为单进程单并发 worker，适合个人 Docker 部署。

器件说明模块支持可选联网搜索，页面可选择“关闭 / 自动 / 强制”。默认“自动”由模型判断是否需要搜索；如需使用联网搜索，需要在小米 MiMo 控制台启用 Web Search Plugin，联网搜索可能产生额外费用。

### 立创资料来源说明

系统不能直接抓取 `member.szlcsc.com` 的会员订单页，因为该页面依赖你的浏览器登录态和账号权限。AI 整理时会优先使用这些可稳定访问的信息：

- 库存字段中的立创编号、商品编号、型号、品牌、封装和参数
- Excel 导入时解析到的立创物料信息
- 用户手动填写的 `datasheet_url`
- 公开立创商品页、厂商官网、官方数据手册和可信分销商页面

如果需要进一步增强，可以在后续导入流程里保存公开商品页链接、图片链接或 PDF 链接；AI 会把这些链接作为优先资料来源。

立创搜索按钮使用移动端公开搜索入口：

```text
https://m.szlcsc.com/pages-list/global-product/index?keyword=<关键词>
```

关键词优先级为立创编号、型号、名称或 AI 推荐型号。

## BOM 状态说明

- `预占/待取料`：BOM 需要该物料，系统会占用库存，但不会扣减实际库存。
- `已取料`：确认已经从库存拿走物料，系统会扣减库存并解除预占。
- `已释放`：该 BOM 项不再占用库存。
- `完成项目`：项目层面的动作，表示整个 BOM 已经处理完；单个物料不再使用“完成”作为主要状态。

旧版本中的单项 `done` 会显示为“旧状态：已完成”，系统不会自动扣库存；需要时可在页面上手动转换为“已取料”。

## 更新日志

完整变更记录见 [CHANGELOG.md](./CHANGELOG.md)。

## 部署到 wxylab.ltd

Compose 默认只暴露宿主机 `8080` 端口，不会直接占用 80/443。可以在已有 Nginx/Caddy 中反向代理到：

```text
http://127.0.0.1:8080/cw/
```

推荐部署在 `https://wxylab.ltd/cw/` 子路径。外层反向代理保留 `/cw/` 前缀转发到本服务即可；本服务内部已经处理 `/cw/api/` 和前端路由刷新。

## Excel 导入表头

支持常见立创商城导出字段：

- 物料名称、商品名称、名称
- 型号、规格型号、商品型号
- 数量、购买数量、库存数量
- 封装、封装规格
- 物料编号、商品编号、立创编号、LCSC编号
- 参数、规格参数、描述

针对立创商城物料明细对账单，还支持：

- 订单编号
- 下单时间
- 品牌
- 商品类型
- 封装格式
- 订购数量
- 商品单位
- 快递单号

导入流程为“上传 -> 预览 -> 确认”。重复库存可选择合并或跳过；已经导入过的同一“订单编号 + 商品编号”会自动跳过。

## API 摘要

- `GET /api/components`
- `GET /api/components/grouped`
- `POST /api/components`
- `PUT /api/components/{id}`
- `DELETE /api/components/{id}`
- `GET /api/components/{id}/ai`
- `POST /api/components/{id}/ai/refresh`
- `GET /api/categories`
- `GET /api/projects`
- `POST /api/projects`
- `POST /api/projects/{id}/bom`
- `GET /api/projects/{id}/shortage`
- `GET /api/projects/{id}/export`
- `POST /api/projects/{id}/ai/analyze-bom`
- `POST /api/projects/{id}/ai/plan`
- `POST /api/import/excel/preview`
- `POST /api/import/excel/commit`
- `GET /api/ai/tasks/summary`
- `GET /api/ai/tasks`
- `POST /api/ai/tasks/enqueue-missing`
- `POST /api/ai/tasks/start`
- `POST /api/ai/tasks/pause`
- `POST /api/ai/classify`
- `POST /api/ai/explain`
- `POST /api/ai/project-plan`
- `POST /api/ai/component-search`
- `POST /api/ai/component-info`
