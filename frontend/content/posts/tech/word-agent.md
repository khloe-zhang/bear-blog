---
title: "用 Coze Agent 批量修改 Word 文档格式"
author: ["Bear"]
date: 2026-01-25T17:00:00+08:00
keywords: 
- AI
- Agent
categories: 
- tech
tags: 
- AI
- Agent
description: "把 Word 文档丢给 Agent，直接说要排版成什么样式，一步到位改完，省时省力省鼠标！"
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
    image: "posts/tech/word-agent/workflow.png"
    caption: "" # 图片底部描述
    alt: ""
    relative: false
---


已经在新公司实习一个多月了，前几周一直在跟各种 word 文档打交道，很多时间花在了编辑格式上。一些项目设计文档和投标文件都有严格的样式要求，比如各级标题、字体缩进、表格、序号等，手动调整非常费时。这时就想到能不能用一个 Agent 来解决呢？可以直接在对话框里跟它说要批量改成什么样式，把文件传给它，然后直接返回修改后的文件，省时省力省鼠标（我已经干废一个鼠标左键了，损耗太快）。

我选择的平台是 Coze（扣子），文件中转使用了火山引擎的 OSS。虽说现在好像 Dify 更流行，有更多企业级兼容的组件，但我这个使用场景用 Coze 已经足够了，而且我更喜欢 Coze 的界面风格。

# Agent 配置

用户进入对话框时，会有默认招呼语：“你好，我是Word格式大师，帮助您高效调整文档格式问题，包括标题、缩进和表格样式等。请上传你要修改的Word文档。”

## 人设与提示词

对于整个Agent，给的人设提示词如下。根据调试期间观察Agent的思考，发现仅在工作流节点中限制条件有时没有作用，Agent还是会想很多，然后陷入死循环；因此，在提示词中也给Agent提供了如何应对不同用户输入的指引。
```
你是Word格式大师，是一个专注于调整文档格式的智能体。你能够处理各级标题设置、文本缩进、字体字号调整以及表格格式优化等工作。
如果用户上传了文档给你，并用提示词告诉你格式调整的要求，你要按照工作流的配置来调整格式并输出文件。
如果用户只是输入了提示词而没有上传文档，那么只要回答用户的问题就可以了。
```

在 Playground 调试阶段，记得要把“深度思考”模式打开，便于查看思考流程来调试。

## 模型与参数


# 工作流配置

Coze 作为低代码 Agent 平台，天然的优势就是拖拉拽式的工作流编排界面。初始界面已经有开始和结束节点，需要新建中间的各节点，然后连线起来。

在构思时，我认为用户输入会有两种类型：
1. 提示词（文本）+ Word文档（文件）
2. 提示词（文本）

第二种类型，“用户只输入了文本提示词”，又分为两种可能，一个是用户只顾着提出格式要求，忘了上传自己的文件（非常有可能）；另外就只是单纯想问某个格式应该怎么调整。对于这两种可能，模型都会用文字来回答，在末尾时会补上一句“请上传你的文档，我可以帮你做这些修改”，这样就可以兼容两种可能了。

基于这样的设定，我的节点设计示意图如下：

[流程图]() （待添加）

首先会通过一个条件判断节点，根据用户是否上传了文档，来判断是否要进入关键的脚本插件，或者是仅做文字回答；如果有文档，那就用一个模型将用户的自然语言要求转化为 JSON，然后将 JSON 传递给脚本插件节点；脚本插件会根据 JSON 规则来运行这些修改函数，然后把最终修改好的文件发回给用户，流程结束。

由于“用户要上传文档”才是这个Agent设计的初衷，也是大部分用户的使用场景，下面的介绍就基于这条支线展开。

## 节点0：开始

在开始节点中，配置 input 和 prompt 两个变量：input 为可选，类型为 File -> Doc；prompt为必填，类型为 String。

<figure>
  <div align=center><img src="/posts/tech/word-agent/start.png"  style="width: 50%; height:auto;" alt="开始节点"></div>
  <figcaption></figcaption>
</figure>


## 节点1：判断是否上传了文件

添加一个节点，选择“IF选择器”。在条件中，只要满足用户有同时传入 input 和 prompt 这两个条件，就进入主分支；否则，进入副分支（仅文字回答）。

<figure>
  <div align=center><img src="/posts/tech/word-agent/if.png"  style="width: 50%; height:auto;" alt="If判断节点"></div>
  <figcaption></figcaption>
</figure>

## 节点2：JSON 解析

来到第一个重头戏，用户对于格式修改的要求，如何把它从自然语言转化成标准的 JSON 格式，以便下一个节点的脚本读取？

这里有两个关键，首先设想好 JSON 格式的结构，比如是区分全局规则还是某章节下的局部规则，修改针对的对象是段落还是标题，定位的范围是哪里；对于每个规则属性，具体有哪些可修改对象，比如字体、段落、表格。然后，要想好如何在提示词中把这些传递给模型，最好在给出要求后，再给出针对各种情景的JSON样例，让模型学习。

对于修改范围，我定义了两个种类：global_rules（全局）和 operations（局部）。全局操作直接对整个文档应用用户的要求，而局部支持更细粒度的操作。

在 global_rlues 即全局规则之下，可以直接展开 actions 即操作，这里不直接体现 actions 这个字段。actions 可分为两种对象：对于 font 或对于 paragraph 的——平常我们在 word 里调格式的时候，操作也可以分为这两类，如调文本的字体、字号、颜色、加粗时，这就属于针对文本自身的 font；而需要调整行间距、段前缩进、段前段后空白的时候，这就属于针对段落的 paragraph。另外，关于表格 table 的属性，目前只支持全局修改，和各层级标题、正文一样，都可以在 global 的顶层字段里指定，可以修改表格整体对齐、是否自动调整列宽、是否自适应页面宽度、单元格文字对齐、边框。

在 operations 即局部规则之下，就比较复杂，需要指定 target、scope、actions 三个对象。

target 也就是限定局部范围的属性，在其中可以指定匹配类型 type（支持章节标题模糊匹配、标题精准匹配、按照标题层级匹配、段落包含的关键词匹配），这几种匹配的值对应输入到 value 中，大概长这样：
```
      "target": {
        "type": "section_title",
        "value": "第三章"
      },
```

scope 指定了作用范围，也就是该目标下的哪些内容，可以选择标题那一行文字本身、该标题下的所有内容（直到下一个标题为止）、按关键词匹配时的包含关键词的段落。

actions 就跟全局规则中一样，分为针对 font 文字本身的、针对 paragraph 段落的，然后展开细致的操作指令，字号颜色间距等等。

看完上面的规则，如果你感觉一头雾水，也可以看我的最终提示词，在末尾给出了三种类型的解析案例：
```
你是一个 Word 文档格式解析器。请将用户对文档格式的要求，严格转换为以下嵌套 JSON 结构。

### 输出结构说明
你的输出必须是一个对象，包含以下两个可选字段：
1. `global_rules`：用于全局样式
2. `operations`：用于局部精准编辑

> 如果用户只提全局要求（如“所有正文用小四”），只输出 `global_rules`  
> 如果用户指定章节/段落（如“第三章正文改12号”），只输出 `operations`  
> 如果两者都有，则同时输出

### 一、global_rules（全局规则，可选）
- 顶层字段只能是：`heading_1`、`heading_2`、`heading_3`、`heading_4`、`body`、`bullet_list`、`ordered_list`、`table`
- 每个字段值为对象，包含 `font` 和/或 `paragraph` 子对象

### 二、operations（局部操作列表，可选）
- 是一个数组，每项代表一条精准编辑指令
- 每项必须包含：
  - `target`：定位目标（描述要修改哪里）
  - `scope`：作用范围（该目标下的哪些内容）
  - `actions`：要应用的样式（结构同 `global_rules` 中的值）

#### target 对象
- `type`（必填）：定位类型，可选值：
  - `"section_title"`：模糊匹配章节标题（如“第三章 功能清单”或“第三章”都能匹配到第三章）
  - `"heading_text"`：精确匹配任意标题文本（如“4.1 系统架构”）
  - `"keyword_in_paragraph"`：段落包含关键词（如“注意：”）
  - `"all_headings_of_level"`：所有某级标题（需配合 `level` 字段）
- `value`（必填）：具体值（如 "第三章 功能清单"）
- `level`（可选）：当 type="all_headings_of_level" 时，指定层级（1=一级标题）

#### scope（必填）
- `"this_heading_only"`：仅修改标题本身的文字
- `"paragraphs_under_heading"`：修改该标题下的所有后续正文（直到下一个同级或更高级标题）
- `"this_paragraph_only"`：仅当前段落（用于 keyword 类型）

#### actions（必填）
- 结构与 `global_rules` 中的值完全相同，包含 `font` 和/或 `paragraph`

---

### 支持的属性

#### font 对象可包含：
- `name`：字体名称（字符串，如 "微软雅黑"）
- `size`：字号（数字如 12，或中文字号如 "小四"）
- `color`：颜色（颜色名如 "red"，或十六进制如 "#FF0000"）
- `bold`：是否加粗（布尔值）
- `italic`：是否斜体（布尔值）
- `underline`：是否加下划线（布尔值）

#### paragraph 对象可包含：
- `alignment`：对齐方式（"left"、"center"、"right"、"justify"）
- `first_line_indent_chars`：首行缩进字符数（数字，如 2）
- `line_spacing`：行距（数字，如 1.5）
- `space_before`：段前间距（单位：磅，数字；若用户说“X行”，请转换为 X × 12 磅）
- `space_after`：段后间距（单位：磅，数字；若用户说“X行”，请转换为 X × 12 磅）

#### table 对象可包含：
- `autofit`：是否自动调整列宽（布尔值）
- `prefer_full_width`：是否将表格宽度拉伸至页面可用宽度（布尔值，优先级高于 autofit）
- `alignment`：表格整体在页面中的对齐方式（"left"、"center"、"right"）
- `cell_alignment`：单元格内文字对齐（对象，见下方）
  - `horizontal`：水平对齐（"left"、"center"、"right"）
  - `vertical`：垂直对齐（"top"、"middle"、"bottom"）
- `borders`：表格边框样式（"all" 表示所有框线，"none" 表示无框线）


---
### 示例（用户输入 → 你的输出）

#### 示例 1：纯全局规则
用户说：“标题用黑体小四红色，居中；正文用宋体五号，首行缩进2字符，1.5倍行距”

输出：
{
  "global_rules": {
    "heading_1": {
      "font": {
        "name": "黑体",
        "size": "小四",
        "color": "red"
      },
      "paragraph": {
        "alignment": "center"
      }
    },
    "body": {
      "font": {
        "name": "宋体",
        "size": "五号"
      },
      "paragraph": {
        "first_line_indent_chars": 2,
        "line_spacing": 1.5
      }
    }
  }
}

#### 示例 2：精准局部编辑
用户说：“把‘第三章 功能清单’下面的所有正文改成12号字”

✅ 输出：
{
  "operations": [
    {
      "target": {
        "type": "section_title",
        "value": "第三章 功能清单"
      },
      "scope": "paragraphs_under_heading",
      "actions": {
        "font": {
          "size": 12
        }
      }
    }
  ]
}

#### 示例 3：混合指令
用户说：“全文小四；另外，第三章的正文要12号字”

✅ 输出：
{
  "global_rules": {
    "body": {
      "font": {
        "size": "小四"
      }
    }
  },
  "operations": [
    {
      "target": {
        "type": "section_title",
        "value": "第三章"
      },
      "scope": "paragraphs_under_heading",
      "actions": {
        "font": {
          "size": 12
        }
      }
    }
  ]
}

---
### 重要提醒
- 如果用户未提某类样式（如没说标题），则省略对应字段
- 模糊匹配即可：用户说“第三章”，但实际标题是“第三章 功能清单” → `value` 写 "第三章" 即可（插件会模糊匹配）
- 输出必须是合法 JSON，不要包含任何解释文字
```


## 节点3：Python-docx 插件（核心）
一开始，我的插件是在 Coze 自带的 IDE 沙箱中运行的，自带的 IDE 里还可以手动添加各种依赖库，对于一个简单的 MVP(最小化可行产品) 来说，IDE 也够用了，还不用部署自己的服务器。不过后来为了体现我会搭 MCP，又把脚本包了一层上到阿里云 Serverless 里。现在先展示整体的脚本逻辑。

我的插件是基于 python-docx 这个库开发的，里面已经内置了各种可以针对 docx 操作的各种函数，我需要根据我的功能来定制包装成自己的函数。

首先需要安装的依赖库：cozepy（Coze IDE需要，MCP不需要）、docx、python-docx、requests（用于下载原始文件）、runtime（用来定义 handler 函数参数类型的，包含输入输出结构和日志工具等）、tos（火山引擎OSS）。

（未完待续）