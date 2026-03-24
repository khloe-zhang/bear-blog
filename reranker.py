"""
Rerank 重排模块
用于提升 RAG 检索结果的相关性
"""

import torch
import numpy as np
from typing import List, Dict, Tuple
import logging
from transformers import AutoTokenizer, AutoModelForSequenceClassification


logger = logging.getLogger(__name__)

class Reranker:
    """重排序器"""
    
    def __init__(self, model_name: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        """
        初始化重排序器
        
        Args:
            model_name: 交叉编码器模型名称
        """
        try:
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            
            # 将模型移动到设备
            self.model.to(self.device)
            self.model.eval()
            
            logger.info(f"Reranker initialized with model: {model_name}, device: {self.device}")
        except Exception as e:
            logger.error(f"Failed to initialize reranker: {e}")
            self.model = None
            self.tokenizer = None
    
    def rerank(self, query: str, documents: List[str], top_k: int = 3) -> Tuple[List[str], List[float]]:
        """
        对文档进行重排序
        
        Args:
            query: 查询文本
            documents: 候选文档列表
            top_k: 返回的文档数量
            
        Returns:
            tuple: (重排序后的文档列表, 相关性分数列表)
        """
        if not self.model or not self.tokenizer or not documents:
            return documents[:top_k], [0.5] * min(len(documents), top_k)
        
        try:
            # 构建查询-文档对
            queries = [query] * len(documents)
            
            # 使用 tokenizer 处理输入
            features = self.tokenizer(
                queries, 
                documents, 
                padding=True, 
                truncation=True, 
                return_tensors="pt"
            )
            
            # 将输入移动到设备
            features = {k: v.to(self.device) for k, v in features.items()}
            
            # 计算相关性分数
            with torch.no_grad():
                scores = self.model(**features).logits
                # 将 logits 转换为概率分数
                scores = torch.sigmoid(scores).squeeze().cpu().numpy()
            
            # 如果只有一个文档，确保 scores 是数组
            if scores.ndim == 0:
                scores = np.array([scores])
            
            # 按分数排序
            scored_docs = list(zip(documents, scores))
            scored_docs.sort(key=lambda x: x[1], reverse=True)
            
            # 返回 top_k 结果
            reranked_docs = [doc for doc, score in scored_docs[:top_k]]
            reranked_scores = [float(score) for doc, score in scored_docs[:top_k]]
            
            logger.info(f"Reranked {len(documents)} documents, returning top {len(reranked_docs)}")
            return reranked_docs, reranked_scores
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return documents[:top_k], [0.5] * min(len(documents), top_k)
    '''
    def is_relevant(self, query: str, document: str, threshold: float = 0.5) -> bool:
        """
        判断文档是否与查询相关
        
        Args:
            query: 查询文本
            document: 文档文本
            threshold: 相关性阈值
            
        Returns:
            bool: 是否相关
        """
        if not self.model or not self.tokenizer:
            return True  # 如果模型不可用，默认认为相关
        
        try:
            # 使用 tokenizer 处理输入
            features = self.tokenizer(
                [query], 
                [document], 
                padding=True, 
                truncation=True, 
                return_tensors="pt"
            )
            
            # 将输入移动到设备
            features = {k: v.to(self.device) for k, v in features.items()}
            
            # 计算相关性分数
            with torch.no_grad():
                scores = self.model(**features).logits
                score = torch.sigmoid(scores).squeeze().cpu().item()
            
            return score >= threshold
        except Exception as e:
            logger.error(f"Relevance check failed: {e}")
            return True  # 出错时默认认为相关
        '''
class HybridReranker:
    """混合重排序器"""
    
    def __init__(self, 
                 vector_threshold: float = 0.2,
                 rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"):
        """
        初始化混合重排序器
        
        Args:
            vector_threshold: 向量相似度阈值
            rerank_model: 重排序模型名称
        """
        self.vector_threshold = vector_threshold
        self.reranker = Reranker(rerank_model)
        
        logger.info(f"HybridReranker initialized: vector_threshold={vector_threshold}")
    
    def filter_and_rerank(self, 
                         query: str, 
                         documents: List[str], 
                         distances: List[float],
                         top_k: int = 3) -> Tuple[List[str], List[float], bool]:
        """
        过滤和重排序文档
        
        Args:
            query: 查询文本
            documents: 候选文档列表
            distances: 向量距离列表
            top_k: 返回的文档数量
            
        Returns:
            tuple: (最终文档列表, 相关性分数列表, 是否有相关结果)
        """
        if not documents:
            return [], [], False
        
        # 第一层：向量相似度过滤
        filtered_docs = []
        filtered_distances = []
        
        for doc, dist in zip(documents, distances):
            # 距离越小越相似，所以用 1 - distance 作为相似度
            similarity = 1 - dist
            if similarity >= self.vector_threshold:
                filtered_docs.append(doc)
                filtered_distances.append(dist)
        
        logger.info(f"Vector filtering: {len(documents)} -> {len(filtered_docs)} documents")
        
        if not filtered_docs:
            logger.warning("No documents passed vector similarity threshold")
            return [], [], False
        
        # 第二层：重排序
        reranked_docs, rerank_scores = self.reranker.rerank(
            query, filtered_docs, top_k=top_k
        )
        
        logger.info(f"Reranking completed: {len(filtered_docs)} -> {len(reranked_docs)} documents")
        
        has_relevant = len(reranked_docs) > 0
        return reranked_docs, rerank_scores, has_relevant
    
    def get_relevance_score(self, query: str, document: str) -> float:
        """
        获取查询和文档的相关性分数
        
        Args:
            query: 查询文本
            document: 文档文本
            
        Returns:
            float: 相关性分数 (0-1)
        """
        if not self.reranker.model or not self.reranker.tokenizer:
            return 0.5
        
        try:
            # 使用 tokenizer 处理输入
            features = self.reranker.tokenizer(
                [query], 
                [document], 
                padding=True, 
                truncation=True, 
                return_tensors="pt"
            )
            
            # 将输入移动到设备
            features = {k: v.to(self.reranker.device) for k, v in features.items()}
            
            # 计算相关性分数
            with torch.no_grad():
                scores = self.reranker.model(**features).logits
                score = torch.sigmoid(scores).squeeze().cpu().item()
            
            return score
        except Exception as e:
            logger.error(f"Failed to get relevance score: {e}")
            return 0.5

# 全局重排序器实例
hybrid_reranker = HybridReranker()
