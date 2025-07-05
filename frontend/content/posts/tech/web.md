---
title: "Web"
author: ["Bear"]
date: 2025-07-06T00:23:00+08:00
keywords: 
- web
categories: 
- tech
tags: 
- web
description: "搭建网站用到的 Web 相关技术栈"
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
    image: "" # 图片路径：posts/tech/123/123.png
    caption: "" # 图片底部描述
    alt: ""
    relative: false
---
# 写在前面

一开始搭建这个网站时，是想练习一下 AWS 云服务的操作，真正用 AWS 来上手做一点事情。2月份开始就有这个想法，当时花费很久部署了 EC2 + EBS + Github Actions，搭配 Flask 后端和 VUE 前端。整个过程非常之艰辛，不断有各种报错，由于蹭的是 AWS 的免费套餐，EC2 和 EBS 都有限额，经常遇到内存不足的报错。历经千辛万苦配置好了服务器，又找到了合眼缘的 VUE 模板，但由于 node.js 各种包的版本不兼容，配置前端也花了很多精力。然而此时网站还没有任何内容，只是准备环境已经精疲力尽，又要开始准备春招，所以项目搁置了好几个月。后果是，等我想要继续开始时，已经忘记之前做了些啥......当时每个步骤都在 Google Docs 里记录了，但现在看起来像天书，完全不记得每个步骤是在做啥。

我想也可能是因为一直没有看到一个初步的成果，自己也没有继续做下去的动力了。这次重新启动，第一要义是先搞出一个可见的网站页面并且上线，尽量用简单的技术栈。经过思考，博客短期内应该只有静态内容，所以先不用服务器，改用 S3 托管静态页面，配合 CloudFront CDN 全球加速，继续用 Github Actions 来做 CI/CD。另外前端需要找能够快速配置和上线的模板，不要再用 VUE。经过一番搜索，Hugo 和 Hexo 是两个比较流行的博客框架，其中 Hugo 是基于 Go 语言的，据说不容易像 node.js 一样报错多多，于是选择 Hugo。在[这个知乎问答](https://www.zhihu.com/question/266175192)里，找到了一个简洁又不失美观的模板，国内一个作者基于经典的 PaperMod 模板修改的 sulv-papermod。最终（或者说阶段性的）效果也就是你现在看到的网站了。

# 静态网站（当前版本）

## AWS S3

## AWS CloudFront CDN

## CloudFlare DNS 与 HTTPS、TLS
首先对比了两家域名服务商的价格，AWS Route53 是 14 美金一年，CloudFlare 10 美金一年，续约同价。另外 CF 还有方便部署的 HTTPS 和 SSL/TLS、DDoS、WAF 等安全服务。此外，据说 AWS 在中国大陆的 DNS 速度比较慢。综合看来，还是选择了 CloudFlare 买域名 + DNS 托管（其实两个可以分开，这里只是为了方便所以都用 CF 了）。






### 什么是反向代理

先说说什么是*正向代理（Forward Proxy）*。它是一个代理服务器，位于客户端和目标服务器之间，帮助客户端访问原本无法直接访问的内容。客户端将请求发给代理服务器，由代理服务器发起真正的网络请求，并将响应返回给客户端。相当于“偷偷”让代理帮你访问目标网站，目标服务器并不知道你是谁。

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


# 后端网站（计划版本）

## AWS EC2

## AWS EBS

## MySQL

## Nginx