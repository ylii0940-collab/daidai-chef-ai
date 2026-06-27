# AI 智能私厨推荐系统

AI Personal Chef Recommendation System

这是一个基于 **FastAPI + Streamlit + ChromaDB + LangGraph** 构建的个性化菜谱检索与推荐系统。项目围绕“冰箱已有食材如何快速生成可执行菜谱”这一场景，实现了图片食材识别、本地菜谱语义检索、规则化推荐重排、多轮对话记忆和 Docker 化部署。

本项目主要用于学习和展示 AI 应用的完整工程流程，包括前后端解耦、RAG 检索、LLM 接入、状态机工作流、数据持久化和容器化部署。

---

## 项目功能

* 支持上传冰箱或食材图片，并通过多模态模型识别食材信息。
* 支持根据用户已有食材、饮食目标、忌口、烹饪时间和可用厨具推荐菜谱。
* 使用 ChromaDB 构建本地菜谱向量库，实现基于语义相似度的候选菜谱召回。
* 使用规则化 Reranker 对候选菜谱进行二次排序，提高推荐结果的可解释性。
* 使用 LangGraph 构建状态机式工作流，实现意图识别、推荐执行和普通问答分流。
* 使用 SQLite 保存会话状态，支持多轮对话历史记录。
* 提供 FastAPI 后端接口和 Streamlit 前端页面。
* 支持 Docker Compose 一键启动前后端服务。

---

## 技术栈

| 模块    | 技术                            |
| ----- | ----------------------------- |
| 前端    | Streamlit                     |
| 后端    | FastAPI                       |
| 工作流编排 | LangGraph                     |
| 向量数据库 | ChromaDB                      |
| 会话持久化 | SQLite                        |
| 大模型接口 | 阿里云百炼 / OpenAI-compatible API |
| 多模态识别 | qwen-vl-plus                  |
| 向量嵌入  | text-embedding-v2             |
| 部署    | Docker / Docker Compose       |

---

## 系统架构

本系统采用前后端解耦设计。

### 前端展示层

前端基于 **Streamlit** 构建，主要负责：

* 食材图片上传
* 用户偏好配置
* 多轮对话输入
* 历史会话切换
* 推荐菜谱卡片展示

### 后端服务层

后端基于 **FastAPI** 构建，主要负责：

* 接收前端请求
* 管理多轮对话状态
* 调用图片识别模型
* 执行菜谱检索与排序
* 返回结构化推荐结果

### 向量检索层

系统使用 **ChromaDB** 作为本地向量数据库。
菜谱文本会被编码为高维向量并写入本地 ChromaDB，用户输入的食材和需求也会被向量化，然后在向量空间中召回语义最接近的候选菜谱。

### 工作流引擎

系统使用 **LangGraph** 构建状态机式工作流，主要包含：

* **Planner Node**：判断用户意图，例如推荐菜谱、追问已有菜谱或普通闲聊。
* **Executor Node**：执行菜谱召回、重排和结果生成。
* **Direct Chat Node**：处理不需要调用菜谱数据库的普通烹饪问答。

### 数据持久化

系统使用 **SQLite** 保存会话状态和历史记录。
相关数据库文件会在本地运行后自动生成，不提交到 GitHub。

---

## 核心实现

### 1. 多模态食材识别

用户上传食材图片后，后端调用多模态大模型对图片进行解析，并尽量输出结构化 JSON 数据。

示例输出：

```json
{
  "ingredients": [
    {
      "name": "鸡胸肉",
      "category": "肉类",
      "freshness": "新鲜",
      "confidence": 0.98
    }
  ]
}
```

该模块的目标是将图片信息转化为后续推荐模块可以使用的结构化食材列表。

---

### 2. 本地菜谱向量检索

系统将 `data/recipes.json` 中的菜谱数据转化为文本表示，并通过嵌入模型生成向量，写入 ChromaDB。

检索流程如下：

```text
用户输入 / 食材列表
        ↓
生成 Query 向量
        ↓
ChromaDB 语义检索
        ↓
召回 Top-K 候选菜谱
        ↓
进入 Reranker 重排
```

相比简单关键词匹配，向量检索可以更好地处理用户的自然语言表达，例如“适合带饭”“减脂”“快手菜”“高蛋白”等需求。

---

### 3. 多维度重排算法

系统在向量召回后，会使用规则化 Reranker 对候选菜谱进行二次排序。

当前版本主要考虑以下因素：

* 食材匹配度
* 营养均衡度
* 制作难度
* 用时成本
* 用户忌口
* 可用厨具
* 烹饪时间上限

评分公式：

```text
总分 = 食材匹配度 × 0.4 + 营养均衡度 × 0.3 + 制作难度 × 0.2 + 用时成本 × 0.1
```

其中：

* **食材匹配度**：统计菜谱所需食材与用户当前已有食材的重合程度。
* **营养均衡度**：根据低卡、高蛋白、低脂等标签进行加权。
* **制作难度**：优先推荐步骤更简单、失败率更低的菜谱。
* **用时成本**：根据用户设置的时间上限进行筛选和排序。

系统还包含硬性过滤规则，例如：

* 过滤用户明确忌口的食材。
* 过滤需要用户没有的厨具的菜谱。
* 过滤烹饪时间超过用户限制的菜谱。

---

### 4. 状态机式工作流

系统使用 LangGraph 对不同类型的用户输入进行分流。

工作流示意：

```text
用户输入
   ↓
Planner Node
   ↓
判断用户意图
   ├── 推荐请求 → Executor Node → RAG 检索 → Reranker 排序 → 生成推荐结果
   └── 普通问答 → Direct Chat Node → 直接生成回答
```

这种设计可以避免所有请求都走同一条 Prompt 调用路径，使推荐逻辑、闲聊逻辑和后续扩展模块更容易维护。

---

## 项目结构

```text
daidai/
├── agents/
│   └── personal_chief.py        # LangGraph 工作流与推荐逻辑
├── data/
│   └── recipes.json             # 基础菜谱数据
├── prompts/
│   └── system_prompt.txt        # 系统提示词
├── resources/
│   ├── kitty_chef.png           # 前端展示资源
│   ├── mockup_screenshot.png    # 项目展示图片
│   └── personal_chief.db        # SQLite 会话数据库，运行后自动生成，不提交
├── scripts/
│   └── build_recipe_index.py    # ChromaDB 向量索引构建脚本
├── streamlit_app.py             # Streamlit 前端入口
├── app_server.py                # FastAPI 后端入口
├── Dockerfile                   # Docker 镜像构建文件
├── docker-compose.yml           # 前后端容器编排文件
├── requirements.txt             # Python 依赖
├── .gitignore                   # Git 忽略规则
└── README.md                    # 项目说明文档
```

说明：

* `.env` 文件用于保存 API Key，不提交到 GitHub。
* `resources/chroma_db/` 为本地向量数据库目录，运行索引构建脚本后生成，不提交到 GitHub。
* SQLite 会话数据库文件为运行时生成文件，不提交到 GitHub。

---

## 本地运行

### 1. 克隆项目

```bash
git clone https://github.com/ylii0940-collab/daidai-chef-ai.git
cd daidai-chef-ai
```

### 2. 创建环境变量文件

在项目根目录创建 `.env` 文件：

```env
DASHSCOPE_API_KEY="your_dashscope_api_key"
DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

请不要将 `.env` 文件提交到 GitHub。

### 3. 安装依赖

建议使用 Python 3.9 或以上版本。

```bash
pip install -r requirements.txt
```

### 4. 构建本地向量索引

首次运行前，需要根据本地菜谱数据构建 ChromaDB 向量索引：

```bash
python scripts/build_recipe_index.py
```

该命令会读取 `data/recipes.json`，并在本地生成 `resources/chroma_db/`。

### 5. 启动后端服务

```bash
python app_server.py
```

后端默认运行在：

```text
http://localhost:8000
```

API 文档地址：

```text
http://localhost:8000/docs
```

### 6. 启动前端页面

打开另一个终端窗口，执行：

```bash
streamlit run streamlit_app.py
```

前端默认运行在：

```text
http://localhost:8501
```

---

## Docker Compose 运行

项目提供 Docker Compose 配置，可以一键启动前后端服务。

```bash
docker-compose up -d --build
```

启动后访问：

```text
前端页面：http://localhost:8501
后端文档：http://localhost:8000/docs
```

停止服务：

```bash
docker-compose down
```

查看日志：

```bash
docker-compose logs -f
```

---

## API 接口

FastAPI 后端提供以下主要接口：

| 方法   | 路径              | 说明                           |
| ---- | --------------- | ---------------------------- |
| POST | `/chat`         | 多轮对话入口，根据 Planner 分流到推荐或普通问答 |
| POST | `/recommend`    | 根据食材和偏好执行菜谱推荐                |
| POST | `/parse_image`  | 上传图片并解析食材信息                  |
| POST | `/score_recipe` | 计算单条菜谱的匹配度评分                 |
| GET  | `/history`      | 根据 `thread_id` 获取历史对话        |
| GET  | `/threads`      | 获取已记录的会话列表                   |
| POST | `/clear`        | 清除指定会话历史                     |

---

## 当前限制

本项目仍是一个学习和展示性质的 AI 应用，当前版本存在以下限制：

1. **依赖第三方模型 API**
   图片识别、意图识别和部分回答生成依赖阿里云百炼服务，暂未接入本地模型作为备用方案。

2. **用户系统尚未完善**
   当前版本未实现用户注册、登录、权限管理和用户级别的数据隔离。

3. **推荐效果缺少系统评测**
   目前主要通过人工测试验证推荐合理性，暂未引入 RAGAS、TruLens 等工具进行检索质量和生成质量评估。

4. **并发和安全控制有限**
   当前版本暂未实现限流、鉴权、请求日志审计和生产级异常监控。

5. **菜谱数据规模有限**
   当前菜谱数据主要用于功能验证，后续可扩展为更大规模的数据集。

---

## 后续优化方向

* 扩充菜谱数据规模，增加更多菜系、口味和营养标签。
* 增加用户登录与用户画像模块，实现更稳定的个性化推荐。
* 引入用户点赞、收藏、评分等反馈数据，优化推荐排序逻辑。
* 使用 RAGAS / TruLens 对检索和生成结果进行评估。
* 增加限流、鉴权、异常日志和监控能力。
* 支持云端部署和 HTTPS 访问。
* 尝试接入本地大模型，提高系统可控性和离线可用性。

---

## 项目定位

本项目不是完整的商业级推荐系统，而是一个面向学习和作品展示的 AI 应用工程实践。
重点在于展示从用户输入、图像识别、向量检索、结果重排、多轮对话到前后端部署的完整流程。
