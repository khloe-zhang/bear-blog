import json
import requests
import time
import os
import argparse
import phoenix as px
from datasets import Dataset
from ragas import evaluate
from ragas.metrics.collections import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
)
from ragas.metrics import Faithfulness, AnswerRelevancy, ContextRecall, ContextPrecision
from ragas.run_config import RunConfig
from ragas.metrics.base import MetricWithLLM, MetricWithEmbeddings
from ragas.llms import llm_factory
from ragas.embeddings import embedding_factory
from ragas.embeddings import OpenAIEmbeddings as RagasOpenAIEmbeddings
from openai import OpenAI
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from phoenix.otel import register
from phoenix.trace import SpanEvaluations
from phoenix.trace import using_project
from phoenix.trace.span_evaluations import TraceEvaluations
from dotenv import load_dotenv
load_dotenv("/home/ubuntu/ai-blog-api/.env")
import pandas as pd

def preflight_check():
    """运行前检查所有依赖，避免跑到一半报错浪费 token"""
    errors = []
    
    # 检查环境变量
    if not os.getenv("DASHSCOPE_API_KEY"):
        errors.append("DASHSCOPE_API_KEY 未设置")
    
    # 检查评测集文件
    if not os.path.exists("eval_set.json"):
        errors.append("eval_set.json 不存在")
    
    # 检查 RAG 接口是否可达
    try:
        r = requests.get("http://localhost:8000/health", timeout=5)
        if r.status_code != 200:
            errors.append(f"/health 接口返回 {r.status_code}")
    except Exception as e:
        errors.append(f"RAG 服务不可达: {e}")
    
    # 检查 Phoenix 是否运行
    try:
        r = requests.get("http://localhost:6006", timeout=5)
    except Exception:
        errors.append("Phoenix 服务不可达，trace 将无法记录")
    
    if errors:
        print("预检失败，请修复以下问题后重试：")
        for e in errors:
            print(f"  ✗ {e}")
        exit(1)
    
    print("预检通过，开始评测...")

# 脚本最开始调用
preflight_check()


# 连接本地 Phoenix
tracer_provider = register(
    project_name="default",
    endpoint="http://localhost:4317",
)


# 1. 加载评测集
with open("eval_set.json", "r", encoding="utf-8") as f:
    eval_data = json.load(f)

# 2. 调用你的 RAG 系统，收集 answer 和 contexts
def query_rag(question: str):
    """调用你现有的 RAG 接口获取回答和检索结果"""
    # 先获取检索结果
    embedding_response = requests.get(
        "http://localhost:8000/api/debug/search",
        params={"q": question}
    )
    print(f"debug/search 状态码: {embedding_response.status_code}")
    print(f"debug/search 响应: {embedding_response.text[:200]}")
    search_result = embedding_response.json()
    contexts = search_result.get("retrieved", [])
    sources = search_result.get("sources", [])

    # 再获取生成的回答（非流式，需要你额外加一个非流式接口）
    answer_response = requests.post(
        "http://localhost:8000/api/ask",
        json={"question": question},
        params={"use_cache": use_cache}
    )
    answer = answer_response.json().get("answer", "")
    
    return answer, contexts

# 3. 构建 RAGAS 所需的数据集格式
questions = []
answers = []
contexts = []
ground_truths = []

CACHE_FILE = "collected_results.json"

# 判断缓存是否存在，存在就直接读取，不存在才重新调用 API
if os.path.exists(CACHE_FILE):
    print("发现缓存，直接从文件读取，跳过 API 调用...")
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    questions = cache["questions"]
    answers = cache["answers"]
    contexts = cache["contexts"]
    ground_truths = cache["ground_truths"]
else:
    print("未发现缓存，开始调用 API 收集结果...")
    questions, answers, contexts, ground_truths = [], [], [], []
    
    for item in eval_data:
        print(f"正在处理 {item['id']}: {item['question']}")
        answer, retrieved_contexts = query_rag(item["question"])
        questions.append(item["question"])
        answers.append(answer)
        contexts.append(retrieved_contexts)
        ground_truths.append(item["ground_truth"])
        time.sleep(1)

    # 收集完立即保存
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "questions": questions,
            "answers": answers,
            "contexts": contexts,
            "ground_truths": ground_truths
        }, f, ensure_ascii=False, indent=2)
    print(f"结果已缓存到 {CACHE_FILE}")

# 4. 转成 RAGAS Dataset 格式
dataset = Dataset.from_dict({
    "question": questions,
    "answer": answers,
    "contexts": contexts,
    "ground_truth": ground_truths,
})

os.environ["OPENAI_API_KEY"] = os.getenv("DASHSCOPE_API_KEY")
qwen_client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
# 定义评测用的 LLM
judge_llm = llm_factory(
    model="qwen-plus-2025-12-01",
    client=qwen_client,
    max_tokens=4000,
    extra_headers={"X-DashScope-SSE": "disable"},
    extra_body={"enable_thinking": False},
    response_format={"type": "json_object"},
)
'''
judge_llm = LangchainLLMWrapper(
    ChatOpenAI(
        model="qwen3.5-27b",
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        n=1,
    )
)
'''
bge_client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url="https://api.siliconflow.cn/v1",
)

os.environ["OPENAI_API_KEY"] = os.getenv("SILICONFLOW_API_KEY")
# Embedding 用的 LLM
'''
judge_embeddings = RagasOpenAIEmbeddings(
    model="BAAI/bge-large-zh-v1.5",
    client=bge_client,
    #api_key=os.getenv("SILICONFLOW_API_KEY"),
    #base_url="https://api.siliconflow.cn/v1",
)
'''
'''
judge_embeddings = embedding_factory(
    model="BAAI/bge-large-zh-v1.5",
    client=bge_client,
)
'''

judge_embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(
    model="BAAI/bge-large-zh-v1.5",
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url="https://api.siliconflow.cn/v1",
))

# 把 LLM 和 Embedding 显式注入每个 metric
#metrics = [faithfulness, answer_relevancy, context_recall, context_precision]
metrics = [
    Faithfulness(),
    AnswerRelevancy(),
    ContextRecall(),
    ContextPrecision(),
]

def init_ragas_metrics(metrics, llm, embedding):
    for metric in metrics:
        if isinstance(metric, MetricWithLLM):
            metric.llm = llm
        if isinstance(metric, MetricWithEmbeddings):
            metric.embeddings = embedding
        metric.init(RunConfig())

#init_ragas_metrics(metrics, judge_llm, judge_embeddings)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RAGAS 评估 + Phoenix 可视化"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "upload"],
        default="full",
        help="运行模式: 'full' (默认, 完整评估+上传), 'upload' (仅上传已有CSV)"
    )
    args = parser.parse_args()
    csv_path = "eval_result.csv"

    # —————— 阶段1: 获取评估结果 DataFrame ——————
    if args.mode == "upload":
        print(f"📂 跳过 RAGAS 评估，加载已有结果: {csv_path}")
        try:
            df = pd.read_csv(csv_path)
            print(f"✅ 成功加载 {len(df)} 条评估结果")
        except FileNotFoundError:
            print(f"❌ 错误: 找不到 {csv_path}，请先运行默认模式生成结果")
            exit(1)

    elif args.mode == "collect":
        print("重新收集答案，生成 Phoenix span...")
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        questions, answers, contexts, ground_truths = [], [], [], []
        for item in eval_data:
            print(f"正在处理 {item['id']}: {item['question']}")
            answer, retrieved_contexts = query_rag(item["question"])
            questions.append(item["question"])
            answers.append(answer)
            contexts.append(retrieved_contexts)
            ground_truths.append(item["ground_truth"])
            time.sleep(1)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "questions": questions,
                "answers": answers,
                "contexts": contexts,
                "ground_truths": ground_truths
            }, f, ensure_ascii=False, indent=2)
        print("✅ 收集完成，现在可以运行 --mode=upload")
        exit(0)

    else:
        # 默认 mode="full"：完整评估
        print("🔄 正在运行 RAGAS 评估（会调用 Judge LLM，请注意 token 消耗）...")
        result = evaluate(
            dataset,
            metrics=metrics,
            llm=judge_llm,
            embeddings=judge_embeddings,
            run_config=RunConfig(
                timeout=60,
                max_retries=2,
                max_workers=1,  # 改成单线程，先确认能跑通
            )
        )
        eval_scores_df = result
        df = eval_scores_df.to_pandas()
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"✅ 评估完成，结果已保存到 {csv_path}")

    # —————— 阶段2: 上传到 Phoenix（通用逻辑）——————
    print("📤 准备将评分上传到 Phoenix...")
    client = px.Client(endpoint="http://localhost:6006")
    spans_df = client.get_spans_dataframe(project_name="default")
    rag_spans = spans_df[spans_df["name"] == "rag_pipeline"].sort_values("start_time", ascending=False).reset_index(drop=True)
    print(f"Phoenix 中找到 {len(rag_spans)} 条 rag_pipeline span")

    if len(rag_spans) == 0:
        print("❌ 未找到匹配的 'rag_pipeline' trace，跳过上传。")
        print("👉 请确保 FastAPI 的 /api/ask 接口已被调用过，并且 Phoenix 正在运行。")
    else:
        rag_spans["question"] = rag_spans["attributes.input"].apply(
            lambda x: json.loads(x).get("question", "") if isinstance(x, str) else x.get("question", "") if isinstance(x, dict) else ""
        )
        span_question_col = "attributes.input.question"
        print("spans_df 中的问题样本:")
        print(rag_spans["question"].head(5).tolist())
        print("\ndf 中的问题样本:")
        print(questions[:5])
        # 合并评分和 span_id
        df_aligned = pd.merge(
            rag_spans[["context.span_id", "question"]],
            df.assign(question=questions),  # df 是 RAGAS 结果，questions 是问题列表
            #left_on=span_question_col,
            on="question",
            how="inner"
        ).set_index("context.span_id")
        df_aligned.index.name = "context.span_id"
        print(f"成功匹配 {len(df_aligned)} 条记录")

        for metric in ["faithfulness", "answer_relevancy", "context_recall", "context_precision"]:
            if metric not in df_aligned.columns:
                continue
            evals_df = df_aligned[[metric]].rename(columns={metric: "score"}).dropna()
            #evals_df = df_aligned[["context.span_id", metric]].dropna()
            if not evals_df.empty:
                client.log_evaluations(SpanEvaluations(eval_name=metric, dataframe=evals_df))
                print(f"✅ 已上传 {metric} 评分 ({len(evals_df)} 条)")
    print("🎉 全部完成！")
    print(rag_spans["attributes.input"].head(3))


    '''改成了兼容没捕捉到trace的逻辑
    # 取最近20条，和评测集对应
    rag_spans = rag_spans.head(len(df)).reset_index(drop=True)

    # 把评分的 index 设成对应的 span_id
    df.index = pd.Index(
        rag_spans["context.span_id"].tolist(),
        name="context.span_id"
    )

    for metric in ["faithfulness", "answer_relevancy", "context_recall", "context_precision"]:
        evals_df = df[[metric]].rename(columns={metric: "score"}).dropna()
        client.log_evaluations(
            SpanEvaluations(eval_name=metric, dataframe=evals_df)
        )
        print(f"已上传 {metric} 评分")
    '''

# 5. 运行评测
# 用 using_project 包裹 evaluate，结果自动发送到 Phoenix
'''
with using_project("default"):
    result = evaluate(
        dataset,
        metrics=metrics,
        llm=judge_llm,
        embeddings=judge_embeddings,
    )
'''
'''之前最新用的是这个，现在都包到 --mode 里了
result = evaluate(
    dataset,
    metrics=metrics,
    llm=judge_llm,
    embeddings=judge_embeddings,
    run_config=RunConfig(
        timeout=60,
        max_retries=2,
        max_workers=1,  # 改成单线程，先确认能跑通
    )
)
'''

#eval_scores_df = result
#eval_scores_df.to_pandas().to_csv("eval_result.csv", index=False, encoding="utf-8-sig")

'''之前最新是这个
eval_scores_df = result  # result 本身就是 EvaluationResult，先转换
df = eval_scores_df.to_pandas()  # 这里才调用 to_pandas()
df.to_csv("eval_result.csv", index=False, encoding="utf-8-sig")
'''
'''
# 设置 index 为 context.trace_id 格式
df.index = [f"trace_{i}" for i in range(len(df))]
df.index.name = "context.trace_id"
'''

'''这些都是之前最新的
client = px.Client(endpoint="http://localhost:6006")

# 从 Phoenix 拉取已有的 rag_pipeline spans
spans_df = client.get_spans_dataframe(project_name="default")
rag_spans = spans_df[spans_df["name"] == "rag_pipeline"].sort_values("start_time", ascending=False)

# 取最近20条，和评测集对应
rag_spans = rag_spans.head(len(df)).reset_index(drop=True)

# 把评分的 index 设成对应的 span_id
df.index = pd.Index(
    rag_spans["context.span_id"].tolist(),
    name="context.span_id"
)

for metric in ["faithfulness", "answer_relevancy", "context_recall", "context_precision"]:
    evals_df = df[[metric]].rename(columns={metric: "score"}).dropna()
    client.log_evaluations(
        SpanEvaluations(eval_name=metric, dataframe=evals_df)
    )
    print(f"已上传 {metric} 评分")

'''
'''之前就注释掉了这个
# 把评测分数附加到对应的 span 上
px.log_evaluations(
    TraceEvaluations(
        eval_name="ragas",
        dataframe=df[["faithfulness", "answer_relevancy", "context_recall", "context_precision"]]
    ),
    endpoint="http://localhost:6006"
)
'''
