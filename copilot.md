### Q: paper_agent是如何实现的？
A: `paper_agent` 是一个用于高级学术文献搜索的类，其核心功能是通过用户输入的查询，递归地搜索相关的论文、分析引用网络，并扩展相关内容。以下是其实现的关键点：

1. **核心类 `PaperAgent`**:
   - 初始化时接收用户查询 (`user_query`)、两个模型代理 (`crawler` 和 `selector`)、及多个控制参数（搜索层数、查询数量、线程数等）。
   - 使用 `crawler` 模型生成搜索查询，调用 Google API 和 arXiv API 获取论文信息。
   - `selector` 模型为每篇论文生成相关性分数，用于筛选高相关性的论文。

2. **主要方法**:
   - `search`: 基于用户查询生成初步的搜索结果，筛选高相关性论文并构建初始的论文树。
   - `expand`: 对已有论文的引用展开搜索，通过递归地分析扩展论文的引用网络，逐步构建更完整的知识图谱。
   - `run`: 整合 `search` 和 `expand` 方法，完成多层次的搜索和引用扩展。

3. **多线程并行处理**:
   - 大量操作（如论文搜索、引用扩展）通过多线程优化，提高效率。

4. **论文树结构**:
   - 使用 `PaperNode` 类构建论文树，每个节点代表一篇论文，包含标题、摘要、arXiv ID、引用信息、来源等。

您可以通过[此链接](https://github.com/bytedance/pasa/blob/main/paper_agent.py)查看完整代码实现。

### Q:如何实现多次搜索和expand， 以及最后会生成总结报告吗？
A: 在 `PaSa` 的实现中，多次搜索和扩展（expand）是通过递归调用和多线程并行处理实现的。以下是具体的实现和是否生成总结报告的说明：

---

### **多次搜索和扩展的实现**
1. **搜索阶段 (`search`)**:
   - **搜索查询生成**: 使用 `crawler` 模型，根据用户查询生成一组搜索关键词。
   - **论文搜索**:
     - 通过 Google Search API 和 arXiv API 搜索与关键词相关的论文。
     - 每篇论文的标题和摘要会传递给 `selector` 模型，生成一个相关性得分。
     - 相关性得分高于阈值的论文被保留下来并加入到论文树中。

   - 代码示例：
     ```python
     def search(self):
         prompt = self.prompts["generate_query"].format(user_query=self.user_query).strip()
         queries = self.crawler.infer(prompt)
         queries = [q.strip() for q in re.findall(self.templates["search_template"], queries, flags=re.DOTALL)][:self.search_queries]
         PaperAgent.do_parallel(self.search_paper, (queries,), len(queries))
     ```

2. **扩展阶段 (`expand`)**:
   - **引用扩展**: 对于搜索得到的论文，分析其引用网络，递归地搜索相关引用的论文。
   - **并行处理**:
     - 多线程处理引用扩展，优化大规模论文网络的处理效率。
   - 每层扩展会更新论文树，并筛选出高质量的引用文献。

   - 代码示例：
     ```python
     def expand(self, depth):
         expand_papers = sorted(self.papers_queue[self.expand_start:], key=PaperNode.sort_paper, reverse=True)
         self.papers_queue = self.papers_queue[:self.expand_start] + expand_papers
         if depth > 0:
             expand_papers = expand_papers[:self.expand_papers]
         self.expand_start = len(self.papers_queue)
         crawl_prompts, have_full_paper = [], []
         PaperAgent.do_parallel(self.get_paper_content, (expand_papers, crawl_prompts, have_full_paper), self.threads_num)
         crawl_results = self.crawler.batch_infer(crawl_prompts)
         PaperAgent.do_parallel(self.do_expand, (depth, have_full_paper, crawl_results), self.threads_num)
     ```

3. **完整运行流程 (`run`)**:
   - 执行 `search` 方法完成初步搜索。
   - 根据设定的扩展层数 (`expand_layers`)，递归调用 `expand` 方法，逐层扩展引用网络。

---

### **总结报告的生成**
在运行结束后，`PaperAgent` 会通过其论文树结构 (`PaperNode`) 生成一个总结性的知识图谱，所有搜索和扩展的结果都保存在论文树中。最终，论文树可以被序列化为字典或 JSON 格式，作为总结报告输出。

- **示例代码**:
  ```python
  def todic(self):
      return {
          "title":        self.title,
          "arxiv_id":     self.arxiv_id,
          "depth":        self.depth,
          "child":        {k: [i.todic() for i in v] for k, v in self.child.items()},
          "abstract":     self.abstract,
          "sections":     self.sections,
          "source":       self.source,
          "select_score": self.select_score,
          "extra":        self.extra,
      }
  ```

- 在 `run_paper_agent.py` 中，结果会被保存到指定的输出文件夹：
  ```python
  if args.output_folder != "":
      json.dump(paper_agent.root.todic(), open(os.path.join(args.output_folder, f"{idx}.json"), "w"), indent=2)
  ```

输出的总结报告包含：
- 论文标题
- arXiv ID
- 摘要
- 引用的论文列表
- 每篇论文的相关性得分等

---

### 总结
- **多次搜索和扩展** 是通过 `search` 和 `expand` 方法实现的，递归完成论文引用的网络扩展。
- **总结报告** 会以 JSON 格式保存，包含完整的论文树结构，方便后续分析和展示。