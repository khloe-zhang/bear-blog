---
title: "网站搭建技术总结（二）动态篇"
author: ["Bear"]
date: 2025-10-07T16:30:00+08:00
keywords: 
- web
categories: 
- tech
tags: 
- web
- AWS
- EC2
- Nginx
- RAG
- AI
description: "搭建动态网页（API调用）用到的 Web 相关技术栈"
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
    image: "posts/tech/web-dynamic/chatpage.png"
    caption: "" # 图片底部描述
    alt: ""
    relative: false
---

书接上回[网站搭建技术总结（一）静态篇](https://bearlybear.com/posts/tech/web-static/)，其实在刚开始接触 AI 的时候，我就有想过做一个关于我自己的 AI 问答机器人，只是当时还不清楚如何实现。在了解到 RAG 之后，有了灵感——把我的信息都挂载到 RAG 知识库里，让 AI 去检索，就可以生成关于我的回答了！博客网站已经有了雏形，是时候把这个功能加上了。

# 架构设计

我采用了动静分离的架构，原先配置好的博客架构、CSS 样式、文章等静态资源不需要迁移走，还可以放在原来的 S3 里，只需要把 API 接口调用的逻辑单独跑在服务器里即可，只有用户发送 API 请求的时候，才会去调用动态资源返回结果。后端我采用了 FastAPI，因为年初使用 Flask 的体验不是很好；为了和已有的基础设施丝滑对接，我还是继续用 AWS，选择了 EC2 作为虚拟 Linux 主机。

关于 AI 的部分，尽管现在有很多一站式的 AI 应用开发平台，可以直接实现 RAG 的一套流程（词嵌入 + 向量检索）以及 API 封装调用，但我还是选择了本地实现 RAG，使用 Transformer 加载词嵌入模型，配合 ChromaDB 向量数据库，最后调用 Deepseek API 生成回答。我的想法是在这个过程中尽可能多地接触 RAG 的原始部署流程，更直观地拆解和学习 RAG 的原理。

为了更好地监控服务器性能和 API 指标，我配置了 Prometheus + Grafana 两件套。我用 node-exporter 配合 Prometheus 抓取服务器运行状况，展示在 Granafa 中。此外我还在 API 服务的后端配置了 API 调用的一些指标断点，比如总提问频率、提问记录与回答记录、全程耗时，以及用于 RAG 优化的一些测试指标，通过 SQLite 记录下来并且传到 Grafana 的可视化面板中，便于后续优化 API 服务的表现。

# AWS EC2

## 创建实例
本着成本最小化的理念，当然还是要蹭 AWS 的免费套餐。我预估 API 请求的次数不会很多，几十到几百请求/天，而且后端服务流程不复杂，t2.micro 应该够用。Linux 选择 ubuntu 24.04，EBS 存储容量默认 8G（后来证明太小了，最好改成 10G）。

创建实例后，记得保存密钥文件的位置，以后用 ssh 登录的时候需要切换到这个目录下。为了后续网络配置方便，我申请了一个弹性 IP，这样 EC2 就有了一个固定的公网 IP 地址，而不会每次重启 IP 都要变。

接下来配置安全组，在创建实例的过程中先定义 HTTP、HTTPS、SSH 这三个类型的出入站规则，后续根据服务的增加还会需要回来调整的。出站流量是默认允许所有；入站流量中，HTTP 和 HTTPS 可允许所有（0.0.0.0），但 SSH 仅允许本机 IP 地址。以后电脑每次开机或者换了网络连接时，要记得回来改一下这个安全组规则。后续由于我增加了服务，需要新增“自定义 TCP 类型”的端口放行规则：API 的服务端口放在了 8000，Prometheus 端口 9090，Grafana 端口 3000，这些端口也设置了仅允许本机地址访问。这之后就可以通过 SSH 连接实例了。

在这里还要说一下，最开始配置完实例后，除了 SSH 这个连接方式以外，最好留一个后门，以防 SSH 由于各种状况无法连接。我就遇到过 systemd 服务循环重启卡死实例，SSH 命令行窗口卡死，退出再登就死活登不上了。一开始我还新建一个救援实例，然后把 EBS 卷分离挂到这个新实例上，登录新实例把应用服务整个删掉再把卷挂回去，非常麻烦。解决方法是，可以配置一个“会话管理器”的登录渠道，这是 AWS 提供的一种基于 System Manager 的连接方式，无需经过 SSH，直接在浏览器端就可以一键连接实例，并且有网页端的 CLI。具体的配置方式可以参考 [使用会话管理器连接到 Amazon EC2 实例](https://docs.aws.amazon.com/zh_cn/prescriptive-guidance/latest/patterns/connect-to-an-amazon-ec2-instance-by-using-session-manager.html)。大概流程就是先去 IAM 里，选择“创建角色”，根据指引选择对象为 EC2，然后在“使用案例”里选择 EC2 Role for AWS Systems Manager，接着一路默认操作就可以了。配置好后，EC2 实例连接页面的会话管理器的“连接”键就从灰色变成可操作了。坏处就是这个 CLI 很多快捷键都用不了，连复制粘贴都要靠鼠标右键，用 nano 编辑脚本文件也很麻烦。并且，每次进去需要手动切换到 ubuntu 用户：`sudo -i -u ubuntu`。

## 安装各种软件包
通过 SSH 登录 Linux 主机后，先安装一些基础的软件包，比如 python3-pip、git、nginx。

```shell
# 1. 更新软件包列表（对于Ubuntu，使用apt）
sudo apt update && sudo apt upgrade -y

# 2. 安装必要的软件包
sudo apt install -y python3-pip python3-venv git nginx
```

然后在 ubuntu 用户的 home 目录下建一个项目目录，存放项目的所有代码。为了防止项目的库以后和别的项目产生依赖冲突，可以给这个项目单独建一个虚拟环境，如果在配置前期出了什么问题，就可以直接删掉这个环境重来。

```shell
python3 -m venv venv  # 创建虚拟环境
source venv/bin/activate # 激活虚拟环境
```

然后，开始安装软件的漫漫长路吧！

先从简单的开始，创建一个 requirement.txt，把要装的软件都写进去。最开始我写的是下面这样的：（不要复制这个来用！仅做记录。后面产生了超多包冲突和内存不足的问题）

```shell
cat > requirements.txt << EOL
fastapi[standard]
uvicorn[standard]
chromadb
sentence-transformers
openai
prometheus-client
EOL

pip install -r requirements.txt
```

这里先说一下各个包的作用。fastapi 用来构建基于 Python 语言的后端；uvicorn 是用来在后端中做异步进程管理的；chromadb 是向量数据库——在 RAG 时，需要先由一个词嵌入模型将提问和知识库都转为向量表示，然后去向量数据库里检索相关知识。sentence-transformers 的作用是：
> Sentence Transformers (a.k.a. SBERT) is the go-to Python module for accessing, using, and training state-of-the-art embedding and reranker models.

来源：[SBERT 官网](https://www.sbert.net/)。就是用来加载词嵌入和排序模型的一个工具模块。


准备好安装列表，然后就开始不停地处理报错了......

首先登场的是，ChromaDB 的依赖库里，urllib3 这个库有 nvidia_cudnn_cu12 这个包，安装的时候我这丐版实例的磁盘空间不足报错了。由于我不需要安装完整的CUDA工具包（这是为GPU机器学习准备的），对于CPU环境，可以选择更轻量的依赖。现在也不知道刚才那些包安装到什么程度了，所以直接删掉虚拟环境重来。

```shell
# 退出当前虚拟环境
deactivate

# 删除当前失败的虚拟环境
rm -rf /home/ubuntu/<项目文件夹>/venv

# 清理pip缓存释放一些空间
pip cache purge
```

跟刚才一样，重新创建虚拟环境，然后新建一个 requirement.txt，指定版本，单独安装 ChromaDB 依赖，避开 CUDA 包，并且指定各种软件的版本。

```shell
cat > requirements.txt << EOL
fastapi==0.104.1
uvicorn[standard]==0.24.0
sentence-transformers==2.2.2
openai==1.3.0
prometheus-client==0.19.0
# 使用chromadb的轻量版，避免CUDA依赖
chromadb==0.4.15 --no-deps
# 单独安装chromadb的CPU依赖
pypika==0.48.9
posthog==2.4.2
typing-extensions==4.8.0
urllib3==1.26.16
# 添加其他必要依赖
numpy==1.24.3
pydantic==2.5.0
torch==2.5.1+cpu
EOL
```

接下来，为了防止安装时中间遇到报错停下来，再出现不知道安装到了哪一步然后全部删掉的情况，这次就不用 pip install -r requirements.txt 一次安装，而是分步安装。

```shell
# 先安装最基础的包
pip install fastapi uvicorn prometheus-client openai

# 安装sentence-transformers（指定不使用CUDA）
pip install sentence-transformers --no-deps
pip install transformers tokenizers torch --index-url https://download.pytorch.org/whl/cpu

# 安装chromadb及其最小依赖
pip install chromadb --no-deps
pip install pypika posthog typing-extensions urllib3

# 安装其他必要依赖
pip install numpy pydantic
```

这中间又遇到了很多次报错，主要是库之间的版本冲突问题。这里我总结一下最后能成功兼容的几个库的版本：

- Python 3.10.18
- Torch 2.5.1+cpu
- Transformers 4.56.1

安装完成后，可用于测试是否安装成功的命令，就是import一下，如果没有报错就是安装成功了，也可以打印出版本号：

```shell
python -c "
import fastapi
import uvicorn
from sentence_transformers import SentenceTransformer
print('核心包导入成功！')
"

python -c "import transformers
print(transformers.__version__)"

# 也可以通过 pip 命令列出指定包以及版本
pip list | grep -E "(torch|transformers|sentence)"
```

重磅插曲：安装过程中，sentence_transformer 和 huggingface_hub 库有冲突，原因是 0.26.0 版本以上的 huggingface_hub 已经移除了 cached_download 这个函数，但是 sentence_transformer 仍然在安装脚本中 import 它，报错如下：

`
File "/home/ubuntu/<项目文件夹>/venv/lib/python3.10/site-packages/sentence_transformers/SentenceTransformer.py", line 12, in <module>
from huggingface_hub import HfApi, HfFolder, Repository, hf_hub_url, cached_download
ImportError: cannot import name 'cached_download' from 'huggingface_hub'
`

这个问题花了好大一番功夫到处想办法。我一开始尝试过降级 huggingface 库到 0.25.0，也就是还保留 cached_download 的最后一个旧版本，但是报错：

`
transformers 4.56.1 requires huggingface-hub<1.0,>=0.34.0, but you have huggingface-hub 0.25.0 which is incompatible. `

好家伙，陷入套娃循环了，版本高了就有参数过时的问题，版本低了 Transformers 又不支持。也不敢再去降级 Transofmers 库了，之前处理 Torch 冲突就花了半天，好不容易才弄好，谁知道还会不会带出啥连锁反应。

怒想别的办法。这个 [Github Issue](https://github.com/easydiffusion/easydiffusion/issues/1851) 可以用作参考，解决思路就是去 sentence_transformer 安装脚本在 import 的地方把 cached_download 改成新的 hf_hub_download（但不只这么简单）。从这个 issue 里可以看到，不只 sentence transformer，还有其他很多封装了 huggingface 的工具库的使用者/开发者也遇到了这个问题。下面我就讲一下怎么自己去解决。

  1. 根据一连串的报错信息，定位到有两个安装脚本里包含了这个过时的 import，分别是 `/home/ubuntu/<项目文件夹>/venv/lib/python3.10/site-packages/sentence_transformers/SentenceTransformer.py", line 12 ` 以及相同目录下的 `util.py, line 17`。找到相应位置，把 import 里面的 `cached_download` 改成 `hf_hub_download`。
  2. 当然不只这么简单！`util.py` 文件里除了 import，代码里也调用了 `cached_download` 这个函数，并且还传入了 `cached_download_args` 的一系列参数。得想个办法解决这一连串问题。

<figure>
  <div align=center><img src="/posts/tech/web-dynamic/cache-1.png"  style="width: 100%; height:auto;" alt="cached_download 报错"></div>
  <figcaption>有问题的地方（修改前）</figcaption>
</figure>

  需要把 path 这一行改成 `path = hf_hub_download(**cached_download_args) `，也就是把 `cached_download` 替换成 `hf_hub_download`。由于 `cached_download_args`只是参数的名字，函数改名了它照样可以传参，所以不用去改它的名字。

  3. 还是报错！`TypeError: hf_hub_download() got an unexpected keyword argument 'url'` 问题来到 `cached_download_args` 参数。旧的 `cached_download` 接受的是 `url` 参数（直接下载 URL），而新的 `hf_hub_download` 函数不再传入 `url` 这个参数。原因可能是：`hf_hub_download` 设计的是基于模型仓库（repo_id, filename）的接口，不支持 url。

  此时把脚本向上滑一点，能看到 `url` 参数的定义。按照下图的说明，把原有的 url 里面的三个参数拆出来，替换掉 `cached download_args` 里面的 `url`。另外，`legacy_cache_layout` 这个参数也弃用了，会报错  `TypeError: hf_hub_download() got an unexpected keyword argument 'legacy_cache_layout'`，如图把这一行注释掉即可。

<figure>
  <div align=center><img src="/posts/tech/web-dynamic/cache-2.png"  style="width: 100%; height:auto;" alt="cached_download 报错2"></div>
  <figcaption>url 参数改完之后的样子</figcaption>
</figure>

至此，这个 `cached_download` 引发的一连串问题算是解决了，后续安装没有再报错。

## 清理内存的命令
这里记录一下清理内存的一些命令，我真心建议创建实例的时候选大一点的存储卷，至少留 12 G，多不了多少钱，体验感天差地别。
```
# 清理APT缓存
sudo apt clean
sudo apt autoremove -y

# 清理日志文件
sudo find /var/log -name "*.log" -type f -delete
sudo find /var/log -name "*.gz" -type f -delete

# 清理临时文件
sudo rm -rf /tmp/*
sudo rm -rf /var/tmp/*

# 再次检查空间
df -h
```

## 远程主机和本地主机互传文件
WinSCP（后续补充）

# 后端服务搭建
来到了重头戏，整个 API 服务逻辑其实都写在 app.py 这一个文件里。现在来拆解一下几个主要的部分。

## FastAPI 
FastAPI 本身，其实代码不多。

```python
# FastAPI 的本体、依赖注入工具（用于DB连接、认证、参数校验）、抛出错误、基础响应类（控制返回内容/状态码/headers/media_type等）、来自客户端的请求对象
from fastapi import FastAPI, Depends, HTTPException, Response, Request 
# 中间件，配置跨域资源共享，允许网页请求转发到API端点
from fastapi.middleware.cors import CORSMiddleware
# 构造 JSON 响应、流式返回输出
from fastapi.responses import JSONResponse, StreamingResponse
# Pydantic 可以自动验证输入数据是否符合定义，用于处理用户输入、API 交互和配置文件
from pydantic import BaseModel

# FastAPI应用初始化
app = FastAPI(title="AI Blog API")

# Pydantic模型
class QuestionRequest(BaseModel):
    question: str
```

## AI 部分

这一部分包括 RAG 的流程和 API 的调用逻辑。

### RAG
定义好嵌入模型和向量库，整理好自己的知识库。

#### 嵌入模型与向量库
我最开始用的是 sentence-transformers 提供的 [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) 这个词嵌入模型。本来是打算用刚好一套的 sentence-transformer 方法来加载模型，结果遇到了很多报错，什么 CA 证书、model_type 参数错误等等，于是随手试了一下直接用 Transformer 来加载，一次成功......所以刚才在那边排查了一堆错误，最后也没用上。

```python
# 先预定义通过Transformer加载Embedding模型
class CustomEmbedder:
    def __init__(self, model_name='sentence-transformers/all-MiniLM-L6-v2'):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name, use_safetensors=True)
        self.model.eval()

    # 定义均值池化函数，把每个 token 的向量合并成整句/文本的一个向量
    def mean_pooling(self, model_output, attention_mask):
        token_embeddings = model_output[0]
        # attention_mask 标记哪些 token 是实际词（1）或填充（padding，0）
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        # 把真实 token 的向量相加，然后除真实 token 的数量，得到平均向量，也就是句子的向量表示
        # clamp min 1e-9 是为了防止除以 0（极端情况整句全是 padding）
        return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)
    
    # 把输入文本转换为成句向量，方便后续做向量检索
    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        # 用 tokenizer 将文本编码成模型输入，返回 PyTorch 张量（tensor）
        inputs = self.tokenizer(texts, padding=True, truncation=True, 
                               return_tensors='pt', max_length=512)
        # 运行推理，得到每个 token 的向量输出
        with torch.no_grad():
            outputs = self.model(**inputs)
        # 调用刚才定义好的池化函数，根据 attention mask 忽略 padding token，只对真实 token 的向量计算嵌入
        embeddings = self.mean_pooling(outputs, inputs['attention_mask'])
        # 对每个向量做 L2 归一化（便于用余弦相似度比较），然后转换为 numpy 数组返回
        return F.normalize(embeddings, p=2, dim=1).numpy()

# 全局变量
embedder = CustomEmbedder()  # 嵌入模型初始化为刚才预定义好的Embedding模型
chroma_client = chromadb.PersistentClient(path="./chroma_db") #初始化 ChromaDB 向量数据库，数据将保存在当前目录的chroma_db文件夹中
collection = chroma_client.get_or_create_collection("personal_knowledge") # 获取或创建知识库集合
DOCUMENTS_DIR = "/home/ubuntu/<项目目录>/rag_documents" # 存放知识库文件的目录
```

#### 构建 RAG
利用刚才搭建好的 embedding 和向量库，开始搭建 RAG 流程。

```python
# 构建或更新RAG知识库
def build_knowledge_base():
    # 声明 global 全局变量，在函数里更新后，全局的 collection 也会更新
    global collection

    try:
        # 尝试删除现有集合，避免每次知识库更新后还匹配到旧的
        chroma_client.delete_collection("personal_knowledge")
    except:
        pass  # 如果集合不存在，忽略错误

    collection = chroma_client.get_or_create_collection("personal_knowledge")

    all_docs = []
    all_embeddings = []
    all_ids = []

    # 支持两种文件格式
    supported_extensions = ('*.pdf', '*.docx')
    files_to_process = []
    for ext in supported_extensions:
        files_to_process.extend(glob.glob(os.path.join(DOCUMENTS_DIR, ext)))

    # 这是 RAG 的参数，后续可以根据效果优化
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,  # 每个文本块的大小
        chunk_overlap=50  # 块之间的重叠部分
    )

    doc_id = 0
    for file_path in files_to_process:
        try:
            if file_path.endswith('.txt'):
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            elif file_path.endswith('.pdf'):
                # 需要安装 PyPDF2: pip install pypdf2
                import PyPDF2
                with open(file_path, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    text = "\n".join([page.extract_text() for page in pdf_reader.pages])
            elif file_path.endswith('.docx'):
                # 处理 DOCX 文件
                from docx import Document
                doc = Document(file_path)
                text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            else:
                continue  # 暂时跳过其他格式

            # 分割文本
            chunks = text_splitter.split_text(text)

            for chunk in chunks:
                # 生成嵌入向量
                embedding = embedder.encode(chunk).tolist()[0] 
                all_docs.append(chunk)
                all_embeddings.append(embedding)
                all_ids.append(f"doc_{doc_id}")
                doc_id += 1

        except Exception as e:
            print(f"Error processing {file_path}: {str(e)}")
            continue

    # 批量添加到向量数据库
    if all_docs:
        collection.add(
            documents=all_docs,
            embeddings=all_embeddings,
            ids=all_ids
        )
        print(f"Successfully loaded {len(all_docs)} document chunks into knowledge base.")
    else:
        print("No documents were processed.")

# 加一个每次启动API服务时，自动构建知识库的函数
@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    print("Building knowledge base...")
    build_knowledge_base()
    print("Knowledge base built successfully.")
```

#### RAG调优
这部分是全部服务都部署完成、测试后，发现模型回答效果不是很好，所以返回来补充的。测试时，我提一个答案很好找的问题，很明显地写在知识库里了，但是答案就是不提那部分。而且问来问去，似乎模型都只会回答我“项目经历”那一段内容，就算问题不太相关，它也会扯到这上面，可能 RAG 嵌入+检索的时候只识别到了那一段信息。

RAG 调优几个主要的方法：
1. Embedding 模型本身的调整。
2. 调参，参数包括 Chunking 切块的 token 数、Overlap 重叠窗口的大小、Top-k 选取前多少个检索匹配结果。其中 Chunking 除了按 token 数来切块外，还有其他的方式，如按照段落或语义切块。
3. Rerank 重排，indexing 索引优化，query rewrite 查询重写。

查到了这些方法之后，准备一条条尝试。我还在后端代码里做了埋点，加了一个 config 参数，跟着问答记录一起展示到 Grafana 的 SQL 里，方便后期测试不同的调优方法对模型表现的影响。

目前尝试了第1个方法——改Embedding模型。起因是我之前用的尺寸很小的模型 all-MiniLM-L6-v2 的 Huggingface 评论区，有人问：中文表现咋样？一致反馈是：不咋样——我也觉得！之前只关注模型尺寸了，没去想语言的问题。又找了几个经过中文预训练的模型，最后锁定在 DMetaSoul/sbert-chinese-general-v2-distill 这个模型，尺寸同样很小，方便部署在我的丐版主机上。

在后端代码里面改了模型，不夸张地说，一下就变聪明了，对答如流且击中要点！这还是没有继续其他 RAG 调优方法的情况下，表现已经提升了很多。由于后续还有其他的工作要做，暂时没有再弄其他几种调优，后面可以返回来继续。

### Deepseek API
API 调用主要是两个部分，一个负责与 Deepseek 接口交互，一个负责问答的内部处理逻辑和路由。

```python
def get_ai_response(prompt):
    """发起HTTP请求调用Deepseek API获取回答"""
    api_key = os.getenv("DEEPSEEK_API_KEY")  # 此处需要提前注册 Deepseek 开发者账号，获取密钥，存到 os 的环境变量中
    if not api_key:
        raise ValueError("Deepseek API key not found in environment variables")

    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",  # 根据实际情况选择模型
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "stream": True
    }

    try:
        with requests.post(url, json=data, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line:
                    yield line + "\n"  # 每行逐块发送
    except requests.exceptions.RequestException as e:
        yield f"data: {json.dumps({'error': f'Deepseek API error: {str(e)}'})}\n\n"

# --- API路由 endpoint，将函数暴露为 POST 接口--- 
@app.post("/api/ask_stream")
async def ask_stream(request: QuestionRequest, db: Session = Depends(get_db)):
    try:
        # 1. 将用户问题转换为向量
        question_embedding = embedder.encode(request.question).tolist()
        if isinstance(question_embedding[0], float):
            question_embedding = [question_embedding]  # 包装成二维列表

        # 2. 在向量数据库中检索最相关的文档
        results = collection.query(
            query_embeddings=question_embedding,
            n_results=3  # 检索Top3最相关的片段，这也就是 RAG 优化中的 top-k 参数
        )
        retrieved_docs = results['documents'][0] if results['documents'] else ["No relevant context found."]

        # 3. 构建Prompt
        context_str = "\n".join(retrieved_docs)
        prompt = f"""我的名字叫熊熊，你是我的AI助手。请根据下面提供的关于我的背景信息来帮我回答用户问题。

        【背景信息】
        {context_str}

        【用户问题】
        {request.question}

        【回答要求】
        1. 假装你就是我，全部使用第一人称视角回答（如"我曾经..."）。
        2. 基于我的背景信息中的内容回答问题。
        3. 如果背景信息不包含答案，请表达根据已有信息你无法回答这个问题，但可以使用生动的语气。
        4. 风格自然亲切，但保持专业。
        5. 不要编造背景信息中不存在的内容。
        """

        # 记录成功的请求
        API_REQUEST_COUNT.labels(method='POST', endpoint='/ask_stream', status='200').inc()
        # return JSONResponse(content={"question": request.question, "answer": answer, "id": record.id}) 这个是最开始尝试的整段返回回答，后来发现前端用户等待时间太长，所以改为流式传输，生成了多少就先输出，不必等到生成完一整段再一起返回到前端
        return StreamingResponse(get_ai_response(prompt), media_type="text/event-stream")

    except Exception as e:
        # 记录失败的请求
        API_REQUEST_COUNT.labels(method='POST', endpoint='/ask_stream', status='500').inc()
        raise HTTPException(status_code=500, detail=str(e))
```

## 网络和Nginx

由于这个 API 是位于次级域名下（原域名前面加上“api”），与前端页面不能算属于同一个 origin，会被浏览器的同源策略拦截，阻止前端 JS 脚本直接发出跨域请求或读取响应。想要用户能够通过前端交互把请求发到后端处理，就必须配置跨域策略 CORS。

```python
# 允许前端跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1313",    # 本地Hugo开发服务器
        "https://bearlybear.com",   # 生产域名
        "https://www.bearlybear.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Nginx 文件存放在 /etc/nginx/sites-available/<项目名>，用于接受前端的请求，把请求转发到后端，避免后端暴露。
```Nginx
server {
    listen 80; # 监听80端口，即http
    server_name api.bearlybear.com; 
    return 301 https://$host$request_uri; # 把http请求重定向到https
}

server {
    listen 443 ssl; # 监听443端口，即https，并开启TLS加密
    server_name api.bearlybear.com;
    # 指定TLS证书和私钥文件，这个在下面一段会讲如何配置
    ssl_certificate /etc/ssl/certs/bearlybear-origin.pem;
    ssl_certificate_key /etc/ssl/private/bearlybear-origin.key;
    
    # API转发，匹配以/api/开头的路径，比如/api/ask_stream
    location /api/ {
        proxy_pass http://127.0.0.1:8000; # 请求转发到后端服务
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 监控指标，会被 Prometheus 抓取。这部分还需要在 app.py 后端里面定义，详情我写在 Prometheus 那部分了
    location /metrics {
        proxy_pass http://127.0.0.1:8000/metrics;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

```
修改完成后，可以用这个命令检查 Nginx 语法：
```shell
sudo nginx -t
```

确认无误后，启用配置并重启 Nginx：
```shell
sudo ln -s /etc/nginx/sites-available/<项目名> /etc/nginx/sites-enabled/
sudo systemctl restart nginx
```

这里还需要给 API 的子域名配置一个 HTTPS 证书。此前我只有静态域名的证书，这个子域名无法共享，所以需要重新配置一个。因为域名管理我用的是 Cloudflare，所以直接继续用 Cloudflare 的 Origin 证书。进入 Cloudflare 控制台 >  SSL/TLS > Origin Server，新建证书，主机名需要包含我的所有子域名：

> bearlybear.com <br/>
> *.bearlybear.com (通配符，覆盖所有子域名) <br/>
> api.bearlybear.com

其他选项可保持默认。完成证书创建后，会得到两个文件：证书文件 (.pem 格式)和私钥文件 (.pem 格式)。将这两个文件的内容复制保存下来。

下一步，回到 EC2 本身配置 SSL 证书。
```shell
# 创建SSL证书目录
sudo mkdir -p /etc/ssl/certs
sudo mkdir -p /etc/ssl/private
# 设置正确的权限
sudo chmod 700 /etc/ssl/private
# 创建证书文件，把刚才复制的证书内容放进文件里
sudo nano /etc/ssl/certs/bearlybear-origin.pem
# 创建私钥文件，把刚才复制的私钥内容放进文件里
sudo nano /etc/ssl/private/bearlybear-origin.key
# 设置严格的权限
sudo chmod 600 /etc/ssl/private/bearlybear-origin.key
sudo chmod 644 /etc/ssl/certs/bearlybear-origin.pem
sudo chown root:root /etc/ssl/private/bearlybear-origin.key
```
相应地，在 Nginx 配置文件里也需要指定这两个密钥文件，详见上面 Nginx 文件内容。完成后，API 服务也跟静态网页一样受到 SSL 保护了，比 HTTP 更安全。

## API Service 文件

到这里，app.py 里面的内容已经基本完成了，要让它能够持续运行在主机上，还需要把它包装成一个服务（service），

```
sudo nano /etc/systemd/system/<项目名>.service

[Unit]
Description=AI Blog API Service
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/<项目目录>
Environment="PATH=/home/ubuntu/<项目目录>/venv/bin:/usr/bin:/bin"
Environment="DEEPSEEK_API_KEY=这个里面填API的密钥"
Environment="ANONYMIZED_TELEMETRY=false"
ExecStart=/home/ubuntu/<项目名>/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal
StartLimitIntervalSec=60
StartLimitBurst=3
TimeoutStartSec=45s
TimeoutStopSec=15s
MemoryMax=2G
CPUQuota=80%

[Install]
WantedBy=multi-user.target
```

配置好后，用下面的命令启动服务：
```shell
# 重新加载systemd配置
sudo systemctl daemon-reload
# 启动服务
sudo systemctl start <服务名>
# 设置开机自启
sudo systemctl enable <服务名>
# 检查服务状态
sudo systemctl status <服务名>
# 查看日志（如果有问题）
sudo journalctl -u <服务名> -f
```

到这里为止，这个的 API 服务就配置完成了。可以用 cURL 来测试是否请求是否能通。

```shell
curl -X POST "http://<EC2的IP>:8000/api/ask-stream" \
     -H "Content-Type: application/json" \
     -d '{"question": "你是谁？"}'
```


## Prometheus 
在 app.py 后端中，还需要暴露一些监控给 Prometheus 来抓取，以便后续展示在 Grafana 中。这些指标包括 API 请求量、请求时延等。

```python
import prometheus_client
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY, CONTENT_TYPE_LATEST
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from prometheus_client import PROCESS_COLLECTOR, PLATFORM_COLLECTOR

# 初始化默认指标
PROCESS_COLLECTOR  # 确保进程收集器被导入
PLATFORM_COLLECTOR  # 确保平台收集器被导入
prometheus_client.start_http_server(0)  # 端口0表示不启动额外服务器

# --- Prometheus监控指标定义 ---
API_REQUEST_COUNT = Counter('api_request_total', 'Total API requests', ['method', 'endpoint', 'status'])
API_REQUEST_DURATION = Histogram('api_request_duration_seconds', 'API request duration', ['endpoint'])

@app.get("/metrics")
async def metrics():
    """Prometheus指标端点"""
    try:
        from prometheus_client import generate_latest
        data = generate_latest()
        return Response(
            content=data,
            media_type=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        logger.error(f"Metrics endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Metrics generation failed")

# 这个其实不用 Prometheus 来抓取，可以直接用 curl 检查状态
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "service": "AI Blog API"}
```

Prometheus 本身的配置在 prometheus.yml 这个文件里。
```yml
# 前面省略默认的一些配置
# A scrape configuration containing exactly one endpoint to scrape:
# Here it's Prometheus itself.
scrape_configs:
  # The job name is added as a label `job=<job_name>` to any timeseries scraped from this config.
  - job_name: "prometheus"

    # metrics_path defaults to '/metrics'
    # scheme defaults to 'http'.

    static_configs:
      - targets: ["localhost:9090"]
       # The label name is added as a label `label_name=<label_value>` to any timeseries scraped from this config.
        labels:
          app: "prometheus"
  
  # 下面开始新增自定义的指标
  - job_name: 'api-job' # 一个新的作业，用于监控API服务
    static_configs:
      - targets: ['localhost:8000'] # API服务端口
    metrics_path: '/metrics' # metrics端点路径
    scrape_interval: 15s # 抓取间隔

  - job_name: 'node-exporter' # 抓取主机健康指标
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:9100']
```

最后这个 node-exporter 是 Prometheus 提供的一个工具，用来收集 EC2 主机本身的运行指标，比如 CPU 利用率、内存等，需要提前下载并解压。它的端口号是 9100，会暴露给 Prometheus 来抓取数据。对于 node-exporter，建议也配置一个systemd文件，便于开机自启：
```shell
sudo nano /etc/systemd/system/node-exporter.service

[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/node_exporter --web.listen-address=127.0.0.1:9100
Restart=on-failure
RestartSec=30
StartLimitBurst=5

NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

配置完成后，重启服务，跟刚才 Nginx 的流程一样，用 systemctl 命令 daemon-reload 然后 enable 最后 start 即可。

要测试指标是否能被成功抓取：
```shell
# Prometheus 指标
curl -v http://localhost:8000/metrics

# 检查 node-exporter 端口监听
sudo netstat -tlnp | grep 9100 

# node-exporter 测试指标收集
curl http://localhost:9100/metrics | grep -E "(node_memory|node_cpu)"
```


## Grafana
上面在 Prometheus 中配置完各项抓取指标后，其实在 Prometheus 页面本身也可以简单查询指标，但是如果想做更加直观的可视化面板，就要用到 Grafana，它支持导入多种数据源，并可视化为表格、饼图、折线图、柱状图等等类型。

首先，在实例上安装并启动 Grafana。

```shell
sudo apt-get install -y grafana
sudo systemctl start grafana-server
sudo systemctl enable grafana-server
```

然后就可以通过网页访问GUI了，地址是 http://\<EC2-IP>:3000，默认用户名/密码：admin/admin。

### 可视化面板配置
面板也就是 Dashboard，在页面中点击新建 Dashboard。在这里我建了3个面板，分别展示主机健康状态、API调用次数和频率，以及API提问和回答的文字记录。在 Explore 菜单栏里添加数据源，然后在创建面板的时候选择需要的数据源，并且设置相应的抓取代码。（待补充）


### SQLite
我用 SQLite 来记录用户的AI问答历史文字。
```python
from sqlalchemy.orm import Session
from db import get_db, SessionLocal, init_db, QAHistory

```

# 前端代码修改

## 视觉元素
本来按照 Hugo 的主题模板，首页只有四个入口。现在为了增加 AI 对话入口，需要新增一个长方形的按键。

```html
<div class="ai-button-container">
    <a class="button ai-button" href="/ai-chat" rel="noopener" title="AI问答">
        <span class="button-inner">
            🤖 AI 问答
        </span>
    </a>
</div>
```

在 CSS 文件中定义这个新的 ai-button-container 容器以及按钮本身的样式。

```css
.ai-button-container {
    width: 100%; /* 确保容器占据整个宽度，为按钮换行做准备 */
    margin-top: 0.5rem; /* 与上一行按钮的间距 */
    display: flex;
    justify-content: center; /* 让按钮在容器中水平居中 */
}

.button:active {
    transform: scale(0.96); /* 点击按钮时，会有一个缩小的效果， 交互上展示出点击有效*/
}
```

然后就是 AI 问答本身的页面了。每个网页最表层是 markdown 文件，放置在 content 文件夹里，里面还有 about 关于、时间轴、友链、搜索的 md 文件。新建一个 ai-chat.md 文件，在里面引用样式为 ai-chat。

```markdown
---
title: "🤖 AI问答"
layout: ai-chat
---
```

在 layouts/_default/ 目录下，新建 ai-chat.html 文件。对话页面的所有前端 HTML 代码都在这里面定义。

开头两段 \<head> 和 \<header> 代码是页面的头部和元信息部分，可以从同一目录下的其他文件里复制过来。

```html
<div id="searchbox">
    <h2>向我提问吧</h2>
    <div class="input-with-button"> <!-- 用户输入框的容器 -->
        <textarea id="question-input" placeholder="在这里输入" aria-label="输入你要问AI的问题" rows="1" oninput="autoResize(this)" onkeypress="if(event.key === 'Enter'){event.preventDefault(); askAI();}"></textarea> 
        <button onclick="askAI()" class="inline-button" aria-label="发送问题">发送</button>
    </div>
</div>
```

相应的 CSS 样式在 assets/css/extended/transition.css 这个文件里定义。
```css
/* 输入框和按钮的包装容器 */
.input-with-button {
    position: relative; /* 为绝对定位的按钮提供参考 */
    display: flex;
    width: 100%; /* 与搜索框同宽 */
    max-width: 800px; /* 限制最大宽度，与原有设计保持一致 */
    margin: 0 auto; /* 居中显示 */
    margin-top: 0.5rem;
}

/* 输入框样式 */
#question-input {
    flex: 1; /* 占据剩余所有空间 */
    padding-right: 70px; /* 为按钮预留空间，防止文字被遮挡 */
    padding: 10px 70px 12px 15px;
    border: 2px solid;
    border-color: var(--tertiary);
    border-radius: 12px; /* 圆角边框 */
    font-size: 16px;
    box-sizing: border-box; /* 确保padding不会影响总宽度 */
    resize: none;
    overflow-y: hidden;
    width: 100%;
    transition: height 0.2s ease;
}

/* 内嵌搜索按钮样式 */
.inline-button {
    position: absolute;
    right: 4px; /* 距离右侧4px */
    bottom: 4px; /* 距离顶部4px */
    height: 36px; /* 比输入框稍矮 */
    padding: 0 16px;
    background: var(--primary); /* 使用颜色主题，主题文件在 themes/hugo-PaperMod/assets/css/core/theme-vars.css */
    border: none;
    border-radius: 20px; /* 稍小的圆角 */
    color: white;
    font-weight: 600;
    cursor: pointer;
    transition: background-color 0.2s ease;
}

/* 按钮悬停效果，会放大一点 */
.inline-button:hover {
    background: var(--primary); /* 使用主题的主色变量 */
    transform: scale(1.02);
}

/*当点击发送后，按钮暂时禁用的效果*/
.inline-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none;
}
```

最初版本的发送样式就只有这些，只有最基本的输入文本框和发送键。后来觉得这样看起来太空旷了，于是加了一个挥手的小熊图片，以及小熊说的话，来引导用户的输入。用户在点击发送后，小熊会退场，真实响应框会取代这个位置。这两段都被包装在一个 api-response-container 容器里。

```html
<div id="api-response-container" style="margin-top: 2rem;">
    <!-- 小熊占位符 -->
    <div id="placeholder" class="chat-placeholder">
        <!--<img src="Bear.jpg" alt="机器熊" class="bear-avatar"> -->
        <img src="{{ "/img/Bearwave.png" | relURL }}" alt="小熊" class="bear-avatar">

        <div class="speech-bubble">
            你好！我是机器熊，是熊熊的助理，我可以帮 TA 回答你的问题。你可以问我跟简历有关的问题，也可以随便聊聊。尽管提问吧！
        </div>
    </div>

    <!-- 真实响应框 -->
    <div id="real-response" class="response-container" style="display: none;">
        <div class="response-header">
            <h2>AI回答</h2>
        </div>
        <div id="api-response-content" class="response-content">
            <!-- API返回的内容将在这里显示 -->
        </div>
    </div>
</div>
```

对应的 CSS 配置如下。

```css
/* 小熊聊天占位符布局 */
.chat-placeholder {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 15px;
    opacity: 0; /* 初始隐藏 */
    transition: opacity 0.8s ease-in-out; /* 淡入过渡 */
}

/* 为了防止加载卡顿，在小熊图片资源加载完成后再淡入显示 */
.chat-placeholder.loaded {
    opacity: 1;
}

/* 小熊头像 */
img.bear-avatar {
    border: none !important;
    width: 150px;
    height: auto;
    flex-shrink: 0;
    box-shadow: none !important; /* 去掉阴影 */
    padding: 0 !important;     /* 去掉内边距 */
    background: transparent !important; /* 避免背景色 */
}

/* 气泡样式 */
.speech-bubble {
    position: relative;
    background: #fff;
    border: 2px solid var(--tertiary);
    border-radius: 12px;
    padding: 12px 16px;
    font-size: 16px;
    line-height: 1.6;
    max-width: 60%;
    text-align: left;
}

/* 气泡小尾巴（指向小熊头像） */
.speech-bubble {
    content: "";
    position: absolute;
    top: 15px;
    left: -12px; /* 让尾巴连到小熊 */
    border-width: 10px 12px 10px 0;
    border-style: solid;
    border-color: transparent #fff transparent transparent;
}

/* 淡入的动画效果 */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
```

到这里为止，纯视觉上的效果就设计完了。

## 动态效果和前后端交互

接下来需要在 HTML 文件里使用 \<script> 标签，定义一些动态效果，以及前后端的交互逻辑。

动态效果如下：

```javascript
// 用户输入框自动根据行数调整高度
function autoResize(textarea) {
    console.log('autoResize function called');
    textarea.style.height = 'auto';
    textarea.style.height = textarea.scrollHeight + 'px';
    
    // 限制最大高度
    if (textarea.scrollHeight > 200) {
        textarea.style.height = '200px';
        textarea.style.overflowY = 'auto';
    } else {
        textarea.style.overflowY = 'hidden';
    }
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', function() {
    const textarea = document.getElementById('question-input');
    if (textarea) {
        // 初始调整一次高度
        setTimeout(() => autoResize(textarea), 100);
    }
});
```

然后来到重头戏，就是 askAI() 和 callAIApi() 这两个函数的逻辑。

askAI() 函数处理了大部分逻辑，包括接收用户的提问、加载时的动效、调用 callAIApi 去触发 HTTP 响应、处理流式传输响应的展示。一些指标也可以在这里记录抓取，比如延迟。流式响应的效果就是 AI 一边生成、页面一边陆续展示已经生成的部分，不必等到全部生成完回答再一次性展示，这样能减少用户的等待时间。但流式响应的处理逻辑也比整段 response 直接输出要复杂很多，需要按行去解析文本；响应格式也从 JSON 变成了 StreamingResponse。

```javascript
async function askAI() {
    const startTime = performance.now();  // 用户点击时间
    const question = document.getElementById('question-input').value.trim(); // 获取用户的问题
    const responseContainer = document.getElementById('api-response-container');
    const responseContent = document.getElementById('api-response-content');
    const placeholder = document.getElementById('placeholder');   // 先获取小熊，为了响应出来后隐藏小熊
    const realResponse = document.getElementById('real-response'); // 获取响应框
    responseContent.innerHTML = ""; // 清空之前内容
    
    if (!question) {
        alert('请输入问题'); // 如果问题框为空就按发送，有报错提示
        return;
    } 
    
    // 点击发送后：隐藏小熊，显示响应框
    placeholder.classList.add('hidden');
    realResponse.classList.remove('hidden');
    realResponse.classList.add('visible');
    
    // 显示加载状态
    responseContent.innerHTML = '<div class="loading">思考中...</div>';
    responseContent.classList.add('loading');
    
    // 禁用按钮防止重复提交
    const sendButton = document.querySelector('.inline-button');
    const originalText = sendButton.textContent;
    sendButton.textContent = '思考中...';
    sendButton.disabled = true;
    
    try {
        // 调用真实的API
        const response = await callAIApi(question); // callAIApi 是发送 API 请求的函数，后面有详细定义
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");

        // 移除加载状态
        responseContent.classList.remove('loading');
        responseContent.innerHTML = "";

        // 显示API返回的内容，用流式响应的逻辑来处理
        let done = false;
        let buffer = "";
        let fullAnswer = "";
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            const chunk = decoder.decode(value, { stream: true });
            buffer += chunk;

            // SSE 按行处理
            let lines = buffer.split(/\r?\n/); // 按照换行符来切分句子
            buffer = lines.pop(); // 最后一行可能不完整，保留到下一轮

            for (let line of lines) {
                line = line.trim();
                if (!line) continue;
                if (line === "data: [DONE]") continue;

                if (line.startsWith("data: ")) {
                    const jsonStr = line.slice(6);
                    try {
                        const parsed = JSON.parse(jsonStr);
                        const content = parsed.choices?.[0]?.delta?.content;
                        if (content) {
                            fullAnswer += content; // fullAnswer 是用于在 Grafana 里记录回答历史和计算延迟
                            // 直接更新内容并应用动画
                            updateContentWithAnimation(responseContent, fullAnswer);
                        }
                    } catch (e) {
                        // 这里只是日志，下一轮继续拼接
                        console.warn("解析 chunk 错误:", e, jsonStr);
                    }
                }
            }
        }

        const endTime = performance.now();         // 记录响应返回时间
        const latencyMs = Math.round(endTime - startTime); // 计算耗时（毫秒）
        console.log(`本次耗时: ${latencyMs} ms`);

        // 发送给后端延时的数据
        await fetch('https://api.bearlybear.com/api/record_latency', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ question, answer: fullAnswer, latency_ms: latencyMs })
        });
        
    } catch (error) {
        responseContent.classList.remove('loading');
        responseContent.innerHTML = `
            <div class="error">
                <p>出错啦: ${error.message}</p>
                <p>请稍后重试或检查网络连接</p>
            </div>
        `;
    } finally {
        // 恢复按钮状态
        sendButton.textContent = originalText;
        sendButton.disabled = false;
    }
}
```

关于流式输出，这里值得单独写一下。在处理这个逻辑的时候遇到了很多报错，还曾经在页面上误展示过很多带标签对的 token 出来。要注意修改几个地方：

1. 后端的 app.py 里调用 API 的接口，需要把 Stream 参数设置为 True。并且在 API 的路由函数里，要把返回类型设置为 StreamingResponse 而非原来的 JSON。
```python
def get_ai_response(prompt):
    # ...
    data = {
    "model": "deepseek-chat",  # 根据实际情况选择模型
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.7,
    "stream": True
    }

    try:
        with requests.post(url, json=data, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if line:
                    yield line + "\n"  # 每行逐块转发给前端
    except requests.exceptions.RequestException as e:
        yield f"data: {json.dumps({'error': f'Deepseek API error: {str(e)}'})}\n\n"

@app.post("/api/ask_stream")
async def ask_stream(request: QuestionRequest):
    prompt = request.question
    return StreamingResponse(get_ai_response(prompt), media_type="text/event-stream")
```

2. 前端对流式输出的处理格式。见上方的 askAI 函数定义。

遇到的问题一：在调试过程中，某次看到网页返回了很多像这样的结果，带着 SSE 流式输出的原始格式就展示在页面上：

data: {"id":"3eaf3e26-564c-4f5b-a5bf-640f39ed8d87","object":"chat.completion.chunk","created":1759677785,"model":"deepseek-chat","system_fingerprint":"fp_ffc7281d48_prod0820_fp8_kvcache","choices":[{"index":0,"delta":{"content":"好的"},"logprobs":null,"finish_reason":null}]}

实际上这些是 token 级别的 JSON，而不是直接可显示的文本。我在后端把原本的 JSON 的 text/plain 整段返回格式改为了 text/event-stream 之后，每次当后端以 SSE（text/event-stream）发送数据时，HTTP 连接不会立即结束，而是不断推送上面这样以 data 开头的数据流。如果此时不针对这样的数据格式做处理，而是直接对整段字符串（包含 data:、空行、换行符）执行了 JSON.parse()，就会出现这个问题。所以前端的 askAI 里面对流式文本的解析有误。

解决方法是，检测以 data 开头的数据流，把冗余标签剥除，然后读取里面的 content 也就是有效回答的文本。

```javascript
// SSE 按行处理
let lines = buffer.split(/\r?\n/); // 按照换行符来切分句子
buffer = lines.pop(); // 最后一行可能不完整，保留到下一轮

for (let line of lines) {
    line = line.trim();
    if (!line) continue;
    if (line === "data: [DONE]") continue;

    if (line.startsWith("data: ")) {
        const jsonStr = line.slice(6); 
        try {
            const parsed = JSON.parse(jsonStr);
            const content = parsed.choices?.[0]?.delta?.content;
        ...}
```

遇到的问题二：出现了回答漏字的情况，可以明显看到语言不连贯，一些字缺失了。页面 F12 控制台中有如下报错：

```console
解析 chunk 错误: SyntaxError: Expected ':' after property name...解析 chunk 错误: SyntaxError: Unterminated string in JSON at position 167 (line 1 column 168) at JSON.parse (<anonymous>) at askAI (ai-chat/:420:45) data: {"id":"04d88ed3-bae9-42eb-8cfd-4780be317940","object":"chat.completion.chunk","created":1759679644,"model":"deepseek-chat","system_fingerprint":"fp_ffc7281d48_prod0820 askAI @ ai-chat/:427 ai-chat/:427
```

这是因为 DeepSeek SSE 流是逐行发送 JSON 块，以换行符 \n 作为结尾。然而在 HTTP/1.1 的分块传输编码（Chunked Transfer Encoding）机制中，当服务器以流的方式返回响应时（比如 Content-Type: text/event-stream），HTTP 不再提前声明 Content-Length，而是把响应拆成一段一段的 chunk 传输。每个 chunk 的大小和边界由底层 TCP 连接决定，而不是应用层（FastAPI 或前端）能控制的。所以，每个 chunk 的边界是任意的，一条 data 可能被截断，而此时还没有到达 SSE 协议中每条消息的换行符 \n 结尾，因此这条 data 后面未完的内容可能就被抛弃了，下一次读取的时候又从最新的 data 开始。而在每次 read 读到数据就直接 JSON.parse 解析成了 line，此时每个 line 有可能只是一部分 JSON 对象，所以导致漏掉了一些字。

修改思路是，每次 reader.read() 读到一个 chunk，先不要去 parse，而是先把它 decode() 成字符串。然后，增加一个 buffer 缓冲区处理，如果 line 只是一部分 JSON（被截断了），就先保存在 buffer，等下一次 read chunk 再拼接成完整 JSON。遇到 data: [DONE] 表示流结束。

```javascript
let done = false;
let buffer = "";
let fullAnswer = "";
while (true) {
    const { value, done } = await reader.read(); // 异步读取流的一小段数据
    if (done) break;
    const chunk = decoder.decode(value, { stream: true }); // 把字节流转为 UTF-8 字符串
    buffer += chunk; // 拼接当前数据块到缓存。

    // SSE 按行处理
    let lines = buffer.split(/\r?\n/); // 按照换行符来切分句子
    buffer = lines.pop(); // 最后一行可能不完整，保留到下一轮

    // 再接逐行解析的逻辑
```

（未完待续）