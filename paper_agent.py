# Copyright (c) 2024 Bytedance Ltd. and/or its affiliates
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import re
import json
import threading
from paper_node import PaperNode
from models     import Agent
from datetime   import datetime
from utils      import (
    search_paper_by_title,
    google_search_arxiv_id,
    search_paper_by_arxiv_id,
    search_section_by_arxiv_id
)

class PaperAgent:
    """
    PaperAgent类实现了一个智能论文搜索和扩展代理
    
    主要功能:
    1. 根据用户查询生成搜索关键词
    2. 使用Google搜索API查找相关论文
    3. 使用选择器模型评估论文相关性
    4. 通过引用关系扩展搜索范围
    5. 构建论文引用树结构
    
    工作流程:
    1. 初始化: 设置用户查询、爬虫模型、选择器模型等参数
    2. 搜索阶段: 生成搜索查询并并行搜索相关论文
    3. 扩展阶段: 从已找到的论文中提取引用关系，进一步扩展搜索范围
    4. 多轮扩展: 可以设置多轮扩展，构建更深层次的引用关系树
    """
    def __init__(
        self,
        user_query:     str,
        crawler:        Agent, # prompt(s) -> response(s)
        selector:       Agent, # prompt(s) -> score(s)
        end_date:       str = datetime.now().strftime("%Y%m%d"),
        prompts_path:   str = "agent_prompt.json",
        expand_layers:  int = 2,
        search_queries: int = 5,
        search_papers:  int = 10, # per query
        expand_papers:  int = 20, # per layer
        threads_num:    int = 20, # number of threads in parallel at the same time
    ) -> None:
        """
        初始化PaperAgent
        
        参数:
            user_query: 用户查询字符串
            crawler: 用于生成搜索查询和提取论文内容的模型
            selector: 用于评估论文相关性的模型
            end_date: 搜索论文的截止日期
            prompts_path: 提示模板文件路径
            expand_layers: 扩展层数，决定引用树的深度
            search_queries: 每个用户查询生成的搜索关键词数量
            search_papers: 每个搜索关键词返回的论文数量
            expand_papers: 每层扩展时处理的论文数量
            threads_num: 并行处理的线程数
        """
        self.user_query = user_query
        self.crawler    = crawler
        self.selector   = selector
        self.end_date   = end_date
        self.prompts    = json.load(open(prompts_path))
        # 创建根节点，存储用户查询
        self.root       = PaperNode({
            "title": user_query,
            "extra": {
                "touch_ids": [],           # 已处理过的论文ID列表
                "crawler_recall_papers": [], # 所有爬取到的论文标题
                "recall_papers": [],         # 相关性评分大于0.5的论文标题
            }
        })

        # 超参数设置
        self.expand_layers   = expand_layers
        self.search_queries  = search_queries
        self.search_papers   = search_papers
        self.expand_papers   = expand_papers
        self.threads_num     = threads_num
        self.papers_queue    = []  # 待扩展的论文队列
        self.expand_start    = 0   # 当前扩展层在队列中的起始位置
        self.lock            = threading.Lock()  # 线程锁，用于保护共享资源
        # 正则表达式模板，用于提取引用、搜索和扩展内容
        self.templates       = {
            "cite_template":   r"~\\cite\{(.*?)\}",  # 提取引用
            "search_template": r"Search\](.*?)\[",   # 提取搜索查询
            "expand_template": r"Expand\](.*?)\["    # 提取扩展内容
        }
    
    @staticmethod
    def do_parallel(func, args, num):
        """
        并行执行函数
        
        参数:
            func: 要执行的函数
            args: 函数参数
            num: 并行线程数
        """
        threads = []
        for _ in range(num):
            thread = threading.Thread(target=func, args=args)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

    def search_paper(self, queries):
        """
        根据查询列表搜索论文
        
        参数:
            queries: 搜索查询列表
        """
        while queries:
            # 从查询列表中取出一个查询
            with self.lock:
                query, self.root.child[query] = queries.pop(), []
            # 使用Google搜索API查找相关论文的arXiv ID
            pre_arxiv_ids, searched_papers = google_search_arxiv_id(query, self.search_papers, self.end_date), []
            # 处理每个找到的arXiv ID
            for arxiv_id in pre_arxiv_ids:
                arxiv_id = arxiv_id.split('v')[0]  # 移除版本号
                self.lock.acquire()
                # 检查是否已处理过该论文
                if arxiv_id not in self.root.extra["touch_ids"]:
                    self.root.extra["touch_ids"].append(arxiv_id)
                    self.lock.release()
                    # 获取论文详细信息
                    paper = search_paper_by_arxiv_id(arxiv_id)
                    if paper is not None:
                        searched_papers.append(paper)
                else:
                    self.lock.release()
            
            # 使用选择器模型评估论文相关性
            select_prompts  = [self.prompts["get_selected"].format(title=paper["title"], abstract=paper["abstract"], user_query=self.user_query) for paper in searched_papers]
            scores = self.selector.infer_score(select_prompts)
            # 处理评估结果
            with self.lock:
                for score, paper in zip(scores, searched_papers):
                    self.root.extra["crawler_recall_papers"].append(paper["title"])
                    # 相关性评分大于0.5的论文被认为是相关的
                    if score > 0.5:
                        self.root.extra["recall_papers"].append(paper["title"])
                    # 创建论文节点
                    paper_node = PaperNode({
                        "title":        paper["title"],
                        "arxiv_id":     paper["arxiv_id"],
                        "depth":        0,
                        "abstract" :    paper["abstract"],
                        "sections" :    paper["sections"],
                        "source":       "Search " + paper["source"],
                        "select_score": score,
                        "extra":        {}
                    })
                    # 将论文节点添加到根节点的子节点中
                    self.root.child[query].append(paper_node)
                    # 将论文节点添加到待扩展队列中
                    self.papers_queue.append(paper_node)

    def search(self):
        """
        执行搜索阶段
        
        1. 使用爬虫模型生成搜索查询
        2. 并行执行搜索
        """
        # 生成搜索查询
        prompt = self.prompts["generate_query"].format(user_query=self.user_query).strip()
        queries = self.crawler.infer(prompt)
        # 提取搜索查询
        queries = [q.strip() for q in re.findall(self.templates["search_template"], queries, flags=re.DOTALL)][:self.search_queries]
        # 并行执行搜索
        PaperAgent.do_parallel(self.search_paper, (queries,), len(queries))

    def get_paper_content(self, new_expand, crawl_prompts, have_full_paper):
        """
        获取论文内容并准备扩展
        
        参数:
            new_expand: 待扩展的论文列表
            crawl_prompts: 爬虫提示列表
            have_full_paper: 已获取完整内容的论文列表
        """
        while new_expand:
            # 从待扩展列表中取出一个论文
            with self.lock:
                if new_expand:
                    paper = new_expand.pop(0)
                else:
                    break
            
            # 如果论文没有章节信息，则获取章节信息
            if paper.sections == "":
                paper.sections = search_section_by_arxiv_id(paper.arxiv_id, self.templates["cite_template"])
                if not paper.sections:
                    paper.extra["expand"] = "get full paper error"
                    continue
            
            # 标记论文为未扩展
            paper.extra["expand"] = "not expand"
            # 生成选择章节的提示
            prompt = self.prompts["select_section"].format(user_query=self.user_query, title=paper.title, abstract=paper.abstract, sections=paper.sections.keys()).strip()
            with self.lock:
                have_full_paper.append(paper)
                crawl_prompts.append(prompt)

    def search_ref(self, section_sources_ori, select_prompts, section_sources, lock):
        """
        搜索引用论文
        
        参数:
            section_sources_ori: 原始章节引用列表
            select_prompts: 选择器提示列表
            section_sources: 章节引用列表
            lock: 线程锁
        """
        while section_sources_ori:
            # 从原始章节引用列表中取出一个引用
            with lock:
                if section_sources_ori:
                    section, title = section_sources_ori.pop(0)
                else:
                    break
            
            # 根据标题搜索论文
            searched_paper = search_paper_by_title(title)
            if searched_paper is None:
                continue
            
            # 检查是否已处理过该论文
            arxiv_id = searched_paper["arxiv_id"]
            with lock:
                if arxiv_id not in self.root.extra["touch_ids"]:
                    self.root.extra["touch_ids"].append(arxiv_id)
                else:
                    continue
            # 生成选择器提示
            prompt = self.prompts["get_selected"].format(title=title, abstract=searched_paper["abstract"], user_query=self.user_query)
            with lock:
                select_prompts.append(prompt)
                section_sources.append([section, searched_paper])

    def do_expand(self, depth, have_full_paper, crawl_results):
        """
        执行扩展操作
        
        参数:
            depth: 当前扩展深度
            have_full_paper: 已获取完整内容的论文列表
            crawl_results: 爬虫结果列表
        """
        while have_full_paper:
            # 从已获取完整内容的论文列表中取出一个论文
            with self.lock:
                if have_full_paper:
                    paper = have_full_paper.pop(0)
                    crawl_result = crawl_results.pop(0)
                else:
                    break
            # 提取扩展内容
            crawl_result = re.findall(self.templates["expand_template"], crawl_result, flags=re.DOTALL)
            section_sources_ori = []
            # 处理每个章节
            for section in crawl_result:
                section = section.strip()
                if section not in paper.sections:
                    continue
                # 处理章节中的引用
                for ref in paper.sections[section]:
                    section_sources_ori.append([section, ref])
            # 并行搜索引用论文
            select_prompts, section_sources, lock = [], [], threading.Lock()
            PaperAgent.do_parallel(self.search_ref, (section_sources_ori, select_prompts, section_sources, lock), self.threads_num * 3)
            # 评估引用论文的相关性
            scores = self.selector.infer_score(select_prompts)
            # 处理评估结果
            for score, (section, ref_paper) in zip(scores, section_sources):
                self.root.extra["crawler_recall_papers"].append(ref_paper["title"])
                # 相关性评分大于0.5的论文被认为是相关的
                if score > 0.5:
                    self.root.extra["recall_papers"].append(ref_paper["title"])
                # 创建引用论文节点
                paper_node = PaperNode({
                    "title":        ref_paper["title"],
                    "depth":        depth + 1,
                    "arxiv_id":     ref_paper["arxiv_id"],
                    "abstract" :    ref_paper["abstract"],
                    "sections" :    ref_paper["sections"],
                    "source":       "Expand " + ref_paper["source"],
                    "select_score": score,
                    "extra":        {}
                })

                # 将引用论文节点添加到原论文的对应章节子节点中
                with self.lock:
                    if section not in paper.child:
                        paper.child[section] = []
                    paper.child[section].append(paper_node)
                    paper.extra["expand"] = "success"
                    # 将引用论文节点添加到待扩展队列中
                    self.papers_queue.append(paper_node)

    def expand(self, depth):
        """
        执行扩展阶段
        
        参数:
            depth: 当前扩展深度
        """
        # 对待扩展的论文按相关性评分排序
        expand_papers = sorted(self.papers_queue[self.expand_start:], key=PaperNode.sort_paper, reverse=True)
        self.papers_queue = self.papers_queue[:self.expand_start] + expand_papers
        # 如果不是第一层扩展，则限制扩展论文数量
        if depth > 0:
            expand_papers = expand_papers[:self.expand_papers]
        # 更新扩展起始位置
        self.expand_start = len(self.papers_queue)
        # 准备扩展
        crawl_prompts, have_full_paper = [], []
        # 并行获取论文内容
        PaperAgent.do_parallel(self.get_paper_content, (expand_papers, crawl_prompts, have_full_paper), self.threads_num)
        # 使用爬虫模型提取扩展内容
        crawl_results = self.crawler.batch_infer(crawl_prompts)
        # 并行执行扩展
        PaperAgent.do_parallel(self.do_expand, (depth, have_full_paper, crawl_results), self.threads_num)

    def run(self):
        """
        运行PaperAgent
        
        1. 执行搜索阶段
        2. 执行多轮扩展阶段
        """
        # 执行搜索阶段
        self.search()
        # 执行多轮扩展阶段
        for depth in range(self.expand_layers):
            self.expand(depth)
