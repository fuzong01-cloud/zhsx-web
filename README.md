# 智慧温室监测与 AI 控制系统

本项目是一个基于 Flask 的智慧温室监测系统，支持从 NLECloud 云平台读取传感器数据、定时入库、历史数据展示、温度统计、趋势可视化、执行器状态记录、账号注册登录，以及基于 Kimi API 的 AI 温室助手。

## 功能概览

- 用户登录、注册、个人资料修改
- NLECloud 云平台授权
- 实时读取温室传感器数据
- 每 5 秒自动采集并保存温度相关数据
- 历史数据列表展示，最新数据在上方
- 温度统计：数据条数、最高温、最低温、平均温
- 温度趋势可视化
- 执行器开关控制与状态入库
- AI 温室助手：
  - 读取最近历史数据并回答问题
  - 支持连续上下文对话
  - 支持自然语言控制阈值和设备
  - 使用 `kimi-k2.6`，关闭思考模式
- 创新功能：智能预警
  - 高温超限
  - 低温超限
  - 升温较快
  - 降温较快
  - 状态平稳

## 技术栈

- 后端：Python、Flask
- 前端：HTML、CSS、JavaScript
- 数据库：SQLite
- 云平台：NLECloud
- AI：Moonshot Kimi API

## 项目结构

```text
D:\web
├── app.py                 # Flask 主程序
├── greenhouse.db          # SQLite 数据库，运行后自动创建
├── .env                   # API Key 等环境变量
├── templates              # 页面模板
│   ├── home.html
│   ├── login.html
│   ├── register.html
│   ├── profile.html
│   ├── cloud_login.html
│   ├── hardware.html
│   └── strategy.html
└── static                 # 静态资源和上传头像
```

## 数据库设计

系统使用 SQLite 数据库 `greenhouse.db`，启动时会自动创建所需数据表。

### 1. 账号信息表 `users`

用于保存系统账号信息。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| account | TEXT | 账号，主键 |
| password | TEXT | 密码 |
| name | TEXT | 姓名 |
| student_id | TEXT | 学号 |
| avatar | TEXT | 头像路径 |
| created_at | TEXT | 创建时间 |

### 2. 温度数据表 `temperature_records`

用于保存每 5 秒采集到的温室环境数据。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER | 自增 ID |
| current_temp | REAL | 当前温度 |
| upper_limit | REAL | 上限温度 |
| lower_limit | REAL | 下限温度 |
| alarm | REAL | 温度报警状态 |
| pressure | REAL | 大气压力 |
| co2 | REAL | 二氧化碳浓度 |
| wind_speed | REAL | 风速 |
| created_at | TEXT | 采集时间 |

### 3. 执行器状态表 `actuator_status`

用于保存执行器开关状态。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER | 自增 ID |
| name | TEXT | 执行器名称 |
| status | INTEGER | 状态，1 表示开启，0 表示关闭 |
| created_at | TEXT | 记录时间 |

## 环境配置

在项目根目录创建 `.env` 文件：

```env
MOONSHOT_API_KEY=你的 Moonshot API Key
KIMI_MODEL=kimi-k2.6
```

系统默认 API 地址为：

```text
https://api.moonshot.cn/v1
```

如需修改，可增加：

```env
MOONSHOT_API_BASE=https://api.moonshot.cn/v1
```

## 运行方式

进入项目目录：

```powershell
cd D:\web
```

启动 Flask：

```powershell
python app.py
```

然后在浏览器访问：

```text
http://127.0.0.1:5000
```

## 使用流程

1. 打开系统登录页。
2. 使用默认账号登录，或注册新账号。
3. 进入首页后先完成 NLECloud 云平台授权。
4. 系统会自动每 5 秒读取一次传感器数据。
5. 数据会写入 SQLite 数据库。
6. 首页会展示实时数据、历史数据、统计结果和趋势图。
7. 可在硬件页面控制执行器开关。
8. 可使用 AI 温室助手进行问答或下达控制指令。

## 默认账号

```text
账号：15600002034
密码：123456
```

## AI 温室助手说明

AI 助手使用 Kimi API，模型默认为 `kimi-k2.6`。

请求中关闭了思考模式：

```json
{
  "thinking": {
    "type": "disabled"
  }
}
```

AI 对话支持上下文记忆。后端会保存最近若干轮对话，并在下一次请求时传给 Kimi API。后端重启后，会自动开始新的会话。

### 普通问答示例

```text
现在温室情况怎么样？
最近温度趋势如何？
CO2 是否异常？
为什么温度报警？
```

### 控制指令示例

明确指令：

```text
把上限调到 30，下限调到 20
打开设备
关闭执行器
```

模糊指令：

```text
太热了，帮我调一下阈值
温度有点低，帮我优化一下
现在环境不太稳定，帮我处理一下
```

为了安全，AI 只能执行白名单动作：

- 调整温度上下限
- 打开或关闭执行器

真正执行前，后端仍会校验：

- 上限必须大于下限
- 温度范围必须在 -40 到 100 ℃
- 必须完成云平台授权

## 页面说明

### 首页

- 展示传感器实时数据
- 展示云平台授权状态
- 展示历史数据列表
- 展示温度趋势图
- 展示统计数据
- 展示智能预警结果
- 提供 AI 温室助手

### 硬件页面

- 展示设备状态
- 控制执行器开关
- 记录执行器状态

### 策略页面

- 展示传感器状态和策略相关信息

### 注册与个人资料页面

- 支持账号注册
- 支持头像上传
- 支持姓名、学号、密码修改
- 信息会同步保存到数据库

## 任务完成情况

- 创建数据库：已完成
- 新建温度数据表：已完成
- 每 5 秒采集并入库：已完成
- 历史数据列表展示：已完成
- 统计数据条数、最高温、最低温、平均温：已完成
- 可视化展示历史数据：已完成
- 创建执行器状态表并定时记录状态：已完成
- 创建账号信息表并支持账号添加：已完成
- 自设创新功能：智能预警，已完成

## 注意事项

- `.env` 中包含 API Key，不建议提交到公开仓库。
- `greenhouse.db` 是本地 SQLite 数据库，删除后系统会在下次启动时重新创建。
- 如果没有完成 NLECloud 授权，传感器数据和设备控制会提示授权错误。
- AI 控制指令需要网络和 Moonshot API Key 正常可用。

