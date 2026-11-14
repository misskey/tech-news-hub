# 科技早报 tech-news-hub

自托管的科技资讯站。它定时抓取多个技术社区的热门内容，按你设的兴趣打分，生成一份每日早报，并通过邮件、Server酱、Telegram、企业微信或飞书推送。

数据放在本机的 SQLite 里。推送用的密钥只从环境变量读取，不会写进数据库，也不要提交到仓库。

## 功能

- 来源可以单独开关：GitHub Trending、Hacker News、V2EX、掘金、Reddit r/programming、少数派、Product Hunt，以及任意 RSS / Atom
- 某个来源失败只会记日志并跳过，不会让整次抓取中断
- 用关键词权重、屏蔽词、编程语言和来源热度给条目打分
- 网页上按今天、近 3 天、近 7 天浏览，可按来源和关键词筛选
- 每条有一两句说明，展开后能看到更长的一段和提到的技术名。首页和推送里还有一份一分钟能读完的今日简报
- 默认每天 08:00（Asia/Shanghai）抓取并推送，时间可改
- 设置页可以立刻抓取，或马上发一份测试早报

## 本地运行

需要 Python 3.11 或更新版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，至少写上 `ADMIN_PASSWORD`。然后：

```bash
python -m app.cli fetch
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。第一次抓取也可以在「设置」里点「保存并立即抓取」。

开发依赖和测试：

```bash
pip install -r requirements-dev.txt
pytest
```

## 配置

所有环境变量都列在 [`.env.example`](.env.example)。应用启动时会读取当前目录的 `.env`，已经存在的环境变量优先，不会被 `.env` 覆盖。

| 变量 | 作用 |
| --- | --- |
| `ADMIN_PASSWORD` | 设置页密码。留空时设置页没有保护，只适合本机试用 |
| `PROTECT_SITE` | 设为 `1` 时，浏览页也要先登录 |
| `SECRET_KEY` | 会话签名。留空会在数据目录里自动生成 |
| `DATA_DIR` | 数据库和自动生成的密钥目录，默认 `./data` |
| `SCHEDULER_ENABLED` | `1` 使用内置定时任务。改用系统 cron 时设为 `0` |
| `FETCH_TIMEOUT` | 单个 HTTP 请求超时，秒 |
| `HN_STORY_LIMIT` | Hacker News Top 取多少条 |
| `OPENAI_API_KEY` | 兼容 OpenAI 的密钥。留空则只用摘录，不调用模型 |
| `OPENAI_BASE_URL` | 接口地址，默认 `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 默认模型名，默认 `gpt-4o-mini`。设置页可以改成别的模型 |

推送渠道要同时满足两件事才会发送：设置页勾选了该渠道，并且对应环境变量已经填好。

- 邮件：`SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`、`SMTP_TO`。587 端口保持 `SMTP_TLS=1`。465 端口用 `SMTP_SSL=1` 且 `SMTP_TLS=0`
- Server酱：`SERVERCHAN_SENDKEY`（[sct.ftqq.com](https://sct.ftqq.com/) 的 SendKey）
- Telegram：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`
- 企业微信群机器人：`WECOM_WEBHOOK`（完整的 webhook 地址）
- 飞书自定义机器人：`FEISHU_WEBHOOK`。机器人开了签名校验时再填 `FEISHU_SECRET`

`SMTP_TO` 可以写多个收件人，用英文逗号分隔。

## 偏好和打分

设置页里这些内容会写进数据库：

- 关键词，每行一个，格式是 `关键词:权重`。权重范围 -5 到 20，不写权重时当作 1
- 屏蔽词。命中后这条既不展示，也不进早报
- 编程语言，最多 6 个。用来抓对应语言的 GitHub Trending，并给语言相符的仓库加分。留空则抓全语言日榜
- 启用哪些来源
- 自定义 RSS，每行 `名称|地址`。行首加 `!` 表示暂时不抓。需要同时勾选「自定义 RSS」
- 每期条数、推送时间、时区和早报时间窗口

分数的算法：

```text
分数 = 命中关键词的权重之和 × 100 + 语言加分 + ln(1 + 热度)
```

语言相符加 3 分。热度来自各站自己的信号：GitHub 用「今日新增 star」，没有这个数字时退回总 star；Hacker News 用点数；V2EX 用回复数；掘金用热榜热度；少数派用点赞。Reddit、Product Hunt 和普通 RSS 没有统一的热度，就用它在列表里的名次。

英文关键词按词边界匹配，所以 `AI` 不会命中 `email`。中文关键词按包含匹配。

两个例子：

- 标题同时含「Rust」（权重 2）和「LLM」（权重 1），语言是 Rust，今日 500 star：关键词 300 分，语言 3 分，热度约 6 分，总分约 309
- 没配任何关键词时，排序基本只看热度

同一条链接被多个来源报出来时，页面和早报只保留分数更高的那条。数据库里仍按「来源 + 原始 ID」去重，重复抓取只会更新标题和热度。

## 摘要和今日简报

列表上每条先显示一两句话，点「展开看点」能看到更长的一段、原文里提到的技术和原文摘录。「单独打开」是这条的详情页。

首页顶部有「今日技术简报」和「今日新技术看点」，推送的邮件和机器人消息里也会带上同样的内容，不再只是一串标题。

生成方式：

- 设置页勾选了「用大模型写中文摘要」，并且环境变量里有 `OPENAI_API_KEY` 时，抓取和推送会调用兼容 OpenAI 的接口。模型名可以写在设置页，留空就用 `OPENAI_MODEL`。
- 没有密钥、关掉开关，或者模型请求失败时，自动改用标题和原文摘录。中文原文会截取前几句；英文原文会保留标题，并附上一小段摘录。单条失败不会让这次抓取或页面中断。
- 摘要按标题和摘录的内容缓存在 SQLite 里。内容没变就不会重复请求。配上密钥之后，下一次抓取或推送会把摘录换成模型写的中文。

浏览页面本身不调用模型，所以打开首页不会因为接口慢而卡住。

## 命令行

```bash
python -m app.cli fetch   # 只抓取
python -m app.cli push    # 用已有内容推送
python -m app.cli run     # 先抓取再推送
```

全部来源都失败时，`fetch` 和 `run` 会以退出码 1 结束。推送渠道都尝试了但全部失败时同样返回 1。没有勾选渠道，或时间窗口里没有新内容，不算失败。

内置调度开着时，不要再配一条系统 cron，否则一天会推两次。想自己调度时：

```bash
# .env
SCHEDULER_ENABLED=0
```

```cron
0 8 * * * cd /opt/tech-news-hub && /opt/tech-news-hub/.venv/bin/python -m app.cli run
```

服务进程没在 8 点运行时，不会补发错过的那一期。

## 用 Docker 部署

服务器上需要 Docker 和 Docker Compose。

```bash
git clone <你的仓库地址> /opt/tech-news-hub
cd /opt/tech-news-hub
cp .env.example .env
# 编辑 .env，填上 ADMIN_PASSWORD 和要用的推送渠道
docker compose up -d --build
```

站点在宿主机的 `8000` 端口。数据库在项目目录的 `data/`。备份这个目录即可。

前面可以加一层反代，例如 Nginx：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

放到公网时请设置 `ADMIN_PASSWORD`。如果连浏览页也不想公开，再把 `PROTECT_SITE=1`。

升级时重新构建即可，SQLite 文件还在 `data/`：

```bash
git pull
docker compose up -d --build
```

不用 Docker 时，用上面的虚拟环境跑 `uvicorn app.main:app --host 0.0.0.0 --port 8000`，再用 systemd 把进程拉起来。`DATA_DIR` 指到一个会保留的目录。

## 添加一个来源

1. 在 `app/fetchers/` 写一个抓取器，提供 `source_id`、`label`，以及 `async def run(self, client, prefs)`。解析函数单独写成纯函数，测试用录好的响应，不访问网络。
2. 把解析结果放进 `NewsItem`。`popularity` 用来参与打分。
3. 在 `app/sources.py` 的 `CATALOG` 登记，设置页就会出现开关。
4. 在 `app/fetchers/__init__.py` 的 `build_fetchers` 里按开关挂上。
5. 给解析函数加一个 fixture 测试。

抓取器抛出的异常会被记到日志里并跳过。RSS 是现成的通用来源，只是临时加一个博客时不用写代码，在设置页加一行地址就行。

## 目录

```text
app/fetchers/     各来源的抓取和解析
app/ranking.py    打分
app/summary.py    摘录、模型摘要和今日简报
app/digest.py     早报正文
app/notifiers.py  邮件和各机器人
app/pipeline.py   抓取入库、生成推送
app/scheduler.py  每天定时
app/cli.py        命令行
templates/        页面
tests/fixtures/   录制的响应样本
```

## 微信小程序（新增）

原生客户端位于 `miniprogram/`，使用 `/api/v1/news`（筛选与分页）和 `/api/v1/news/{id}`（详情）。共享当前资讯、偏好、屏蔽词和摘要缓存；仅公开白名单字段，阅读不调用模型。列表在最近 500 条候选中排序并明确返回截断标识，单页最多50条。

支持早报阅读、搜索/来源/时间筛选、收藏和分享。导入方式、域名要求和未实现范围见 [小程序说明](miniprogram/README.md)。原网页、管理、抓取及推送不变。小程序收藏仅保存在设备，当前不接入微信登录与订阅消息。私有站点 API 返回401，不绕过原有保护。
