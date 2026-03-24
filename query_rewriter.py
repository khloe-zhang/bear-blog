"""
Query Rewrite 模块
用于优化用户查询，提高 RAG 检索效果
"""

import re
import jieba
import difflib
from typing import List, Dict, Tuple
import requests
import os
import json
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class QueryRewriteResult:
    """查询重写结果"""
    original_query: str
    rewritten_queries: List[str]
    confidence_scores: List[float]
    rewrite_type: str  # 'spell_correct', 'synonym_expand', 'ai_rewrite', 'multi_variant'

class QueryRewriter:
    """查询重写器"""
    
    def __init__(self, deepseek_api_key: str = None):
        self.deepseek_api_key = deepseek_api_key or os.getenv("DEEPSEEK_API_KEY")
        
        # 初始化中文同义词库（简化版）
        self.synonyms = {
            "技术": ["技术", "科技", "IT", "编程", "开发", "代码"],
            "学习": ["学习", "学", "掌握", "了解", "研究", "探索"],
            "工作": ["工作", "职业", "事业", "就业", "上班"],
            "生活": ["生活", "日常", "日常", "过日子", "起居"],
            "旅行": ["旅行", "旅游", "游玩", "出行", "观光"],
            "读书": ["读书", "阅读", "看书", "学习", "阅读"],
            "编程": ["编程", "写代码", "开发", "编码", "程序设计"],
            "项目": ["项目", "工程", "任务", "工作", "计划"],
            "经验": ["经验", "经历", "体验", "心得", "体会"],
            "问题": ["问题", "疑问", "困惑", "难题", "困难"],
            "解决": ["解决", "处理", "搞定", "完成", "实现"],
            "帮助": ["帮助", "协助", "支持", "指导", "建议"],
            "如何": ["如何", "怎么", "怎样", "怎么", "如何"],
            "什么": ["什么", "啥", "哪个", "哪些", "何"],
            "为什么": ["为什么", "为啥", "为何", "怎么", "如何"],
            "哪里": ["哪里", "哪儿", "何处", "在哪", "位置"],
            "时候": ["时候", "时间", "何时", "几时", "多久"],
            "多少": ["多少", "几个", "多长", "多大", "多高"],
            "可以": ["可以", "能", "能够", "会", "行"],
            "需要": ["需要", "要", "必须", "得", "应该"],
            "会": ["掌握", "了解", "懂得", "技能", "经历"]
        }
        
        # 常见错别字映射
        self.typo_corrections = {
            "技述": "技术",
            "学息": "学习", 
            "工做": "工作",
            "生话": "生活",
            "旅形": "旅行",
            "读收": "读书",
            "编成": "编程",
            "项木": "项目",
            "经念": "经验",
            "问提": "问题",
            "解绝": "解决",
            "帮住": "帮助",
            "如呵": "如何",
            "什摸": "什么",
            "为什摸": "为什么",
            "那理": "哪里",
            "时侯": "时候",
            "多小": "多少",
            "可一": "可以",
            "须要": "需要",
            "二级": "耳机"
        }
    
    def spell_correct(self, query: str) -> str:
        """拼写纠错"""
        corrected_query = query
        
        # 直接替换常见错别字
        for typo, correct in self.typo_corrections.items():
            corrected_query = corrected_query.replace(typo, correct)
        
        # 使用 difflib 进行模糊匹配纠错
        words = jieba.lcut(corrected_query)
        corrected_words = []
        
        for word in words:
            if len(word) > 1:  # 只对长度大于1的词进行纠错
                # 在已知词汇中查找最相似的词
                candidates = list(self.typo_corrections.keys()) + list(self.typo_corrections.values())
                matches = difflib.get_close_matches(word, candidates, n=1, cutoff=0.8)
                if matches:
                    corrected_word = self.typo_corrections.get(matches[0], matches[0])
                    corrected_words.append(corrected_word)
                else:
                    corrected_words.append(word)
            else:
                corrected_words.append(word)
        
        return ''.join(corrected_words)
    
    def synonym_expand(self, query: str) -> List[str]:
        """同义词扩展"""
        words = jieba.lcut(query)
        expanded_queries = [query]  # 包含原始查询
        
        # 只对关键名词进行同义词扩展，避免过度扩展
        key_words = ["技术", "工作", "经验", "技能", "能力", "掌握", "懂", "会"]
        
        for i, word in enumerate(words):
            if word in self.synonyms and word in key_words:
                # 只选择最相关的1-2个同义词
                relevant_synonyms = [syn for syn in self.synonyms[word] if syn != word][:5]
                for synonym in relevant_synonyms:
                    new_words = words.copy()
                    new_words[i] = synonym
                    expanded_queries.append(''.join(new_words))
        
        return expanded_queries[:3]  # 限制返回3个版本
    
    def ai_rewrite(self, query: str) -> List[str]:
        """使用 AI 进行查询重写"""
        if not self.deepseek_api_key:
            logger.warning("Deepseek API key not found, skipping AI rewrite")
            return [query]
        
        # 只对模糊查询进行 AI 重写，避免过度处理
        if len(query) >= 3 and any(word in query for word in ["什么", "哪些", "如何", "怎么", "相关"]):
            prompt = f"""请将以下用户查询重写为2个更具体的查询版本，用于在知识库中检索相关信息。

原始查询：{query}

要求：
1. 保持原意不变，但让查询更具体
2. 使用更直接的关键词
3. 每个重写版本用换行分隔
4. 只返回重写后的查询，不要其他解释

重写后的查询："""
        else:
            # 对于已经比较具体的查询，不进行 AI 重写
            return [query]

        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 200
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            rewritten_text = result['choices'][0]['message']['content'].strip()
            
            # 分割多行结果
            rewritten_queries = [line.strip() for line in rewritten_text.split('\n') if line.strip()]
            
            # 确保至少返回原始查询
            if not rewritten_queries:
                rewritten_queries = [query]
            
            return rewritten_queries[:3]  # 限制返回3个版本
            
        except Exception as e:
            logger.error(f"AI rewrite failed: {e}")
            return [query]
    
    def generate_query_variants(self, query: str) -> List[str]:
        """生成多种查询变体"""
        variants = []
        
        # 1. 原始查询
        variants.append(query)
        
        # 2. 拼写纠错版本
        corrected = self.spell_correct(query)
        if corrected != query:
            variants.append(corrected)
        
        # 3. 智能同义词扩展（只对关键查询进行）
        if any(keyword in query for keyword in ["技术", "工作", "经验", "技能", "掌握", "懂", "会"]):
            synonym_variants = self.synonym_expand(query)
            # 只添加与原始查询不同的变体
            for variant in synonym_variants:
                if variant != query and variant not in variants:
                    variants.append(variant)
        
        # 3.5 对“公司”进行同义词扩展
        if "公司" in query:
            broad_query = query.replace("公司", "工作 职业 经历")
            variants.append(broad_query)
    
        # 4. AI 重写版本（保守策略）
        ai_variants = self.ai_rewrite(query)
        for variant in ai_variants:
            if variant != query and variant not in variants:
                variants.append(variant)
        
        # 限制变体数量，优先保留最相关的
        if len(variants) > 4:
            # 优先保留：原始查询、拼写纠错、1-2个同义词变体
            priority_variants = [query]
            if corrected != query:
                priority_variants.append(corrected)
            
            # 添加1-2个同义词变体
            for variant in variants[2:]:
                if variant not in priority_variants and len(priority_variants) < 4:
                    priority_variants.append(variant)
            
            variants = priority_variants
        
        return variants[:4]  # 最多返回4个变体
    
    def rewrite_query(self, query: str) -> QueryRewriteResult:
        """主要的查询重写方法"""
        logger.info(f"Rewriting query: {query}")
        
        # 生成查询变体
        rewritten_queries = self.generate_query_variants(query)
        
        # 计算置信度分数（简化版）
        confidence_scores = []
        for i, variant in enumerate(rewritten_queries):
            if i == 0:  # 原始查询
                confidence_scores.append(1.0)
            elif variant == self.spell_correct(query):  # 拼写纠错
                confidence_scores.append(0.9)
            else:  # 其他变体
                confidence_scores.append(0.8)
        
        # 确定重写类型
        if len(rewritten_queries) == 1:
            rewrite_type = "no_change"
        else:
            # 检查具体使用了哪些重写方法
            has_spell_correct = any(q == self.spell_correct(query) and q != query for q in rewritten_queries[1:])
            has_synonym = len(self.synonym_expand(query)) > 1  # 同义词扩展生成了变体
            has_ai_rewrite = len(self.ai_rewrite(query)) > 1   # AI重写生成了变体
            
            if has_spell_correct and not has_synonym and not has_ai_rewrite:
                rewrite_type = "spell_correct"
            elif has_synonym and not has_spell_correct and not has_ai_rewrite:
                rewrite_type = "synonym_expand"
            elif has_ai_rewrite and not has_spell_correct and not has_synonym:
                rewrite_type = "ai_rewrite"
            else:
                rewrite_type = "multi_variant"
        
        result = QueryRewriteResult(
            original_query=query,
            rewritten_queries=rewritten_queries,
            confidence_scores=confidence_scores,
            rewrite_type=rewrite_type
        )
        
        logger.info(f"Query rewrite completed. Type: {rewrite_type}, Variants: {len(rewritten_queries)}")
        return result

# 全局查询重写器实例
query_rewriter = QueryRewriter()
