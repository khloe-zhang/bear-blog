---
title: "网站搭建技术总结（一）静态篇"
author: ["Bear"]
date: 2025-08-17T17:33:00+08:00
keywords: 
- web
categories: 
- tech
tags: 
- web
- AWS
- Cloudflare
- 网络安全
description: "搭建静态网页（页面样式、博客文章）用到的 Web 相关技术栈"
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
    image: "posts/tech/web-static/homepage.png"
    caption: "" # 图片底部描述
    alt: ""
    relative: false
---
# 写在前面

一开始搭建这个网站时，是想练习一下 AWS 云服务的操作，真正用 AWS 来上手做一点事情。2月份开始就有这个想法，当时花费很久部署了 EC2 + EBS + Github Actions，搭配 Flask 后端和 VUE 前端。整个过程非常之艰辛，不断有各种报错，由于蹭的是 AWS 的免费套餐，EC2 和 EBS 都有限额，经常遇到内存不足的报错。历经千辛万苦配置好了服务器，又找到了合眼缘的 VUE 模板，但由于 node.js 各种包的版本不兼容，配置前端也花了很多精力。然而此时网站还没有任何内容，只是准备环境已经精疲力尽，又要开始准备春招，所以项目搁置了好几个月。后果是，等我想要继续开始时，已经忘记之前做了些啥......当时每个步骤都在 Google Docs 里记录了，但现在看起来像天书，完全不记得每个步骤是在干什么。

我想也可能是因为一直没有看到一个初步的成果，自己也没有继续做下去的动力了。这次重新启动，第一要义是先做出一个可见的网站页面并且上线，尽量用简单的技术栈。经过思考，博客短期内应该只有静态内容，所以先用不到动态服务器，改用 S3 托管静态页面，配合 CloudFront CDN 内容分发，继续用 Github Actions 来做 CI/CD。另外前端需要找能够快速配置和上线的模板，不要再用 VUE。经过一番搜索，Hugo 和 Hexo 是两个比较流行的博客框架，其中 Hugo 是基于 Go 语言的，据说不容易像 node.js 一样报错多多，于是选择 Hugo。在[这个知乎问答](https://www.zhihu.com/question/266175192)里，找到了一个简洁又不失美观的模板，国内一个作者基于经典的 PaperMod 模板修改的 [sulv-papermod](https://github.com/xyming108/sulv-hugo-papermod)。最终（或者说阶段性的）效果也就是你现在看到的网站了。

PS：主题作者 Sulv 似乎现在没有继续维护自己的网站和代码了，其他教程里引用的他的初版使用指南，是发布在他的个人网站上的，链接已经失效。好在还有 Wayback Machine 这个神器，可以穿越回去看[原有的教程](https://web.archive.org/web/20230131002909/https://www.sulvblog.cn/posts/blog/build_hugo/)。

# 准备工作——买域名

开始搭网站之前，先把域名买上。都说买了装备才有动力干活，我在买下域名的当天就已一鼓作气上线了网站，速度感人。当然此前已经配置好了模板，并且尝试用 Github Pages 托管上线了，但发现页面在国内无法打开，还是得搭个正儿八经的基座。

首先我对比了两家域名服务商的价格，对于我的域名，AWS Route53 是 14 美金一年，CloudFlare 是 10 美金一年，续约同价。这里是常规的 .com 后缀的价格，如果想买 .net 或其他后缀似乎是另外的价钱。除了价格优势外，Cloudflare 还有方便部署的 HTTPS 和 SSL/TLS、DDoS、WAF 等安全服务。此外，据说 AWS 在中国大陆的 DNS 速度比较慢。综合看来，还是选择了 CloudFlare 买域名 + DNS 托管（其实两个可以分开，这里只是为了方便所以都用 Cloudflare 了）。买好域名后，就可以开始基础设施的配置了。 

# AWS S3

由于我的博客网站目前只有静态内容，本质上在访问时只是在加载一个个不同的 HTML 页面。因此，可以将这些 HTML 文件都上传到 S3 存储桶中，每次用户请求时，S3 会充当服务器，根据请求路径返回相应的 HTML 文件。

在这里先介绍一下 S3，全称为 Simple Storage Service。它是一种 ***面向对象的存储***（Object Storage），是因为它的核心设计理念和数据处理方式基于对象（Object）而非传统文件系统的块（Block）或层级目录（Hierarchy）。

那对象又是啥？每个文件（如图片、视频、HTML）存储都是一个独立的对象，每个对象里面包含几个内容：
- 数据本身（文件内容）
- 元数据（如创建时间、类型、自定义标签），也就是 Metadata
- 全局唯一标识符（也就是键Key，如 images/logo.png）。注意，尽管看起来像是一个有目录的路径，但仅作为标识符前缀使用，是逻辑分组而非目录层级。

对比传统文件系统，对象存储没有复杂的目录树结构，而是扁平化的键值存储（Key-Value）。

对象存储天然适合海量 ***非结构化*** 数据，如网站静态资源，且可无限扩展。

读到这里，似乎就能理解为什么 S3 的容器叫做“存储桶”了，它的 icon 也是一个小桶：不管是啥内容，先丢进桶里，不用分门别类一层层上架。等需要拿东西的时候，叫到号的再出来。

与之相对的，AWS 另一个存储服务 EBS 是**块存储**。某次面试就被问到这两者有什么区别，才发现只是知道这两个概念，不知本质有什么区别，怒而补之。存储块（Block），类似硬盘的原始数据块，可以挂载到 EC2 服务器实例，作为块设备。就像电脑主机与外接硬盘，但是虚拟版。这些“块”需格式化为文件系统（如 ext4）后才能存储文件，也支持文件系统操作（如 ls、cp）。它适合需要频繁读写、且数据 ***结构化*** 的应用（如数据库），延时更低，读写速度更快。

在可用性方面，S3 可以自动跨 AZ（Availablility Zone 可用区）复制，且存储本身按实际用量（存储量+请求量）收费，成本相对较低。EBS 则是在单个 AZ 内建立，需要手动建立快照来复制到其他区；并且它是按预分配容量付费，即使未用完也收费，成本相对较高。

对比之下，我的网站暂时不需要用到 PHP 动态效果和 SQL 数据库，所以选择 S3 更有性价比。对于比较复杂的业务网站，一般是两者结合使用，如：
- 动态网站：EBS 存代码+数据库，S3 存用户上传内容。
- 大数据分析：S3 存原始数据，EC2+EBS 运行计算集群。

概念就介绍到这里，下面讲讲我搭建 S3 的过程。

## 1. 创建存储桶

在控制台上找到 S3，新建存储桶，然后跟着指引操作就差不多了，注意需要取消“阻止所有公共访问”，确保存储桶公开可用。在创建后，来到存储桶的管理页，“属性”标签页翻到底，有“静态网站托管”这个功能，需要启用。在同一个设置页中，需要设定索引页与错误页，一般是 index.html 和 404.html，具体要看自己的 html 文件里是不是有这两个名字。索引页意味着在没有指定路径后缀的情况下，将默认访问的页面，一般是网站首页。404就是发生错误时的页面啦。

设置完成后可以看到生成了一个终端节点，形如 http://[存储桶名字].s3-website-[可用区名字].amazonaws.com ，表示现在的存储桶已经配置为一个可通过 HTTP 访问的静态网站。这个节点在之后的 Cloudfront 配置中还会用到。

接下来需要给存储桶设定权限。在“权限”标签页，“存储桶策略”以代码的形式定义谁可以对存储桶做哪些操作。详细代码在此不做展示，重点关注几条必要的权限：

- PublicReadForGetBucketObjects: 允许所有人公开读取 S3。
- AllowCloudFrontServicePrincipal: 如果只允许通过 Cloudfront 读取 S3 而避免直接向 S3 发请求，可以使用这个，不过还需要配置Cloudfront的 OAI（Origin Acess Identity），疑似现在已经升级成 OAC（Origin Access Control），详细可参考[限制对 Amazon S3 源的访问](https://docs.amazonaws.cn/zh_cn/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-s3.html)这篇文档。部署起来有些麻烦。


## 2. 将 HTML 文件上传到存储桶

在本地编辑好文件内容后，需要先用 Hugo 的命令将所有内容（md、css、图片以及其他config文件等）都生成为 HTML 文件。命令是：

```shell
hugo
```
（没错，就是这么简单。）
根据主题作者言：
> 输入 hugo 就可以生成 public 文件夹，可以部署到云服务器或者托管到 Github 上。<br/>
> 注意：输入hugo的生成方式只会往public文件夹里添加内容，但是不会删除外部已经不存在而public里面还存在的文件，
> 所以我一般用hugo -F --cleanDestinationDir命令，表示每次生成的public都是全新的，会覆盖原来的。

运行之后，工作目录下的 /public 文件夹中会出现我们需要所有的 HTML 文件。接下来就需要将这些文件上传到 S3 存储桶。

与 S3 交互的终端可以用 AWS CLI。下载安装后，需要先配置自己的 AWS 账户信息。

```shell
aws configure
（回车后，显示需要输入下面四个信息）
AWS Access Key ID [None]: <密钥ID，一般格式是AKIAxxxxxxxxxxxxxxx>
AWS Secret Access Key [None]: <密钥本身，是一长串大小写都有的字符，还有/斜杠>
Default region name [None]: <S3 所在区域>
Default output format [None]: json
```

这之后就可以运行下面的代码，把 public 文件夹里的内容上传到 S3：

```shell
aws s3 sync frontend/public/ s3://[存储桶名] --delete
```

注意这里的第一个路径，正常只要写 public/ 就可以了。我是因为项目没有直接放在仓库的第一层，而是放在了 frontend 文件夹里，所以写成这样。

为了节省时间，后续我配置了 Github Actions 自动化部署流程，每次在 Github 仓库更新并推送内容时，都会自动运行 hugo 生成 HTML 文件并上传到 S3。具体的内容请参考 [Github Actions](#github-actions-自动部署) 这一章节。

# AWS CloudFront CDN

初步完成了 S3 的配置后，就可以开始让 CloudFront 代理 S3 静态网站地址，并作为博客对外展示的地址（实际上也不会直接对外暴露地址，只是在 DNS 记录配置时，让域名跳转到 CDN 代理的地址）。作为全球分发网络 CDN，Cloudfront 可以将请求转移到离读者较近的数据中心（即边缘节点），提高访问的速度；并且如果内容已经在这个边缘节点缓存过，Cloudfront 也会直接返回缓存的内容，节省了直接发到 S3 的请求次数。

此外，S3 本身是无法直接搭配 HTTPS 的，默认是 HTTP 访问。想要一个更安全的站点，就需要通过 Cloudfront 来配置 HTTPS。

关于 Cloudfront 的更多介绍，可以参考[这篇 AWS 的博客](https://aws.amazon.com/cn/blogs/china/amazon-cloudfront-article/)（里面的配置示例图可以不用参考了，时过境迁控制台已经大变样）。

## 1. 创建分发（Distribution）

分发（Distribution）是 Cloudfront 运作的基本单元，拥有自己的 ID 和域名，以便后续用于 DNS 记录配置。在 Cloudfront 面板中，点击创建分发，然后配置以下几项：
- Origin：还记不记得刚才[创建 S3 存储桶](#1-创建存储桶)的时候生成的节点地址？[存储桶名].s3-website-[AZ 区名].amazonaws.com 搞里头。
- Settings：“源设置”和“Cache settings”都按默认勾选

创建好分发后，在“行为”标签页，设置行为“Redirect HTTP to HTTPS”（有点忘记了这是不是默认了，可以在创建完之后去确认一下）。同样在“行为”标签页中还有关于[缓存的配置](#缓存配置)，之后再讲。

Alternative domain name (CNAMEs) 需要配置为自己的域名，[域名].com 和 www.[域名].com 两个都需要加上。这一步似乎无法直接在创建分发的时候完成，提示让我稍后再加。于是创建完成后，在“常规”标签页的“设置”版块编辑中，找到 CNAME 一栏加上即可。同样在这个版块中，还有 [SSL 证书的配置](#2-https-与-tls-证书)，稍后一起说。

# Github Actions 自动部署

如果每次更新内容都要手动 hugo 生成 public 文件夹再上传到 S3，未免太麻烦。于是通过 Github Actions 设置一个自动化部署管道：每当我的仓库有新内容 commit 时，都会触发自动化部署流程，一站式帮我完成这些步骤，我只要管内容更新就可以了，这些部署和构建都会自动完成，好丝滑呀！

在项目的 Github 仓库中，先去 Settings > Secrets and variables 里设置一下密钥/参数变量，以便在自动化脚本中自动填充。需要填入这几个内容：AWS_ACCESS_KEY_ID，AWS_REGION，AWS_SECRET_ACCESS_KEY，DISTRIBUTION_ID，S3_BUCKET。

然后来到仓库，在 Actions 标签页选择新建 Workflow，会自动在 .github/workflows/ 目录下创建一个 main.yml 文件（我改名成了 deploy.yml），直接在页面上输入自动化的代码就可以了。

```yml
name: Deploy Hugo site to S3

on:
  push:
    branches:
      - main  # 仅在 main 分支有推送时触发部署

jobs:  # jobs 里列出要按顺序完成哪些动作
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v3

      - name: Setup Hugo
        uses: peaceiris/actions-hugo@v2
        with:
          hugo-version: '0.147.9' 

      - name: Build Hugo site
        working-directory: frontend  # 注意：我是在 frontend/ 目录中存放的项目文件，所以需要特别设置这一行。如果仓库一进来就是项目文件，就不需要这个。
        run: hugo -F --cleanDestinationDir  # 这里就是前面主题作者提到的 hugo 构建 HTML 文件到 public/ 目录的命令

      - name: Configure AWS credentials  # 上传到 S3 前需要身份认证，相当于在 AWS CLI 里运行 aws configure 命令
        uses: aws-actions/configure-aws-credentials@v2
        with: # 这里就是提前配置好的密钥和参数直接代入
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}

      - name: Upload to S3  # 前面提到过，上传到 S3 的命令
        run: |
          aws s3 sync frontend/public/ s3://${{ secrets.S3_BUCKET }} --delete

      - name: Invalidate CloudFront cache  # 刷新 CloudFront 的缓存。CloudFront 默认缓存是 24 小时，刷新后会立刻更新缓存，确保读者看到的是最新内容
        run: |
          aws cloudfront create-invalidation --distribution-id ${{ secrets.DISTRIBUTION_ID }} --paths "/*"

```

至此，自动化部署也完成了。每次推送内容到 Github 仓库时，可以在 Actions 里看到运行状况、每一步的响应。如果提示工作流失败，可以去检查是哪一步有报错，一一解决。

<figure>
  <div align=center><img src="/posts/tech/web/actions.png"  style="width: 70%; height:auto;" alt="自动化工作流"></div>
  <figcaption>Actions 工作流</figcaption>
</figure>


# CloudFlare 

## 什么是反向代理

此处先讲讲 Cloudflare 本身的用途，都是概念，如果急着看步骤可以跳[下一小节](#1-域名与-dns-配置)。

Cloudflare 本质上是一种反向代理。先说说与之相对的，什么是*正向代理（Forward Proxy）*。它是一个代理服务器，位于客户端和目标服务器之间，帮助客户端访问原本无法直接访问的内容。客户端将请求发给代理服务器，由代理服务器发起真正的网络请求，并将响应返回给客户端。相当于“偷偷”让代理帮你访问目标网站，目标服务器并不知道你是谁。

正向代理的使用场景：

1. 绕过网络限制，访问被墙的网站（如中国大陆访问 Google、YouTube）。
2. 隐藏真实身份，比如用代理 IP 爬虫，防止被目标网站封禁。
3. 开发调试环境，开发人员抓包分析流量、测试不同地区的访问效果。
4. 访问地域限定资源，例如某服务只允许美国 IP 访问时，可以使用美国的正向代理服务器。

似乎前两者更常见到。

总之，正向代理的“代理”对象是**客户端**，帮客户端出面去请求内容。

与之相对的，*反向代理（Reverse Proxy）* 的“代理”对象是**服务端**。它是一个位于客户端和服务器之间的服务器，接收用户请求并代表真实服务器来处理这些请求。它在扮演“服务器的中间商”。

在部署 CloudFlare 的时候就用到了反向代理，DNS 列表里如果把 Proxy 打钩，图标会变成橙色云朵，代表开启了反向代理。

在没有反向代理的情况下，用户浏览器会直接向 CloudFront 发起请求（DNS 只做解析，不做中转），CloudFront 向 S3 获取页面。没有 Cloudflare 的缓存、WAF、HTTPS、DDoS 防护等能力。路径是 用户 → DNS → CloudFront → S3。

开启了反向代理后，用户请求被 Cloudflare 接收（Cloudflare 成为反向代理）。Cloudflare 根据配置（如 CNAME 记录）将请求转发到 CloudFront。现在路径是 用户 → CloudFlare 反向代理 → CloudFront → S3。

CloudFlare 的反向代理主要实现以下几个功能：

- 自动配置 HTTPS（使用它自己的证书），而且是免费的
- 缓存静态内容（可减少 CloudFront 请求次数）
- 过滤恶意请求、防护 DDoS、Bot 等攻击
- 隐藏真实源站地址（CloudFront 域名不暴露）

总之，在这个网站中，CloudFlare 的 “橙色云朵” Proxy 模式本质上就是反向代理服务器，负责代表网站接收用户请求、处理 HTTPS、执行缓存与安全策略。不仅提升了访问速度，也让网站更安全、更好用。

## 1. 域名与 DNS 配置 
在 Cloudflare 买了域名后，一站式直通控制台。从左侧菜单栏来到 DNS record 配置，先添加这两条记录：

|  Type   | Name  | Content | Proxy Status |
|  ----  | ----  | ----  | ----  |
| CNAME  | www | Cloudfront 分发域名，形如 [一串字符].cloudfront.net | 启用代理，即橙色云朵 |
| CNAME  | 输一个 @ 就行，代表裸域，也就等于我的 [域名].com | 同上 | 同上 |

配置好后，在浏览器中输入域名应该就能跳转到网站首页了。但此时还没有配置 HTTPS，网站仍然不能安全访问。

## 2. HTTPS 与 TLS 证书

这里又涉及到了 AWS，要去 AWS Certificate Manager (ACM) 里申请安全证书，然后再回来添加新的 DNS 记录。选 ACM 有几个理由，首先是完全免费，且可直接绑定到 AWS CloudFront 分发，只需通过 DNS 验证你拥有该域名（Cloudflare 中配置）。

回到 AWS 控制台，进入 Certificate Manager 服务。需要选择美国弗吉尼亚北部（us-east-1）区域，因为CloudFront 只支持此区域的证书。

在申请证书时，选择类型为“公有证书”，并填上自己的域名。“验证方式”选择“DNS 验证”，系统会生成一个 CNAME 记录用于验证域名归属权。接下来就可以回到 Cloudflare DNS 去根据这个记录来填写了。注意不要开启 Proxy 代理，保持灰色云朵即可。（不知为何我的 Cloudflare DNS 记录里有两条不一样的 ACM 证书记录，忘记当时是咋配置的，回头再来看看）。

等待几分钟后，ACM 会显示“已颁发”。此时回到 Cloudfront 分发的编辑页，来配置安全证书。Custom SSL certificate 栏会有一个下拉框，直接能看到有一个申请好的证书在里面，选择它就行。其他证书配置保持默认。

至此，HTTPS 与安全证书也配置完成了。现在访问域名，会自动重定向到 https 的 URL，实现安全访问。我想实现的“输入域名->浏览器看到我的博客页面”这个目标已经达成！接下来就是一些额外的工作，包括缓存、网络安全配置等，让我的网站变得更加完备。

# 网络安全那些事

六月底网站上线，紧接着就回老家了，忙忙碌碌中十几天没有去管过网站数据。一直听说 AWS 免费套餐的额度对于个人网站绰绰有余，加上 Cloudflare 有一些基础的防御措施，是在域名管理中自动生效的，所以也没有担心过。直到七月中旬的某天，突然收到 AWS 的邮件，提醒我免费套餐的额度即将超标。仔细看了看额度用量，主要是 S3 超标，每月免费 2 万次请求的进度条已经飚红，马上就要顶格。又去 Cloudflare 控制台看了一下，似乎是收到了很多无意义的请求，大量重复 IP 来自同一个遥远的国家，又并非我目标读者所在地（没错就是爱尔兰）。过去 24 小时中，Unique Visitor 很少，只有两位数，但总请求量却爆棚，达到一千多条。我想应该是受到了某种网络攻击吧，早就听说网上有很多自动扫描脚本不停地在找端口暴露的服务器，没想到我这小小的静态网站也成了靶子。第一次面对这种攻击，还有点小紧张。那几天因为无法抽太多时间出来处理，于是简单粗暴地直接在 S3 停用了静态网站托管，以免收到高额账单。

时间来到七月下旬，准备重振精神处理网站的问题。Cloudflare 和 AWS 都各自有 WAF 防火墙功能，两边都研究了一下。

## Cloudflare 防火墙规则

进入控制台左侧 Security > Security Rules，在这里免费用户可以设定 5 条安全规则、1 条速率限制规则。我观察了 Analytics & Logs 里面的 HTTP Traffic 和 Security，以及 Security > Analytics 的统计，制定了下面几个规则来防范攻击：

1. 对 IP 地址来源的限制。爱尔兰、法国、澳大利亚这几个比较猖狂，24 小时分别访问我 500 次、300 次、200 次，我真的有这么多粉丝吗，求放过。我的措施是，对中国大陆、香港、台湾和新加坡 IP 直接放行，对其他国家的 IP 会采用 Cloudflare 提供的 Managed Challenge 验证，它会检测访问者的浏览器、行为等来判断要不要放行。如果有可疑的行为，就会弹出交互认证，认证通过了才能放行，类似我们平常访问一些网站的时候，突然跳出来的“点击这里以验证你是否是人类”，或者“选出所有包含XXX的图片”。关于这个验证的原理可以参考 [Cloudflare 的这篇博客](https://blog.cloudflare.com/zh-cn/end-cloudflare-captcha/)。关于几种 Challenge 的行为可以参考 [Interstitial Challenge Pages](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/)。
  > When incoming requests match…  
  > not (ip.geoip.country in {"CN" "SG"})  
  > Action: Managed Challenge

2. 对访问路径的限制。日志里发现很多请求路径根本不是我的网站真实存在的，比如很多以 /wp- 开头的路径，/admin，/wordpress，/file.php，等等。似乎是在瞎蒙哪个是我的博客控制台？或者想要读取到源码？总之这类可疑路径都需要屏蔽一下。
  > When incoming requests match…  
  > URI path contains ... (每个可疑地址都列出，用 OR 串联)  
  > Action: Block

3. 好 Bot 不挡道。有很多 SEO 数据统计服务会有爬取信息的 Bot，不算恶意访问，因此我会允许这些 Bot 通过；除此以外的 Bot 进来就会被 Challenge 一下。
  > When incoming requests match…  
  > not cf.client.bot  
  > Action: JS Challenge

cf.client.bot 是 Cloudflare 维护的好 Bot 名单，包括 Google, Yahoo, Bing, Linkedin, Apple 等等的 SEO bot。

4. 访问速率限制。为了防止恶意脚本几秒内访问我上百次，对于域名下的任意 URL，限制每 10 秒最多可请求多少次，超过了就会被 Block。我目前这个次数就不透露了，但好像太低了点，有时候把我自己也防住了，尤其是在主页右上角不同的版块快速来回切换看效果的时候。如果是免费套餐，似乎只能选择 Block，无法选择其他 Action，本来想设 Challenge 以免误伤的。好用的功能果然还是要收费。

另外 Cloudflare 自带 Bot fight mode，会自动检测 Bot，开启方法是 Security > Settings 找到 Bot fight mode 启用即可。

至此，Cloudflare 这边的安全措施就差不多了，目前来看效果还是不错的，免费套餐用量消耗得很慢，说明防住了不少无意义请求，在 Cloudflare 的 Security > Events 里也可以看到有很多快速批量访问被屏蔽。

## AWS WAF 与 ACL 规则

上面说的这些规则，AWS WAF 里面也都可以设置，但是要收费。为了探索如何设置，我也是以 3.27 美元的成本尝试了一下（开了几天就关了，真的不如 Cloudflare 直观好用，人家还是免费的）。

WAF 的工作原理是需要建立 ACL，设定规则组 Ruleset，然后把上面说的那些规则一一放进去就差不多了，设置方法大同小异。
1. 首先来到 WAF 服务，点击新建 ACL。
2. 关联自己的 Cloudfront 分发。
3. 添加安全规则。除了上面刚才说的规则外，还可以选择 AWS 现成的一些常见漏洞规则集，比如针对 SQL 注入、跨站脚本攻击的防范。

配置完成后，当我想要找一下哪个面板可以看到被拦截的详细信息时，发现还要去配置 AWS Cloudwatch 或者 Kinesis 面板才能看日志分析......此时已精疲力尽，遂放弃。那么多人都在用 Cloudflare 是有原因的，直接在控制台就能看图文并茂的分析。

月底收到账单，看了一下，ACL 和规则都算钱了，各 1 美元多。访问次数由于不多，没有给我算钱。至此，删掉所有 Rules 和 ACL 跑路，从此不再用 AWS WAF。

<figure>
  <div align=center><img src="/posts/tech/web/waf-pricing.png"  style="width: 50%; height:auto;" alt="AWS WAF 计费"></div>
  <figcaption>AWS WAF 计费</figcaption>
</figure>


# 缓存配置

其实缓存是在受到了网络攻击后才想起来这回事。大量请求之下，缓存命中率却非常低，导致每次请求都要直接到达 S3，消耗了用量。在额度耗尽当天去检查 Cloudflare 控制台时，24 小时内有 3.1K 次访问，但只有 1.52K 命中了缓存，基本只有 50% 命中率，对于静态网站来说很低了，正常来说 70% ~ 95% 才是理想状态。

要解决这个问题，做了三件事。

1. 去 Cloudflare 控制台的 Rules > Page Rules 新建了一条缓存的规则。对于我的域名，设定 Cache Level 为 Cache Everything 。Edge Cache TTL 设置为 1 month，因为博客更新频次不高，这样应该够用了。如果一个月内多次更新，每次去手动 Purge Everything 一下就可以刷新缓存。

此时用命令行看一下缓存情况：

```bash
curl -I https://我的域名.com/  # curl 可用于查看资源状态，选项 -I 表示只获取头部信息，不下载页面内容
```

响应：

```bash {hl_lines=[8]}
HTTP/1.1 200 OK 
Date: Sat, 12 Jul 2025 10:50:13 GMT 
Content-Type: text/html 
Connection: keep-alive
...
X-Cache: Miss from cloudfront
Cache-Control: max-age=432000 
Cf-Cache-Status: MISS
```

重点看到 MISS 这一行，说明缓存还是没有命中。按理来说由于 Cloudflare 代理了 Cloudfront 的转发，Cloudflare 的这个缓存策略应该是优先级最高的，但还是没有命中，估计问题不在于 Cloudflare 而在于源站或 Cloudfront。所以这里做另外两件事。

2. 在传静态内容到 S3 的时候，手动规定缓存机制。
  
```bash
aws s3 sync public/ s3://bucket-name/ \
  --cache-control "public, max-age=86400, must-revalidate" \ 
  --delete
```
第二行的 86400 表示存活时间为 24 小时，超出这个期限之后 must-revalidate 必须回源重新检查是否有更新。如果是不常更新的文件也可以用 immutable，不会重新请求更新。

3. 刚才在响应头里还看到 X-Cache: Miss from cloudfront，保险起见在 Cloudfront 这边也把缓存配置一下，这样如果 Cloudflare 缓存没有命中，还有兜底。进入 Cloudfront 左侧的“策略”，新建一个缓存策略。设置 最小 TTL、最大 TTL、默认 TTL都为 86400（1天）。然后来到 Distribution 的行为标签页，设置缓存策略为刚才建立的这个。由于在 Actions 工作流里还有一个刷新 Cloudfront 缓存的步骤，所以 TTL 设置为一天也没有问题，一天内有多次更新的时候也会刷新的。

这样配置一圈下来好像有点多余了，按理来说这三条其中任何一条配置好了，缓存应该都没有问题。不过搭建环境就是很玄，很多时候没有那么多“按理来说”，也不知道是哪一条起了作用，总之三管齐下后缓存命中率相当高了，有 95% 以上。

<figure>
  <div align=center><img src="/posts/tech/web/cache-after.png"  style="width: 100%; height:auto;" alt="配置后的缓存命中率"></div>
  <figcaption>配置后的缓存命中率</figcaption>
</figure>

到这里就是我的网站目前为止所有的配置流程了。中间穿插了一些概念类的解读，也是为了自己巩固学习，以后面试问起来也好有个记录。

对了，还有 twikoo + MongoDB 评论功能没说，等到后面有空了再加上。

如果有关于主题配置的问题，也欢迎评论留言讨论！配置的过程中我也是发现了不少 tips，比如设置单行代码高亮、修改表格边框、自动更新发布时间、让背景皮肤保持日间白色主题，等等，准备再开一个帖子记录。后续还打算集成一下 nanogallery2 这个插件，让图片展示更美观。

谢谢观看！网站建设这块我还是初出茅庐，许多概念解释或者配置还是有不周到的地方，也欢迎在评论区指正。

下回预告：[网站搭建技术总结（二）动态篇](https://bearlybear.com/posts/tech/web-dynamic/) 我给网站新加了AI问答的接口，引入了更多技术栈。 