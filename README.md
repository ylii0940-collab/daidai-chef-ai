# 🍳 李黛黛的智能私厨管家 (Li Daidai's AI Personal Chef Manager)

这是一个基于 **LangGraph + Qwen-VL-Plus 多模态模型 + Streamlit** 构建的智能私人厨师推荐系统。它突破了传统“单轮 Prompt 调 API”的 Demo 级别应用，通过工程化的方式实现了**图像多模态识别**、**实时网络菜谱检索**、**自定义多维度算法打分**以及**基于 SQLite 的多轮对话偏好记忆**。

---

## 🌟 核心亮点与升级点

1. **多模态食材识别（结构化输出）**
   - 拍照或上传食材图片，通过 `qwen-vl-plus` 视觉大模型进行智能分析。
   - 强约束的 Prompt 设计保证输出标准的 JSON 格式（包括食材名称、品类、新鲜度与识别置信度）。
2. **基于真实搜索的菜谱检索**
   - 使用 Tavily 搜索引擎对真实中文菜谱进行检索，杜绝大模型凭空胡编（Hallucination）烹饪步骤和配方。
3. **独立的纯 Python 多维度打分算法（亮点推荐）**
   - **不依赖大模型昂贵的 Token 和不确定性推理**，用纯算法对召回的菜谱进行评分：
     $$\text{总分} = \text{食材匹配度} \times 0.4 + \text{营养均衡度} \times 0.3 + \text{制作难度} \times 0.2 + \text{用时成本} \times 0.1$$
   - 算法结合用户的饮食目标（如：减脂、增肌）和时间限制，提供高可信度、可解释的打分细项。
4. **多轮对话偏好记忆**
   - 基于 LangGraph 内置的状态管理器和 **SQLite Saver**，自动保存会话的历史记录（Thread ID 隔离）。
   - 用户可随时追加忌口、更换烹饪工具、缩短时间，在后续多轮对话中，AI 将始终保持对用户偏好的记忆与遵从。
5. **极简优雅的 Streamlit Dashboard**
   - 定制化暗色系（Slate/Emerald）高级 UI。
   - 互动式的食材增删核对与带彩色填充进度条的评分看板。

---

## 📂 项目结构

```text
daidai/
├── agents/
│   └── personal_chief.py        # Agent 核心逻辑 (StateGraph)
├── prompts/
│   └── system_prompt.txt        # 核心 AI 角色与流程 Prompt
├── resources/
│   └── personal_chief.db        # SQLite 记忆持久化数据库 (自动生成)
├── streamlit_app.py             # Streamlit 前端交互页面
├── langgraph.json               # LangGraph 部署配置文件
├── .env                         # 密钥配置文件 (需自备)
└── README.md                    # 项目说明文档
```

---

## 🚀 快速启动指南

### 1. 配置环境变量

在项目根目录下创建 `.env` 文件，并填入您的 API Keys：

```env
DASHSCOPE_API_KEY="您的阿里云百炼 API Key"
TAVILY_API_KEY="您的 Tavily Search API Key"
DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

### 2. 安装依赖包

确保您的 Python 环境在 3.9+ 以上，然后安装以下包：

```bash
pip install streamlit langchain langchain-community langchain-openai langchain-tavily langgraph pyarrow pillow
```

### 3. 运行前端应用

在项目根目录下直接运行 Streamlit：

```bash
streamlit run streamlit_app.py
```

浏览器会自动打开 `http://localhost:8501`。

### 4. （可选）使用 LangGraph CLI 本地开发调试

如果您安装了 `langgraph-cli`，也可以在本地启动调试服务器以可视化状态流：

```bash
langgraph dev
```

---

## 🛠️ 打分机制设计细节

- **食材匹配度（权重 40%）**：计算菜谱所需食材在用户提供食材中的占比。
- **营养均衡度（权重 30%）**：基础分 50 分。对于低卡、低脂、高蛋白等有正向加分；对于油炸、高盐高糖有扣分；当用户选择“减脂”目标时，低卡与高蛋白的加权值进一步放大。
- **制作难度（权重 20%）**：简单级 100 分，中等级 60 分，复杂级 30 分。
- **时间成本（权重 10%）**：用时越短评分越高（$\le 15$分钟为 100 分，超过 60 分钟降为 20 分）。
