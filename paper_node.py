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
class PaperNode:
    """
    PaperNode类表示论文树中的一个节点
    
    主要功能:
    1. 存储论文的基本信息（标题、摘要、arXiv ID等）
    2. 管理论文的引用关系（子节点）
    3. 提供将节点转换为字典的方法，用于序列化
    4. 提供排序方法，用于按相关性评分排序
    """
    def __init__(self, attrs):
        """
        初始化PaperNode
        
        参数:
            attrs: 包含论文属性的字典
        """
        self.title        = attrs.get("title", "")         # 论文标题
        self.arxiv_id     = attrs.get("arxiv_id", "")     # arXiv ID
        self.depth        = attrs.get("depth", -1)         # 在树中的深度
        # 子节点，按章节名称组织，每个章节包含多个引用论文节点
        self.child        = {k: [PaperNode(i) for i in v] for k, v in attrs.get("child", {}).items()}
        self.abstract     = attrs.get("abstract", "")      # 论文摘要
        self.sections     = attrs.get("sections", "")      # 章节信息，格式为 section name -> list of citation papers
        self.source       = attrs.get("source", "Root")    # 来源，可以是 Root（根节点）、Search（搜索得到）或 Expand（扩展得到）
        self.select_score = attrs.get("select_score", 0.0) # 选择器模型给出的相关性评分
        self.extra        = attrs.get("extra", {})         # 额外信息，如扩展状态等

    def todic(self):
        """
        将节点转换为字典，用于序列化
        
        返回:
            包含节点所有属性的字典
        """
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

    @staticmethod
    def sort_paper(item):
        """
        用于排序的静态方法，按相关性评分排序
        
        参数:
            item: 要排序的PaperNode对象
            
        返回:
            相关性评分，用于排序
        """
        return item.select_score