from fastapi import FastAPI, Depends, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import chromadb
import openai  # 示例，可替换
import prometheus_client
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY, CONTENT_TYPE_LATEST
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from prometheus_client import PROCESS_COLLECTOR, PLATFORM_COLLECTOR
import time
from datetime import datetime
import os
import glob
from langchain.text_splitter import RecursiveCharacterTextSplitter
import requests
import re
import logging
from sqlalchemy.orm import Session
from db import get_db, SessionLocal, init_db, QAHistory
import json
from query_rewriter import QueryRewriter, QueryRewriteResult
import boto3
import shutil
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
import phoenix as px
#from reranker import hybrid_reranker

REINDEX_TOKEN = os.getenv("REINDEX_TOKEN")  # 在 EC2 环境变量里设置同一个 token
BLOG_DIR = "/home/ubuntu/ai-blog-api/rag_documents/blog"
S3_BUCKET = os.getenv("S3_BUCKET")

# 初始化 tracer
def setup_phoenix():
    exporter = OTLPSpanExporter(endpoint="localhost:4317", insecure=True)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return trace.get_tracer(__name__)

tracer = setup_phoenix()

# 配置日志系统
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('rag_debug.log', encoding='utf-8'),  # 保存到文件
        logging.StreamHandler()  # 同时输出到控制台
    ]
)
logger = logging.getLogger(__name__)

# 初始化默认指标
PROCESS_COLLECTOR  # 确保进程收集器被导入
PLATFORM_COLLECTOR  # 确保平台收集器被导入
prometheus_client.start_http_server(0)  # 端口0表示不启动额外服务器

# --- Prometheus监控指标定义 ---
API_REQUEST_COUNT = Counter('api_request_total', 'Total API requests', ['method', 'endpoint', 'status'])
API_REQUEST_DURATION = Histogram('api_request_duration_seconds', 'API request duration', ['endpoint'])

# --- FastAPI应用初始化 ---
app = FastAPI(title="AI Blog API")
init_db()

# 允许前端跨域请求（重要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1313",    # 本地Hugo开发服务器
        "https://bearlybear.com",   # 您的生产域名
        "https://www.bearlybear.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 获取数据库会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# BGE API嵌入模型封装
class BGEAPIEmbedder:
    def __init__(self):
        self.api_key = os.getenv("SILICONFLOW_API_KEY")
        self.url = "https://api.siliconflow.cn/v1/embeddings"
        self.model = "BAAI/bge-m3"

    def encode(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        
        response = requests.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts}
        )
        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings

    def encode_single(self, text):
        """返回单个向量，兼容现有调用方式"""
        return self.encode(text)[0]

# --- 全局变量 ---
embedder = BGEAPIEmbedder()  # 刚才定义好的 BGE Embedding模型
chroma_client = chromadb.Client()
# 获取或创建集合
collection = chroma_client.get_or_create_collection("personal_knowledge")
DOCUMENTS_DIR = "/home/ubuntu/ai-blog-api/rag_documents"

# 初始化查询重写器
query_rewriter = QueryRewriter()

# --- Pydantic模型 ---
class QuestionRequest(BaseModel):
    question: str

def build_knowledge_base():
    """构建或更新RAG知识库的函数"""
    with tracer.start_as_current_span("build_knowledge_base") as span:
        # 清空现有集合，避免重复（根据你的需求决定是否保留）
        global collection
        try:
            # 尝试删除现有集合
            chroma_client.delete_collection("personal_knowledge")
        except:
            pass  # 如果集合不存在，忽略错误

        collection = chroma_client.get_or_create_collection("personal_knowledge")

        all_docs = []
        all_embeddings = []
        all_ids = []
        all_metadatas = [] # 新增元数据列表

        # 支持多种文件格式
        supported_extensions = ('*.txt', '*.md', '*.pdf', '*.docx')
        files_to_process = []
        for ext in supported_extensions:
            files_to_process.extend(
                glob.glob(os.path.join(DOCUMENTS_DIR, '**', ext), recursive=True)
                ) # 递归查找 rag_documents 目录下的所有 txt、md、pdf、docx 文件

        EXCLUDED_FILES = {'_index.md', 'archives.md', 'links.md', 'tech.md', 'tech1.md', 'search.md', 'ai-chat.md'}


        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=600,  # 每个文本块的大小
            chunk_overlap=100  # 块之间的重叠部分
        )

        doc_id = 0
        total_chunks = 0

        # 针对 Markdown 文件，增加清洗步骤，去除 HTML 标签和多余空行，避免干扰分块和检索
        def clean_markdown(text: str) -> str:
            # 去除<figure>标签及其内容，避免图片干扰分块和检索
            text = re.sub(r'<figure>.*?</figure>', '', text, flags=re.DOTALL)
            # 去除多余的空行（连续超过2个换行符压缩成2个）
            text = re.sub(r'\n{3,}', '\n\n', text)
            # 去除代码块结束符被误转成 --- 的情况，分块前，保护代码块边界，先把尾端的 ``` 替换成一个特殊标记，分块后再还原回来
            text = text = text.replace('```', '‹‹‹CODE›››')
            return text.strip()

        for file_path in files_to_process:
            if os.path.basename(file_path) in EXCLUDED_FILES:
                continue
            with tracer.start_as_current_span("process_file") as file_span:
                file_span.set_attribute("file.path", file_path)
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

                    # 加入新的 markdown 支持，用 python-frontmatter 解析 md 文件的 YAML 头部元数据（如标题、标签等），并把它们拼接到正文前面，增强检索召回率
                    elif file_path.endswith('.md'):
                        import frontmatter
                        with open(file_path, 'r', encoding='utf-8') as f:
                            post = frontmatter.load(f)
                        # 把标题拼到正文前面，增强检索召回率
                        title = post.get('title', os.path.basename(file_path))
                        tags = ' '.join([t for t in post.get('tags', []) if t is not None])
                        raw_text = f"标题：{title}\n标签：{tags}\n\n{post.content}" 
                        text = clean_markdown(raw_text)

                    else:
                        continue  # 暂时跳过其他格式

                    # 分割文本
                    chunks = text_splitter.split_text(text)
                    chunks = [chunk.replace('‹‹‹CODE›››', '```') for chunk in chunks]

                    file_span.set_attribute("file.chunk_count", len(chunks))
                    file_span.set_attribute("file.char_count", len(text))

                    # 记录每个 chunk 的预览
                    '''
                    for i, chunk in enumerate(chunks):
                        file_span.set_attribute(f"chunk_{i}.length", len(chunk))
                        file_span.set_attribute(f"chunk_{i}.preview", chunk) # 如果只要预览前200个字符，可以改成 chunk[:200]
                    '''

                    chunks_summary = [
                        {"index": i, "length": len(chunk), "preview": chunk}
                        for i, chunk in enumerate(chunks)
                    ]
                    file_span.set_attribute("chunks", json.dumps(chunks_summary, ensure_ascii=False))

                    total_chunks += len(chunks)

                    # 添加调试：打印分块信息
                    logger.info(f"文件: {file_path}")
                    logger.info(f"总长度: {len(text)} 字符")
                    logger.info(f"分块数量: {len(chunks)}")
                    for i, chunk in enumerate(chunks):
                        logger.info(f"块 {i+1}: {len(chunk)} 字符")
                        logger.info(f"内容预览: {chunk[:100]}...")
                        logger.info("---")

                    for chunk in chunks:
                        # 生成嵌入向量
                        #embedding = embedder.encode(chunk).tolist()[0]  # 注意维度处理
                        embedding = embedder.encode_single(chunk) # 改成 BGE API 之后，直接返回单个向量，不需要再取 [0] 了

                        all_docs.append(chunk)
                        all_embeddings.append(embedding)
                        all_ids.append(f"doc_{doc_id}")
                        all_metadatas.append({"source": os.path.basename(file_path)})  # 可选：添加元数据，如文件来源。os.path.basename(file_path) 的意思是只保留文件名，不包含路径，这样在检索结果中可以直接看到是哪个文件提供的内容，增加可解释性。
                        doc_id += 1

                except Exception as e:
                    print(f"Error processing {file_path}: {str(e)}")
                    continue

        span.set_attribute("total_files", len(files_to_process))
        span.set_attribute("total_chunks", total_chunks)

        # 批量添加到向量数据库
        if all_docs:
            collection.add(
                documents=all_docs,
                embeddings=all_embeddings,
                ids=all_ids,
                metadatas=all_metadatas  # 新增元数据字段，存储文件来源等信息
            )
            print(f"Successfully loaded {len(all_docs)} document chunks into knowledge base.")
        else:
            print("No documents were processed.")


def get_ai_response(prompt):
    """调用Deepseek API获取回答"""
    api_key = os.getenv("DEEPSEEK_API_KEY")
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

def search_with_query_rewrite(original_query: str, collection, embedder, top_k: int = 5):
    """
    使用查询重写进行多版本检索并合并结果，集成重排序功能
    
    Args:
        original_query: 原始用户查询
        collection: ChromaDB 集合
        embedder: 嵌入模型
        top_k: 返回的文档数量
    
    Returns:
        tuple: (合并后的文档列表, 重写结果信息, 是否有相关结果)
    """
    # 1. 查询重写
    rewrite_result = query_rewriter.rewrite_query(original_query)
    logger.info(f"Query rewrite completed. Type: {rewrite_result.rewrite_type}, Variants: {len(rewrite_result.rewritten_queries)}")
    
    # 2. 对每个重写查询进行向量检索
    all_documents = []
    all_distances = []
    
    for i, query in enumerate(rewrite_result.rewritten_queries):
        try:
            # 向量化查询
            query_embedding = embedder.encode(query)

            
            # 检索相关文档
            results = collection.query(
                query_embeddings=query_embedding,
                n_results=top_k
            )
            
            if results['documents'] and results['documents'][0]:
                documents = results['documents'][0]
                distances = results['distances'][0] if 'distances' in results else [0.5] * len(documents)
                
                all_documents.extend(documents)
                all_distances.extend(distances)
                
        except Exception as e:
            logger.error(f"Error processing query variant '{query}': {e}")
            continue
    
    # 3. 结果去重
    if not all_documents:
        return ["No relevant context found."], rewrite_result, False
    
    # 简单的去重策略：基于文档内容相似度
    unique_documents = []
    unique_distances = []
    seen_content = set()
    
    # 按距离排序（距离越小越相关）
    sorted_indices = sorted(range(len(all_documents)), key=lambda i: all_distances[i])
    
    for idx in sorted_indices:
        doc = all_documents[idx]
        # 简单的去重：检查文档内容是否已存在
        doc_hash = hash(doc[:200])  # 使用前100个字符作为去重依据
        if doc_hash not in seen_content:
            seen_content.add(doc_hash)
            unique_documents.append(doc)
            unique_distances.append(all_distances[idx])
    
    logger.info(f"Retrieved {len(unique_documents)} unique documents from {len(rewrite_result.rewritten_queries)} query variants")
    '''
    # 4. 重排序和相关性过滤
    final_documents, relevance_scores, has_relevant = hybrid_reranker.filter_and_rerank(
        original_query, unique_documents, unique_distances, top_k
    )

    if not has_relevant:
        logger.warning("No relevant documents found after reranking")
        return ["No relevant context found."], rewrite_result, False
    '''
    if not unique_documents:
        final_documents = ["No relevant context found."]
        has_relevant = False
    else:
        final_documents = unique_documents[:top_k]
        has_relevant = True

    logger.info(f"Final result: {len(final_documents)} relevant documents after reranking")
    return final_documents, rewrite_result, has_relevant

# 修改ChromaDB客户端初始化
chroma_client = chromadb.PersistentClient(path="./chroma_db")  # 数据将保存在当前目录的chroma_db文件夹中
collection = chroma_client.get_or_create_collection("personal_knowledge")

# 用于 RAG 评测的 ask 接口，不用流式输出，直接返回
@app.post("/api/ask")
async def ask(request: QuestionRequest, db: Session = Depends(get_db)):
    print("🔥 进入 /api/ask，准备创建 rag_pipeline span")
    with tracer.start_as_current_span("rag_pipeline") as span:
        span.set_attribute("input.question", request.question)

        if use_cache:
            # 从本地缓存读取 answer（不调 DeepSeek，但 trace 已记录）
            cached_answer = get_answer_from_cache(request.question)
            return JSONResponse(content={"answer": cached_answer})


        """非流式接口，供评测脚本使用"""
        retrieved_docs, rewrite_result, has_relevant = search_with_query_rewrite(
            request.question, collection, embedder, top_k=5
        )
        span.set_attribute("retrieval.has_relevant", has_relevant)
        if not has_relevant:
            return JSONResponse(content={"answer": "抱歉，根据我现有的背景信息，我无法回答这个问题。"})

        context_str = "\n".join(retrieved_docs)
    	# 添加查询重写信息到Prompt中
        rewrite_info = ""
        if rewrite_result.rewrite_type != "no_change":
            rewrite_info = f"""
    	【查询优化信息】
    	原始查询：{rewrite_result.original_query}
    	优化类型：{rewrite_result.rewrite_type}
    	生成了 {len(rewrite_result.rewritten_queries)} 个查询变体以提高检索效果
    	"""

        prompt = f"""我的名字叫熊熊，你是我的AI助手。请根据下面提供的关于我的背景信息来帮我回答用户问题。
    	{rewrite_info}
    	【背景信息】
    	{context_str}

    	【用户问题】
    	{request.question}

    	【回答要求】
    	1. 假装你就是我，全部使用第一人称视角回答（如"我曾经..."）。
    	2. 基于我的背景信息中的内容回答问题。
    	3. 如果背景信息不包含答案，请表达根据已有信息你无法回答这个问题，但可以使用生动的语气，比如"这个问题熊熊没有告诉过我，如果你真的很想知道，请找熊熊当面聊聊~"。只有在这种情况下，你才可以跳出第一人称视角回答，其他时候都要装作是我。
    	4. 风格自然亲切，但保持专业。
    	5. 不要编造背景信息中不存在的内容。
    	6. 如果用户的问题有错别字或表达不够清晰，你可以自然地纠正并回答。
    	7. 现在的时间是2026年1月，回答中的时态要参照现在的时间基准。
    	"""

    	# 非流式调用 Deepseek
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False  # 关键：关闭流式
            },
            timeout=30
        )
        answer = response.json()["choices"][0]["message"]["content"]
        return JSONResponse(content={"answer": answer})


# --- API路由 ---
@app.post("/api/ask_stream")
async def ask_stream(request: QuestionRequest, db: Session = Depends(get_db)):
    try:
        # 加上 tracing span，记录整个RAG流程的性能数据
        with tracer.start_as_current_span("rag_pipeline") as span:
            span.set_attribute("input.question", request.question)

            # 1. 使用查询重写进行多版本检索，不集成重排序
            with tracer.start_as_current_span("retrieval"):
                retrieved_docs, rewrite_result, has_relevant = search_with_query_rewrite(
                    request.question, collection, embedder, top_k=5
                )
                span.set_attribute("retrieval.has_relevant", has_relevant)

            # 2. 检查是否有相关结果
            if not has_relevant:
                # 没有相关结果，直接拒答
                refusal_response = f"""data: {json.dumps({
                    "id": "refusal",
                    "object": "chat.completion.chunk", 
                    "created": int(time.time()),
                    "model": "deepseek-chat",
                    "choices": [{
                        "index": 0,
                        "delta": {
                            "content": "抱歉，根据我现有的背景信息，我无法回答这个问题。如果你真的很想知道，建议找熊熊当面聊聊~"
                        },
                        "finish_reason": "stop"
                    }]
                })}\n\n"""
            
                # 记录拒答情况
                try:
                    config = {
                        "model": 2, "chunk_size": 600, "top_k": 5, "overlap": 100,
                        "split": 0, "rerank": 0, "keyword": 0, "rewrite": 1,
                        "rewrite_type": rewrite_result.rewrite_type,
                        "rewritten_queries": rewrite_result.rewritten_queries,
                        "confidence_scores": rewrite_result.confidence_scores,
                        "total_variants": len(rewrite_result.rewritten_queries),
                        "refusal_reason": "no_relevant_documents"
                    }
                    
                    query_record = QAHistory(
                        question=request.question,
                        answer="[REFUSED] No relevant documents found",
                        latency_ms=0.0,
                        config=json.dumps(config)
                    )
                    db.add(query_record)
                    db.commit()
                    
                except Exception as e:
                    logger.error(f"Failed to record refusal: {e}")
                
                return StreamingResponse(
                    iter([refusal_response + "data: [DONE]\n\n"]), 
                    media_type="text/event-stream"
                )

            with tracer.start_as_current_span("generation"):
                # 3. 构建增强的Prompt
                context_str = "\n".join(retrieved_docs)
                
                # 添加查询重写信息到Prompt中
                rewrite_info = ""
                if rewrite_result.rewrite_type != "no_change":
                    rewrite_info = f"""
                【查询优化信息】
                原始查询：{rewrite_result.original_query}
                优化类型：{rewrite_result.rewrite_type}
                生成了 {len(rewrite_result.rewritten_queries)} 个查询变体以提高检索效果
                """
                
                prompt = f"""我的名字叫熊熊，你是我的AI助手。请根据下面提供的关于我的背景信息来帮我回答用户问题。
                {rewrite_info}
                【背景信息】
                {context_str}

                【用户问题】
                {request.question}

                【回答要求】
                1. 假装你就是我，全部使用第一人称视角回答（如"我曾经..."）。
                2. 基于我的背景信息中的内容回答问题。
                3. 如果背景信息不包含答案，请表达根据已有信息你无法回答这个问题，但可以使用生动的语气，比如"这个问题熊熊没有告诉过我，如果你真的很想知道，请找熊熊当面聊聊~"。只有在这种情况下，你才可以跳出第一人称视角回答，其他时候都要装作是我。
                4. 风格自然亲切，但保持专业。
                5. 不要编造背景信息中不存在的内容。
                6. 如果用户的问题有错别字或表达不够清晰，你可以自然地纠正并回答。
                7. 现在的时间是2026年1月，回答中的时态要参照现在的时间基准。
                """

                # 记录成功的请求
                API_REQUEST_COUNT.labels(method='POST', endpoint='/ask_stream', status='200').inc()
                return StreamingResponse(get_ai_response(prompt), media_type="text/event-stream")

    except Exception as e:
        # 记录失败的请求
        API_REQUEST_COUNT.labels(method='POST', endpoint='/ask_stream', status='500').inc()
        logger.error(f"Error in ask_stream: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

class LatencyRecord(BaseModel):
    question: str
    answer: str
    latency_ms: float     # 前端测量的总耗时

@app.post("/api/record_latency")
async def record_latency(record: LatencyRecord, db: Session = Depends(get_db)):
    """创建新的延时记录，不再更新现有记录 """
    try:
        config = {"model": 2, "chunk_size": 600, "top_k": 5, "overlap": 100, "split": 0, "rerank": 0, "keyword": 0, "rewrite": 1}
        new_record = QAHistory(
            question=record.question,
            answer=record.answer,
            latency_ms=record.latency_ms,
            config=json.dumps(config)
        )
        db.add(new_record)
        db.commit()
        db.refresh(new_record)

        return JSONResponse(content={"status": "ok", "id": new_record.id, "latency_ms": record.latency_ms})

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"记录延迟失败: {str(e)}")


'''
# 这个接口把流式传输的内容发给前端
@app.post("/api/ask_stream")
async def ask_stream(request: QuestionRequest):
    prompt = request.question
    return StreamingResponse(get_ai_response(prompt), media_type="text/event-stream")
'''

@app.on_event("startup")
async def startup_event():
    """应用启动时初始化"""
    print("Building knowledge base...")
    build_knowledge_base()
    print("Knowledge base built successfully.")

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

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "service": "AI Blog API"}

@app.post("/api/query_rewrite_test")
async def test_query_rewrite(request: QuestionRequest):
    """测试查询重写功能的端点"""
    try:
        rewrite_result = query_rewriter.rewrite_query(request.question)
        
        return JSONResponse(content={
            "original_query": rewrite_result.original_query,
            "rewritten_queries": rewrite_result.rewritten_queries,
            "confidence_scores": rewrite_result.confidence_scores,
            "rewrite_type": rewrite_result.rewrite_type,
            "total_variants": len(rewrite_result.rewritten_queries)
        })
    except Exception as e:
        logger.error(f"Error in query rewrite test: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/debug/search")
async def debug_search(q: str):
    """测试检索某个关键词"""
    #embedding = embedder.encode(q)
    embedding = embedder.encode_single(q)
    results = collection.query(
        query_embeddings=[embedding],
        n_results=5
    )
    return JSONResponse(content={
        "query": q,
        "retrieved": results["documents"][0],
        "sources": results["metadatas"][0]
    })

# Github Actions 触发，EC2 上的 FastAPI 接口接收请求后从 S3 拉取最新 markdown，重建知识库
@app.post("/api/reindex")
async def reindex(request: Request):
    # token 验证，防止任意人触发
    token = request.headers.get("X-Reindex-Token")
    if token != REINDEX_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # 从 S3 拉取最新 markdown
        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        
        # 清空本地 blog 目录
        shutil.rmtree(BLOG_DIR, ignore_errors=True)
        os.makedirs(BLOG_DIR, exist_ok=True)
        
        # 下载所有 markdown 文件
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="blog-content/"):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                filename = os.path.basename(key)
                if filename.endswith(".md"):
                    local_path = os.path.join(BLOG_DIR, filename)
                    s3.download_file(S3_BUCKET, key, local_path)
                    logger.info(f"Downloaded: {filename}")
        
        # 重建知识库
        build_knowledge_base()
        return JSONResponse(content={"status": "ok", "message": "知识库重建完成"})
    
    except Exception as e:
        logger.error(f"Reindex failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 初始化知识库（首次运行时调用） ---
# build_knowledge_base() # 取消注释并在实现后运行一次
