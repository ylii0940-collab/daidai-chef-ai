# AI 智能私厨推荐系统 (AI Personal Chef Recommendation System)

这是一个基于 **FastAPI + Streamlit + ChromaDB + LangGraph** 构建的个性化菜谱检索与推荐系统。系统实现了冰箱食材的多模态识别、本地菜谱的向量检索（RAG）、基于用户画像特征的多维度重排（Reranker），以及基于 SQLite 持久化会话的多轮对话能力。

---

## 🏗️ 系统架构与技术栈

本系统采用前后端解耦的架构设计：

*   **前端展示层 (Client)**: 基于 **Streamlit** 构建。作为轻量级交互客户端，负责图片上传、偏好配置、历史会话切换及渲染格式化后的菜谱推荐卡片。
*   **后端服务层 (Server)**: 基于 **FastAPI** 搭建 REST APIs，统一管理多轮对话状态及各类算法计算。
*   **向量检索层 (RAG)**: 使用 **ChromaDB** 作为本地持久化向量数据库（存储于 `resources/chroma_db`），使用阿里云的 `text-embedding-v2` 对菜谱进行嵌入和余弦相似度检索。
*   **智能体引擎 (Agent Engine)**: 使用 **LangGraph** 构建多智能体状态机（Planner/Executor/Direct Chat），通过自定义节点实现意图识别与工作流流转。
*   **数据持久化 (Persistence)**: 基于 **SQLite** 实现状态机 Checkpoint 存储，提供跨会话的多轮记忆持久化。
*   **大语言模型 (LLMs)**: 使用阿里云百炼平台的 `qwen-vl-plus` 多模态模型进行视觉食材分析，并使用其兼容 OpenAI 规范的 API 完成核心 Agent 工作流。

---

## 🛠️ 核心功能实现细节

### 1. 多模态食材视觉识别
用户上传冰箱食材照片后，FastAPI 后端通过多模态大模型对图像进行结构化解析。系统通过强约束 Prompt 设计，规范大模型输出以下格式的 JSON 数据：
```json
{
  "ingredients": [
    {"name": "鸡胸肉", "category": "肉类", "freshness": "新鲜", "confidence": 0.98}
  ]
}
```

### 2. 本地向量数据库检索 (RAG)
系统放弃了简单的关键词匹配，将 100+ 道本地精选菜谱的文本特征编码为 1536 维的密集向量导入 ChromaDB。检索阶段将用户输入的食材列表和个性化诉求作为 Query 向量化，在向量空间中召回 Top-10 语义最接近的候选菜谱。

### 3. 多维度重排算法 (Reranker)
系统使用纯 Python 编写的轻量重排算法，结合用户偏好规则对 RAG 召回的候选集进行微观排序，**总分计算公式**如下：
$$\text{总分} = \text{食材匹配度} \times 0.4 + \text{营养均衡度} \times 0.3 + \text{制作难度} \times 0.2 + \text{用时成本} \times 0.1$$

*   **食材匹配度 (40%)**: 统计菜谱必需食材在用户当前可用食材中的占比。
*   **营养均衡度 (30%)**: 根据菜谱营养标签（低卡、低脂、高蛋白等）进行加减分。当用户偏好为“减脂”或“增肌”时，算法会动态调整特定营养成分的权重加成。
*   **硬性过滤规则 (Hard Filtering)**: 
    *   **避开食材/忌口**: 自动过滤包含用户忌口食材（如：过敏原、不吃辣、忌油炸）的菜谱。
    *   **烹饪器具约束**: 若菜谱所需器具不在用户可用清单内，直接予以剔除。
    *   **时间上限约束**: 剔除烹饪耗时超出用户时间限制的菜谱。

### 4. 多智能体状态机流转 (LangGraph)
系统内部运行的工作流如下：
1.  **Planner Node (规划节点)**: 接收用户输入，分析当前意图是“要求推荐/提供新食材”（流转至 `Executor`）还是“针对已有菜谱追问/普通闲聊”（流转至 `Direct Chat`）。
2.  **Executor Node (执行推荐节点)**: 调度 ChromaDB 进行向量召回，随后运行 Reranker 计算综合评分，最后由大模型对 Top-3 菜谱进行烹饪步骤与营养成分的细节微调并输出 JSON。
3.  **Direct Chat Node (闲聊/答疑节点)**: 不调用数据库，利用系统预置提示词和会话上下文，使用温馨的语气直接回答用户的日常烹饪问题。

---

## 📂 项目结构

```text
daidai/
├── agents/
│   └── personal_chief.py        # 智能体核心逻辑 (LangGraph 状态机定义)
├── data/
│   └── recipes.json             # 基础菜谱源数据 (100 道)
├── prompts/
│   └── system_prompt.txt        # 核心智能体系统级提示词
├── resources/
│   └── personal_chief.db        # SQLite 会话记忆持久化数据库 (自动生成)
├── scripts/
│   └── build_recipe_index.py    # ChromaDB 向量索引构建脚本
├── streamlit_app.py             # Streamlit 交互式客户端前端
├── app_server.py                # FastAPI 后端 API 服务端
├── Dockerfile                   # 镜像构建配置文件
├── docker-compose.yml           # 双容器编排配置文件
├── requirements.txt             # 项目第三方依赖清单
├── .gitignore                   # Git 忽略配置文件 (包含密钥/缓存屏蔽)
└── README.md                    # 项目说明文档
```

---

## 🚀 快速启动指南

### 1. 本地直接运行

#### ① 配置环境变量
在项目根目录下创建 `.env` 文件，配置您的 API 凭证：
```env
DASHSCOPE_API_KEY="您的阿里云百炼 API Key"
TAVILY_API_KEY="您的 Tavily Search API Key"
DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

#### ② 安装依赖
推荐在虚拟环境中安装依赖（Python 3.9+）：
```bash
pip install -r requirements.txt
```

#### ③ 构建本地向量索引
运行以下脚本，对 `data/recipes.json` 中的菜谱文本进行向量化并导入 Chroma 本地数据库：
```bash
python scripts/build_recipe_index.py
```

#### ④ 启动 FastAPI 后端服务
运行以下命令，后端服务默认运行在 `8000` 端口：
```bash
python app_server.py
```

#### ⑤ 启动 Streamlit 前端
在另一个终端窗口中启动前端，服务默认运行在 `8501` 端口：
```bash
streamlit run streamlit_app.py
```
浏览器会自动打开 `http://localhost:8501`。

### 2. 使用 Docker Compose 一键容器化部署
确保本地已安装 Docker 引擎，在项目根目录下直接运行：
```bash
docker-compose up -d --build
```
启动后：
*   前端交互地址：`http://localhost:8501`
*   后端 API 文档 (Swagger UI)：`http://localhost:8000/docs`

---

## 🔌 API 接口说明

FastAPI 服务端提供了以下核心 REST APIs：

*   `POST /recommend`: 接收可用食材和偏好配置，执行 RAG + 评分重排，返回定制化推荐菜谱 JSON。
*   `POST /chat`: 多轮会话路由接口，返回 Planner 分流后的 AI 回复内容。
*   `GET /history`: 根据 `thread_id` 获取该会话下的所有历史对话消息列表。
*   `GET /threads`: 获取系统中所有已记录的会话 `thread_id` 列表。
*   `POST /clear`: 擦除指定 `thread_id` 的 SQLite 数据库会话记录。
*   `POST /parse_image`: 多模态图片上传解析食材接口。
*   `POST /score_recipe`: 计算单条菜谱匹配度指标评分接口。

---

## ⚠️ 项目限制与后续优化计划 (Roadmap)

*   **对第三方 API 依赖性强**: 核心交互完全依赖于阿里云百炼在线服务，暂未引入本地大模型（如 Ollama / Llama3）作为备用或离线方案。
*   **安全与并发控制不足**: 作为一个学习与演示项目，系统目前暂未设计用户登录注册、RBAC 权限控制，以及高并发请求下的限流（Rate Limiting）和缓存优化。
*   **测试评估指标缺失**: 推荐系统及 RAG 效果暂未做系统性的评测（如使用 Ragas / TruLens 等工具对检索召回率、相关性进行定量评估）。
*   **后续计划**: 计划扩充基础菜谱数据库容量，加入基于用户历史点赞打分的协同过滤算法，并完善用户登录与会话隔离机制。
