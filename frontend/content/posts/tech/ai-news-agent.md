---
title: "用 ReAct Agent 搭建专属读报小秘书"
author: ["Bear"]
date: 2026-02-21T15:42:00+08:00
keywords: 
- AI
- Agent
categories: 
- tech
tags: 
- AI
- Agent
description: "使用 LangChain 搭建 ReAct Agent，抓取多源 AI 资讯并总结每日新闻简报，推送到企业微信群聊。"
weight:
slug: ""
draft: false # 是否为草稿
comments: true
reward: false # 打赏
mermaid: false # 是否开启mermaid
showToc: true # 显示目录
TocOpen: true # 自动展开目录
hidemeta: false # 是否隐藏文章的元信息，如发布日期、作者等
disableShare: true # 底部不显示分享栏
showbreadcrumbs: true # 顶部显示路径
cover:
    image: "posts/tech/ai-news-agent/cover.jpeg"
    caption: "" # 图片底部描述
    alt: ""
    relative: false
---


在干这份实习的时候，以及去年下半年找工作的时候，都经常被问到：“AI行业最近有啥新消息？有啥新玩意出来了？”但当时总是忙着工作的杂活，或者忙着准备面试本身，根本没想起来去各大网站公众号读一读最近的新闻，显得我很落伍。最近空闲下来了，想要尝试搭一个 Agent，用来干点啥好呢？—— 不如就搭一个可以帮我读新闻的小助手吧！每天把我常看的几个AI资讯网站都拉下来，把最值得看的主题总结成简报，微信推送给我。这样一来，只要微信有消息提醒，我就会想起来要看新闻；另外，还能治好我的“太长不看”综合症，我只要读个一百来字的简报，有感兴趣的再点链接读原文就好了。

此外，这个 Agent 并不是单纯的自动化工作流，没有按照编排死的顺序去爬虫+汇总，我加入了一些让 Agent “更像人” 的逻辑：设定我感兴趣的关键词，让AI综合我的偏好以及它自己的思考，来判断某条新闻是否值得推送；另外，由于新闻来自于多个网站，有可能出现某热点事件被重复报道的情况，还需要 Agent 去判断几条新闻是否主题相同，如重复就进行合并汇总；如果最终推送的数量过少，还会返回全部新闻去重新挑选几条来补上。

至此，我的项目目标如下：
- 每日自动聚合主流 AI 媒体新闻（机器之心、新智元，还有更多正在赶来的路上）
- 基于用户偏好关键词智能筛选
- 自动去重、事件合并、每条新闻生成 150 字精炼摘要，共 3 条新闻作为简报
- 推送到企业微信群聊（普通微信容易被封号）

# 工作流程图
定时触发 → 理解任务 → 抓取标题 → 筛选 → 去重 → 抓取全文 → 摘要生成 → 推送并备份到本地

理解任务：识别出需要处理两个新闻源；
获取候选新闻：调用 RSS 爬虫，拿到最新文章列表；
筛选重要新闻：根据用户偏好关键词（如“大模型”“机器人”）打分排序；
去重合并：判断相似新闻是否属于同一事件，避免重复；
抓取全文：对选中的新闻，获取完整正文；
生成摘要：为每篇新闻写一段 150 字左右的专业摘要；
整合输出：将所有摘要合并成一份结构清晰的每日简报。


# 环境配置
各种包的版本，docker，docker-compose

# 项目代码目录结构
<span style="font-size:14px; line-height:0.5">
ai_daily_briefing/ <br>
├── run_daily.py                # 主程序，初始化 ReAct Agent 并执行 <br>
├── agent_tools.py              # 6 个细粒度 ReAct 工具，提供给 Agent 调用 <br>
├── skills/ <br>
│   ├── fetch_rss.py           # 抓取RSS页面的有效信息 <br>
│   ├── fetch_headers.py       # 抓取标题+链接 <br>
│   ├── fetch_full_content.py  # 按需抓取全文 <br>
│   ├── title_matcher.py       # 判断两个新闻标题是否属于同一事件 <br>
│   ├── article_reranker.py    # 根据标题评估新闻的重要性，选出最值得推送的 <br>
│   └── summarize.py           # 为单篇新闻生成摘要 <br>
├── sources/ <br>
│   ├── jiqizhixin.py          # 封装机器之心爬取逻辑 <br>
│   └── newzhiyuan.py          # 封装新智元爬取逻辑 <br>
├── utils/ <br>
│   ├── clean_html.py          # 清理机器之心 RSS 中的 HTML 内容，去除格式乱码和无用标签 <br>
│   ├── qwen_client.py         # 千问 API 的调用逻辑 <br>
│   ├── redis_client.py        # 配置 Reids 客户端 <br>
│   ├── save_report.py         # 把简报作为 markdown 文件备份保存到本地的文件夹 reports <br>
│   └── wechat_bot.py          # 企业微信推送 <br>
├── reports/ <br>
├── dockerfile <br>
├── docker-compose.yml <br>
├── .env                       # 环境文件，包含 API key，上传 Github 时要用 .gitignore 忽略 <br>
└── requirements.txt <br>
</span>

# 新闻数据源 Sources
我把每个网站来源的爬虫逻辑单独放在 Sources 文件夹中，以便后续再加新的网站时快速按照来源管理。我的 Agent 逻辑是：先把所有来源的新闻标题都汇总到一起，通过阅读标题来筛选出值得推送的文章，然后只去爬这几篇文章的全文即可；而那些被淘汰掉的文章，只要爬取到标题为止就可以了。因此，在爬虫阶段，“标题+链接” 与 “全文” 两种爬取逻辑需要做分割。

## 机器之心
### 啥是 RSS？
我在网上找到了机器之心的RSS订阅源。好古早的名词 —— RSS 英文全称 Really Simple Syndication 非常简单的内容聚合，人如其名，也就是以非常简单的 XML 格式把网站的内容展示出来，不用受到格式的干扰。RSS 的订阅源叫做 RSS feed，它本质上是一个结构化的数据文件，通常以.rss、.xml或.rdf为后缀，它会随着网站本体实时更新内容。只要有这个 RSS feed，就可以在不打开网站的情况下从 feed 中拉取到网站实时更新的内容，可以通过阅读器将多个 RSS 源整合到一起，定制自己的电子书架。国外的许多资讯网站会在页面附上官方的 RSS feed，旁边会有一个橙色信号状的 Logo；而国内的网站近些年来很少提供官方 RSS，比如我要爬的机器之心和新智元，都转向了付费订阅制，盈利模式驱使下 RSS 只能退出主流舞台。但，高手在民间，只要用心搜索，就能找到网上各路大神自制的 RSS 源大合集。关于 RSS 的兴衰，我找到了一篇写得很好的文章，感兴趣可以阅读：[为什么现在没人用 RSS 了？RSS 的兴衰与互联网理想的消逝](https://www.dayanzai.me/the-disappearing-rss-subscription.html)

我为机器之心的RSS单独写了一个脚本，放在 Skillls 文件夹中，作为 Agent 的能力之一。RSS 的格式比较固定，因此只要分析好内容的层级，就可以顺滑地提取了。这个 RSS feed 非常靠谱，里面不仅有文章标题、链接，还有全文，只需要一些简单的清洗，就可以用这一个 RSS 链接爬到所有需要的内容。相比于其他网站的爬取首页-逐条新闻爬取，简单很多。

以下是这个RSS爬虫需要的库：
```python
import requests  # 用于 HTTP 请求头，向网站发送访问请求
import xml.etree.ElementTree as ET   # Python 内置的 XML 解析库
from typing import List, Dict  # 导入类型注解，用于函数签名
```

定义一个函数 def fetch_rss_news(feed_url: str, limit: int = 12) -> List[Dict]，接收 RSS feed 的 URL，最多提取12条新闻，输出一个列表，里面每篇文章作为一个字典。

相比于普通的HTML提取，对于RSS来说，还存在一个“命名空间”的概念。因为 RSS 要做的事是多源聚合，多个不同来源的 XML 文件里可能会有相同的扩展标签名，如果无法区分所属的来源，场面就会变得十分混乱。命名空间的意义就是区分不同来源的相同扩展标签名。除了 RSS 2.0 标准定义下的 title、link、description 已经在默认命名空间里，能够直接提取，其他的自定义扩展标签名都需要经过命名空间才能正常提取。

```python
# 解析 RSS
root = ET.fromstring(xml_text)
# 注册 content 命名空间，这个URL就在RSS页面的顶部
ET.register_namespace('content', 'http://purl.org/rss/1.0/modules/content/')
```

针对XML标签，逐层提取内容。首页所有的文章都被包裹在大的标签 \<channel> 里；每篇文章最外层的标签是 \<item>，包裹着标题 \<title>，发布日期 \<pubDate>，文章真实链接 \<link>，正文 \<content> 则是在 \<content:encoded> 这个命名空间里，不能单纯提取，而需要解码。

```python
items = []
# 先找到所有 <channel>，再找其中的 <item>
for channel in root.findall('channel'):
    items.extend(channel.findall('item'))
for item in items[:limit]:
    def get_text(tag): # 定义辅助函数 get_text()，安全获取标签文本
        elem = item.find(tag)  # 寻找 <item> 之中的其他 tag
        return elem.text.strip() if elem is not None and elem.text else "" 
    # 获取标题链接和发布日期
    title = get_text('title')
    link = get_text('link')
    published = get_text('pubDate')
    
    # 关键：提取带命名空间的 <content:encoded>内容，格式：{命名空间URI}标签名
    # http://purl.org/rss/1.0/modules/content/ 就是 content 模块的标准命名空间
    content_elem = item.find('{http://purl.org/rss/1.0/modules/content/}encoded')
    content_html = content_elem.text if content_elem is not None and content_elem.text else "" # 获取完整的 HTML 内容
    
    clean_text = clean_html_content(content_html) if content_html else "" # 用清理函数清掉冗余的标签，清理函数在utils文件夹中
    
    # 爬取到的内容存到 articles 字典中
    if title and link:
        articles.append({
            "title": title,
            "link": link,
            "published": published,
            "content": clean_text
        })
return articles
```
最后这个函数返回的格式如下：
```python
[
    {"title": "文章标题1", "link": "...", "published": "...", "content": "..."},
    {"title": "文章标题2", "link": "...", "published": "...", "content": "..."},
    ...
]
```

### 分割标题与全文爬虫
上面提到，标题与全文的爬虫逻辑需要分割开，就算这里 RSS 已经能一次性获取标题和全文，但为了与其他网站的传统爬取模式保持一致，这里也把机器之心 RSS 的标题和全文爬虫封装成两个不同的函数。另外，返回的 articles 对象里，还要加上 source 这个属性，以便在按需爬取全文时，区分使用哪个源的爬取逻辑。
```python
# sources/jiqizhixin.py
from skills.fetch_rss import fetch_rss_news  # 上面定义的RSS爬虫函数
JIQIZHIXIN_RSS = "https://www.jiqizhixin.com/rss"
def get_jiqizhixin_headers(limit: int = 12):
    """获取标题+链接（其实有全文，但为统一接口）"""
    articles = fetch_rss_news(JIQIZHIXIN_RSS, limit=limit)
    return [{"title": a["title"], "link": a["link"], "source": "jiqizhixin"} for a in articles]

def get_jiqizhixin_full_content(link: str):
    """用标题作为查找索引，直接返回全文（从RSS已抓取的数据中查）"""
    articles = fetch_rss_news(JIQIZHIXIN_RSS, limit=12)
    for a in articles:
        if a["link"] == link:
            return a["content"]
    return ""
```
这里的 `get_jiqizhixin_headers` 到后面还会与新智元的标题获取函数封装到一起，形成一个爬取所有来源新闻标题的工具，给 Agent 用。


## 新智元
本来想着跟机器之心一样用RSS来抓新智元的内容，无奈没有找到靠谱的feed，只好用最原始的办法，requests 伪装请求头，爬网站的 HTML，再用正则化提取标题和正文。 
### 爬网站首页
```python
# sources/xinzhiyuan.py
# 省略 import re json requests html List Dict
def _fetch_raw_html(url: str, timeout: int = 10) -> str:
    """直接用requests抓取原始 HTML，伪装请求头防止被网站屏蔽"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.baidu.com/"
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"抓取 {url} 失败: {e}")
        return ""

def _extract_articles_from_html(html: str) -> List[Dict[str, str]]:
    """从原始 HTML 提取出标题和链接"""
    articles = []
    # 正则：匹配带有 rel="bookmark" 的 <a> 标签
    # 示例：<a href="https://aiera.com.cn/2026/02/11/other/aiera-com-cn/84094/anthropic%e6%/" rel="bookmark">Anthropic最新2026趋势报告：人类最大一次编程革命势不可挡</a>
    # 支持单引号或双引号；非贪婪匹配标题文本
    pattern = r'<a[^>]+href=["\']([^"\'>]+)["\'][^>]*rel=["\']bookmark["\'][^>]*>([^<]{10,}?)</a>'
    # 正则里有两个捕获组，包围在圆括号里，一个负责捕获链接，一个负责捕获文字标题
    matches = re.findall(pattern, html, re.IGNORECASE)
    for link, title in matches:
        title = title.strip()
        articles.append({
        "title": title,
        "link": link,
        "source": "xinzhiyuan"
    })
    return articles
```

### 封装标题与正文爬虫
仍然是在 sources/xinzhiyuan.py 里：
```python
def get_newzhiyuan_headers(limit: int = 8) -> List[Dict[str, str]]:
    """调用刚才写好的爬虫，获取新智元最新文章标题和链接"""
    html = _fetch_raw_html(XINZHIYUAN_HOME)
    articles = _extract_articles_from_html(html)
    return articles[:limit]

def _extract_article_content(html: str) -> str:
    """获取全文内容"""
    if not isinstance(html, str) or not html.strip():
        return ""
    
    match = re.search(
        r'<article[^>]*class=["\']post-content["\'][^>]*>(.*?)</article>',
        html,
        re.DOTALL | re.IGNORECASE
    )
    
    if not match:
        match = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
    
    if not match:
        return ""
    
    content_html = match.group(1)
    content_html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', content_html, flags=re.DOTALL)
    content_html = re.sub(r'</?(p|div|br)[^>]*>', '\n', content_html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', content_html)
    return re.sub(r'\s+', ' ', text).strip()

def get_newzhiyuan_full_content(link: str) -> str:
    '''调用刚才写好的函数，先获取原始 HTML，然后从中抓取正文'''
    html = _fetch_raw_html(link, timeout=10)
    content = _extract_article_content(html)
    return content[:5000]
```

## 合并多源的标题和全文工具
对于我的 Agent 小秘书，如果把上面这些繁琐的爬虫接口分开给它，实在是太麻烦了，能不能组装一下呢？最终决定只给两个工具：爬标题，爬全文。
```python
# skills/fetch_titles.py
def fetch_titles_from_source(source: str, limit: int = 100) -> List[Dict]:
    """
    从指定数据源抓取新闻标题和链接
    Args:
        source: 数据源名称，可选值: "jiqizhixin" 或 "xinzhiyuan"
        limit: 抓取条数限制，默认100（实际会抓取所有可用新闻）
    Returns:
        文章列表，每个元素包含 title, link, source 字段
    """
    if source == "jiqizhixin":
        articles = get_jiqizhixin_headers(limit=limit)
        return articles
    elif source == "xinzhiyuan":
        articles = get_newzhiyuan_headers(limit=limit)
        return articles
    else:
        raise ValueError(f"未知的数据源: {source}，支持的值: 'jiqizhixin' 或 'xinzhiyuan'")

# skills/fetch_full_content.py
def fetch_full_content(source: str, link: str) -> str:
    """
    从指定数据源抓取新闻全文内容
    Args:
        source: 数据源名称，可选值: "jiqizhixin" 或 "xinzhiyuan"
        link: 新闻链接
    Returns:
        新闻的全文内容文本，如果抓取失败返回空字符串
    """
    if not source or not link:
        return ""
    
    try:
        if source == "jiqizhixin":
            content = get_jiqizhixin_full_content(link)
            return content if content else ""
        elif source == "xinzhiyuan":
            content = get_newzhiyuan_full_content(link)
            return content if content else ""
        else:
            print(f"未知的数据源: {source}")
            return ""
    except Exception as e:
        print(f"抓取 {source} 的全文内容失败 ({link}): {e}")
        return ""
```
到这里为止，获取新闻数据的工具就已经准备好了。

# LangChain
说了这么多终于进入重头戏！Agent 是基于 LangChain 搭建的。LangChain 就是一个用于开发 LLM 应用的框架，内置各种组件和工具，让开发者可以去组织多步骤的模型推理、接入外部数据、管理上下文等等动作，最终造出来一个 Agent，利用这些步骤（Chain）和组件（Component）去执行具体的任务。这里的 Chain 是 LangChain 的核心概念，一个 Chain 就是将多个模块串起来完成一系列操作，可以将上一步操作的结果交给下一步去执行，就跟环环相扣的链子一样，非常形象。

LangChain的主要库：
- langchain-core：定义通用的接口和工具，是其他模块的基础，确保模块之间能够兼容和连通。主要组件有 Runnable（核心执行接口，所有链、代理和工具都基于此抽象）、PromptTemplate（提示词模板）、OutputParser（解析语言模型的输出，如 JSON、列表、结构化数据）、Callbacks：用于监控和调试执行过程，支持日志记录、性能分析等。
- langchain：本体主包，包括核心功能模块，依赖于 langchain-core，主要的子模块有 LLMs（与语言模型交互的接口，如 OpenAI、Hugging Face）、Memory（管理对话上下文的模块）、Chains（组合提示、模型和其他组件的工作流）、Agents（动态决策和工具调用的模块）、Tools（外部工具接口）。
- langchain-community：社区贡献的第三方扩展模块，可用于向量存储、文档加载、网络搜索等，也可以集成第三方模型。

还有一些根据模型厂商定制的库，如 langchain-openai、langchain-huggingface、langchain-google-genai 等，专门用于集成厂商的模型，或者是 HuggingFace 里的开源和嵌入模型。这些库需要单独安装才能用。我在项目里就用到了 langchain-openai，虽然我调的是 Qwen 的 API，但阿里提供的是兼容 OpenAI v1 的接口，请求、响应的字段格式都遵照 OpenAI 的规则来。

## ReAct Agent 以及其他类型 Agent 对比
LangChain Agent 有多种类型，我选的是 ReAct 这个框架，它的核心思想是：Reasoning + Action（推理 + 行动），Agent 运行的时候会遵循 思考 → 行动 → 观察 → 再思考 的路线。如果把 ReAct Agent 的思考过程显式打印出来，就会是这样：
```
Thought: 我需要先获取新闻列表...
Action: fetch_rss_news_tool
Action Input: {"source": "jiqizhixin"}
Observation: ✅ 获取到 20 条新闻
Thought: 现在我要筛选出最重要的 3 篇...
...
```
ReAct Agent 在每个工具之间的传递时，只接收单个字符串，因此如果有多个参数如字典或列表，需要在接收后用其他方式转化成目标格式。

ReAct Agent 的好处就是 Agent 思考的过程是透明的（好像三体人），因此行为的可解释性强；另外，对 LLM 的模型能力要求也不高，只需要它会根据提示词思考和写句子就行，能力一般的、支持思考模式的文本模型都能做到。缺点就是，步骤多时 token 消耗大，而且不能并行调用多个工具。不过我的任务步骤明确、工具调用串行（每步都依赖于上一步完成的结果，不需要同时进行），并且逻辑不是很复杂，所以这些缺点都可以接受。鉴于我的 Agent 还在搭建初期，非常想看到它的思考过程，如果卡在哪个点上，也方便我对症下药去调试，因此 ReAct 就是我的首选。

此外比较流行的还有 Function Calling Agent，LLM 会直接冷酷地读取任务，按需输出一个结构化函数的工具调用请求（JSON），然后直接执行对应工具，结果返回给 LLM 继续处理，不会生成自然语言指令，比较节省 Token，同时也支持多种工具并行调用；但是需要 LLM 模型本身支持这种 Function Calling 能力，如 GPT-4、Qwen-Max/Turbo，并且没办法看到思考过程，不利于调试。

Plan-and-Execute Agent（规划-执行型）就更高级些，工作流程分为 Planner 和 Executor 两步骤。对于 Planner，LLM 会生成一个全局任务计划（如 “Step1: 抓新闻；Step2: 去重；Step3: 摘要…”）；然后来到 Executor，逐个执行计划中的子任务（每个子任务可是一个 mini-Agent）。这两步完成后，Agent 还会视情况决定是否需要 Re-Plan，结合原始目标、初始计划和已执行步骤的结果，判断是否需要继续执行后续步骤，或是否需要更新计划，形成 “规划-执行-反馈-调整” 的动态循环。这类型的 Agent 因为提前做了全局计划，所以更具备长期视角，避免了单步思考可能导致的方向偏差，不容易陷入死胡同。它适合复杂任务，对 LLM 规划能力要求高，但我的任务流程比较固定，不需要 LLM 在规划上做太多发散性思考，所以也不选择它。

下面先开始配置 Agent 的工具能力，身体各部位的内容都填好后，再来用 creat-agent 去正式[组装 Agent](#构建和运行-ReAct-Agent)。

## 模型与提示词
我为 Agent 选择的大脑——也就是模型，都是来自阿里的通义千问家族。核心思考能力用 Qwen-Plus，次要的能力用 Qwen-Turbo。现在阿里云百炼平台有新用户优惠，免费送一百万 Token，羊毛必须薅到。但最好在控制台里，去把“超出免费额度后自动停用”这个功能打开，我们的宗旨就是不花一分钱。

这里介绍 Qwen 家族的模型能力对比，最强的是 Max，其次是 Plus，然后是 Turbo、Flash。Coder 用于 Vibe Coding，可以去 Claude Code 中配置。

hub.pull("hwchase17/react") 是一个官方推荐的提示词模板。

在让小模型来评估新闻的价值时，用的提示词：
```python
prompt = f"""你是一位AI科技媒体的编辑，需要从以下新闻标题中选择最值得推送的 {target_count} 条新闻。

评估标准（请综合考虑以下所有因素）：
1. 新闻的重要性和影响力（技术突破、行业动态、重大发布等）
2. 与AI、大模型、智能体等核心领域的相关性
3. 时效性和热点程度
4. 对读者的价值和吸引力
5. **用户偏好关键词匹配度**：用户关注以下关键词，如果标题中包含这些关键词，应优先考虑：
   {keywords_text}

请综合考虑以上标准，从以下标题中选择最值得推送的 {target_count} 条，只返回对应的编号（用逗号分隔，例如：1,3,5）：
{titles_text}
```

## 核心能力（Agent Tools）
我在 Skills 这个文件夹的脚本里，把模型要做的动作都写好了（也就是 Python 函数）。现在需要根据我的产品逻辑，把这些动作组装起来，成为一个个的工具（Tool）交给模型去调用。
```python
# 在主程序 run_daily.py 中，定义工具集，告诉模型能用什么 Tool
tools = [
    fetch_news_from_source,      # 抓取机器之心和新智元当天的每篇新闻标题与链接
    rank_articles_tool,          # 评估新闻标题重要性，选择最值得推送的新闻（结合模型的思考与用户偏好）
    check_same_event_tool,       # 判断两个标题是否属于同一事件
    fetch_full_content_tool,     # 获取新闻全文内容
    ai_summarizer_tool,          # 生成单篇新闻摘要
    merge_and_summarize_tool     # 如两标题属同一事件，合并两篇新闻全文，生成综合摘要
]
```
之前我在 Skills 里教给模型的动作是：RSS抓取与解析、抓取标题、根据新闻链接抓取全文、标题重要性排序、事件去重判断、摘要生成，和最终的 Tools 大概一致，只有 RSS 作为机器之心专属的爬取逻辑，没有在工具中体现出来。此外，与 Skills 不同的是，Tools 还承担了解析和处理模型输入与输出的工作，以及处理缓存与错误异常，这些都不便放在单个的 Skills 里，因为 Skills 只要负责做它该做的动作就好了，以后有其他 agent 还可以直接复用，到时候再去写不同的输入输出逻辑。

下面是我 Skills 里的动作和最后 Tools 的对比，保存留档，供以后调试用：
| Tool | Tool 的功能 | 用了哪些 Skills |
| ---  | --- |  --- |
|fetch_news_from_source | 抓新闻的标题和链接 | fetch_titles.py 里面的 fetch_titles_from_source 根据数据源抓标题和链接|
|rank_articles_tool | 从所有标题里面选最好的3篇 | article_ranker.py 里的 rank_articles_by_importance |
|check_same_event_tool | 判断某两个标题是否属于同一事件 | title_matcher.py 里的 check_same_event |
|fetch_full_content_tool | 根据来源和链接获取全文 | fetch_full_content.py 里的 fetch_full_content |
|ai_summarizer_tool | 根据全文给单篇新闻生成摘要 | summarize.py 的 summarize_content |
|merge_and_summarize_tool | 读取两篇同主题新闻的全文后合并生成摘要 | summarize.py 的 merge_and_summarize |

## 其他工具函数（Utils）
清理RSS格式，Qwen API 调用封装，Redis 客户端封装，存档MD简报，Redis用户关键词配置，企业微信推送

## Redis
- 缓存对话历史（暂时停用），
- 已爬取过的 URL
- 用户偏好关键词
 
Redis 的作用是将 Agent 的记忆持久化。在 Agent 的读取全文逻辑里，我使用了 Python 的临时缓存，避免 Agent 在思考的时候把全文都读出来，节省 Token；然而临时缓存每次重启后会清空，如果要长期保存 Agent 的记忆，如上下文、用户偏好、对话历史，就需要让记忆持久化，Redis 就可以派上用场了。

首先，需要在 .env 文件里配置好 Redis 的端口，因为我的项目是本地运行，所以直接用 localhost，端口 6379。在 Utils 这个文件夹中，创建 Redis 客户端：
```python
# 从环境变量读取配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# 创建全局连接池
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True  # 关键：自动将字节转为字符串
)
```
然后还是在 Utils 文件夹里，设置用户偏好关键词，存到 Redis 里：
```python
# Redis 中的固定 key（无 user_id）
PREFERENCES_KEY = "global_news_topics"
DEFAULT_TOPICS = ["AI", "大模型", "Agent", "智能体", "阿里", "千问", "Qwen", "腾讯", "混元", "字节跳动", "字节", "豆包", "DeepSeek", "OpenAI", "微软", "Azure", "谷歌", "Google", "AWS", "英伟达", "具身智能", "机器人"]

def set_global_topics(topics: list):
    """由管理员设置全局关键词"""
    redis_client.set(PREFERENCES_KEY, json.dumps(topics, ensure_ascii=False))

def get_global_topics() -> List[str]:
    """获取偏好，此函数用于 rank_articles_tool，用户关键词作为输入之一"""
    data = redis_client.get(PREFERENCES_KEY)
    if data:
        return json.loads(data)
    return DEFAULT_TOPICS

def delete_global_topics():
    """清除用户偏好"""
    redis_client.delete(PREFERENCES_KEY)
```

### 已爬取过的 URL 去重
在 fetch_news_from_source 里，还加入了 Redis 判断某条 URL 是否已经被推送过的逻辑。每次筛选出的 3 条最好新闻决定推送后，在 rank_articles_tool 里把这三条 URL 都存入 Redis，设为 processed 已处理；等到下一次去爬取新闻的时候，就跳过这些已处理的 URL。【其实，是否在 summarize 的时候再标记为已处理更合适？因为筛选后还会去重，如果数量不够，模型会再返回去挑其他新闻，此时已经标记的就被去重掉了作废】
```python
# Redis URL去重过滤（只保留所有未处理的文章）
unprocessed_articles = []
for art in all_articles:
    link = art['link']
    # 检查 Redis 中是否存在该 URL
    if not r.exists(f"processed:{link}"):
        # 统一格式：确保所有文章都有 source 字段
        art.setdefault('source', source)
        unprocessed_articles.append(art)
    else:
        print(f"跳过已处理的新闻: {art['title']}")
```

```python
#标记选中的文章为已处理
for art in ranked:
    link = art['link']
    r.setex(f"processed:{link}", 604800, "1")
return ranked
```
### 用户偏好关键词


## 构建和运行 ReAct Agent
配置完刚才这些工具，接着一开始的 [ReAct-Agent-以及其他类型-Agent-对比](#ReAct-Agent-以及其他类型-Agent-对比) ，可以开始正式构建 Agent 的框架，以及尝试跑起来看看效果。

以下是构建 Agent 的代码：
```python
from langchain_openai import ChatOpenAI
from langchain_classic.agents import AgentExecutor, create_react_agent
from langchain_classic import hub
from langchain_core.prompts import PromptTemplate

# 获取 Prompt 模版 (使用 LangChain Hub 的标准模版)
base_prompt = hub.pull("hwchase17/react")

# 在 "Begin!" 之前插入我自定义的任务说明
new_template = base_prompt.template.replace(
    "Begin!", 
    """重要提示：
1. fetch_news_from_source 工具爬取的机器之心和新智元新闻都只包含标题和链接，如需全文请先使用 fetch_full_content_tool 获取，再生成摘要。
2. 使用 rank_articles_tool 可根据新闻标题评估是否值得推送
3. 在得到值得推送的标题后，去重逻辑：使用 check_same_event_tool 对于剩下标题两两组合判断是否报道同一事件。
   - 如果是同一事件：先获取两篇新闻的全文，然后使用 merge_and_summarize_tool 合并两篇报道并生成综合摘要。
   - 如果不是同一事件：分别使用 ai_summarizer_tool 为每篇新闻生成摘要。
4. 最终简报应包含3条不同的新闻主题，每条新闻一个150字左右的摘要，并在摘要后附上新闻的链接。

Begin!"""
)

# 把刚才插入的 Prompt 重新包装成一个新的 PromptTemplate 对象
prompt = PromptTemplate.from_template(new_template)

# 初始化兼容 Qwen 的 LLM
llm = ChatOpenAI(
    model_name="qwen3.5-plus",
    openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
)

# 构建 Agent
agent = create_react_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, handle_parsing_errors=True)
```

构建好了 Agent，还就需要一个新的函数做唤起它（invoke）的动作：
```python
def run_agent():
    current_date = datetime.now().strftime('%Y-%m-%d')
    result = agent_executor.invoke({ 
        "input": f"现在的日期是{current_date}，帮我整理机器之心和新智元的热点资讯，整理成简报。"
    })
    print("--- Final Result ---")
    return(result["output"])
```

加上保存MD文件到本地，以及推送企微的函数：
```python
def daily_job():
    print(f"🔔 定时任务启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    final_content = run_agent()
    if final_content:
        # 1. 本地保存为 MD 文件
        filepath = save_to_markdown(final_content)
        print(f"📖 本地报告预览已就绪: {filepath}")
        # 2. 企业微信推送
        webhook_url = os.getenv("WECHAT_WEBHOOK_URL")
        send_to_wechat_group(final_content, webhook_url)
        print("🏁 今日任务已圆满完成并推送。")
    else:
        print("⚠️ Agent 未生成任何内容，跳过推送。")
```

定时运行函数的逻辑：
```python
if __name__ == "__main__":
    #daily_job()  # 测试模式：如果想启动后立刻先跑一次，取消这一行的注释

    #设定每天 10:00 执行。如果是测试运行一次，就注释掉
    schedule.every().day.at("10:00").do(daily_job)
    
    print(f"⏰ 调度器已启动。当前系统时间: {datetime.now().strftime('%H:%M:%S')}")

    #保持定时检测程序运行的死循环，不能停。如果是测试运行一次，下面的就注释掉
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每 60 秒检查一次闹钟是否到点
```

# LangSmith 可观测


# 遇到的问题及解法
## 抓到的正文会显式思考，浪费 Token
使用临时缓存，不返回正文给 Agent，有需要时读取缓存
## LangChain Classic 库版本的迭代


# 未来加入功能
微信公众号文章的爬取——采用WeRSS工具
改用 LangGraph？
保存对话历史，读取历史以追踪某新闻主题的发展


