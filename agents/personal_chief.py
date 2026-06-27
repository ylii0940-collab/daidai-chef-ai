"""
私人厨师 Agent 核心模块 (V2 多 Agent + ChromaDB 升级版)
─────────────────────────────────────────
功能：
  1. 多模态食材识别（结构化 JSON 输出）
  2. 基于 Chroma 本地向量数据库的 RAG 检索
  3. 混合重排系统（Reranker）- 结合语义匹配度与用户画像规则
  4. 多 Agent 路由决策流 (Planner + Executor + Direct Chat)
  5. 多轮对话状态与记忆持久化
─────────────────────────────────────────
"""

import os
import socket

# 仅在 Antigravity 沙箱环境下启用特殊的 DNS 劫持和代理屏蔽
if "ANTIGRAVITY_AGENT" in os.environ:
    import urllib.request
    import json
    
    _dashscope_real_ip = "39.96.198.249"  # 默认备份 IP
    try:
        _dns_url = "http://223.5.5.5/resolve?name=dashscope.aliyuncs.com"
        _req = urllib.request.Request(_dns_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(_req, timeout=2.0) as _dns_res:
            _dns_data = json.loads(_dns_res.read().decode('utf-8'))
            _ips = [ans["data"] for ans in _dns_data.get("Answer", []) if ans.get("type") == 1]
            if _ips:
                _dashscope_real_ip = _ips[0]
    except Exception as e:
        pass

    _orig_getaddrinfo = socket.getaddrinfo
    def _custom_getaddrinfo(host, port, *args, **kwargs):
        if host == "dashscope.aliyuncs.com":
            return _orig_getaddrinfo(_dashscope_real_ip, port, *args, **kwargs)
        return _orig_getaddrinfo(host, port, *args, **kwargs)
    socket.getaddrinfo = _custom_getaddrinfo

    urllib.request.getproxies = lambda: {}

import os
import re
import json
import base64
import numpy as np
from typing import TypedDict, Annotated, Optional, List

import httpx
import chromadb
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

load_dotenv()

# ══════════════════════════════════════════════════════════════════
# 1. 环境变量校验与模型初始化
# ══════════════════════════════════════════════════════════════════
_API_KEY = os.getenv("DASHSCOPE_API_KEY")
_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

if not _API_KEY:
    raise ValueError("❌ 请配置 DASHSCOPE_API_KEY 环境变量")

# 适配沙箱与本地环境的客户端设置
if "ANTIGRAVITY_AGENT" in os.environ:
    # 沙箱环境下：跳过 SSL 校验和系统代理，避免安全机制冲突
    _chat_client = httpx.Client(verify=False, trust_env=False)
    _embeddings_client = httpx.Client(verify=False, trust_env=False)
else:
    # 用户本地机器：强行禁用系统代理读取 (trust_env=False)，从而绕过任何本地 VPN 代理拦截，实现直接连接国内阿里云百炼。
    _chat_client = httpx.Client(verify=True, trust_env=False)
    _embeddings_client = httpx.Client(verify=True, trust_env=False)

# 主 LLM (Qwen-VL-Plus 多模态模型)
model = ChatOpenAI(
    model="qwen-vl-plus",
    openai_api_key=_API_KEY,
    openai_api_base=_BASE_URL,
    http_client=_chat_client,
    timeout=60.0,  # 增大超时时间，防止生成长篇菜谱时超时
    max_retries=2,
)

# Embeddings model for ChromaDB query
# 必须设置 check_embedding_ctx_length=False。因为 LangChain 默认会先在本地将文本通过 tiktoken 转化为整数 Token 列表，
# 但阿里云百炼模型的 compatible /embeddings 接口仅支持字符串原文或字符串列表，接收整数列表会报 HTTP 400 错误。
embeddings_model = OpenAIEmbeddings(
    model="text-embedding-v2",
    openai_api_key=_API_KEY,
    openai_api_base=_BASE_URL,
    http_client=_embeddings_client,
    check_embedding_ctx_length=False,
)

# ══════════════════════════════════════════════════════════════════
# 2. 食材视觉理解 (Qwen-VL-Plus)
# ══════════════════════════════════════════════════════════════════
INGREDIENT_PARSE_PROMPT = """你是一位专业食材分析师。请仔细观察图片，识别所有可见食材。

严格按以下 JSON 格式输出，不要添加任何其他内容或 markdown 标记：
{
  "ingredients": [
    {
      "name": "食材名称（中文）",
      "category": "分类（蔬菜/肉类/蛋类/海鲜/主食/调料/水果/其他）",
      "freshness": "新鲜程度（新鲜/较新鲜/一般/不新鲜）",
      "confidence": 0.95
    }
  ]
}"""

def parse_image_ingredients(image_bytes: bytes) -> dict:
    """
    通过 qwen-vl-plus 模型识别图片中的食材，并输出结构化 JSON
    """
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    
    message = HumanMessage(
        content=[
            {"type": "text", "text": INGREDIENT_PARSE_PROMPT},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
            },
        ]
    )
    
    response = model.invoke([message])
    content = response.content.strip()
    
    # 移除 markdown 代码块标记
    if content.startswith("```"):
        lines = content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
        
    try:
        return json.loads(content)
    except Exception as e:
        print(f"解析食材 JSON 失败: {e}. 原始输出: {content}")
        return {"ingredients": []}

# ══════════════════════════════════════════════════════════════════
# 3. ChromaDB 向量数据库 RAG 检索
# ══════════════════════════════════════════════════════════════════
_chroma_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "chroma_db"))
_chroma_client = None
_offline_mode = None

def _get_chroma_collection():
    """获取或初始化 ChromaDB 集合"""
    global _chroma_client
    if _chroma_client is None:
        print(f"Connecting to ChromaDB at {_chroma_path}...")
        _chroma_client = chromadb.PersistentClient(path=_chroma_path)
    return _chroma_client.get_collection("recipes_collection")

def retrieve_recipes(query_str: str, top_k: int = 10) -> List[dict]:
    """
    RAG 检索：使用 ChromaDB 向量数据库进行余弦/L2 相似度召回。
    """
    global _offline_mode
    try:
        collection = _get_chroma_collection()
    except Exception as e:
        print(f"❌ 获取 ChromaDB 集合失败: {e}。请确保已运行 scripts/build_recipe_index.py 重新生成。")
        return []

    # 首次查询时检测网络连接状况并缓存
    if _offline_mode is None:
        try:
            headers = {
                "Authorization": f"Bearer {_API_KEY}",
                "Content-Type": "application/json"
            }
            data = {
                "model": "text-embedding-v2",
                "input": ["test"]
            }
            is_sandbox = "ANTIGRAVITY_AGENT" in os.environ
            check_verify = not is_sandbox
            check_trust_env = not is_sandbox
            with httpx.Client(verify=check_verify, trust_env=check_trust_env, timeout=5.0) as check_client:
                res = check_client.post(
                    "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                    headers=headers,
                    json=data
                )
                if res.status_code == 200:
                    _offline_mode = False
                else:
                    raise Exception(f"HTTP status {res.status_code}")
        except Exception as e:
            print(f"  [Offline Detector] DashScope connection failed ({e}). Using OFFLINE mode with zero vectors.")
            _offline_mode = True

    # 获取 Query 的 dense embedding 向量
    embedding = None
    if not _offline_mode:
        for retry in range(3):
            try:
                embedding = embeddings_model.embed_query(query_str)
                break
            except Exception as ex:
                print(f"  Warning: Embedding query failed for '{query_str}' (retry {retry+1}/3): {ex}")
                import time
                time.sleep(1)

    if embedding is None:
        embedding = [0.0] * 1536

    try:
        results = collection.query(
            query_embeddings=[embedding],
            n_results=top_k
        )
    except Exception as e:
        print(f"❌ ChromaDB 查询出错: {e}")
        return []

    candidates = []
    if not results or "metadatas" not in results or not results["metadatas"]:
        return candidates

    metadatas = results["metadatas"][0]
    distances = results["distances"][0] if "distances" in results else [1.0] * len(metadatas)

    for i, meta in enumerate(metadatas):
        # 距离映射为相似度评分 (Chroma L2 default: distance 越小越相似)
        dist = distances[i]
        semantic_score = 1.0 / (1.0 + dist)
        
        # 反序列化 Chroma 存储的 Stringified 列表字段
        try:
            req_ing = json.loads(meta.get("required_ingredients", "[]"))
        except Exception:
            req_ing = []
            
        try:
            nut_tags = json.loads(meta.get("nutrition_tags", "[]"))
        except Exception:
            nut_tags = []
            
        try:
            steps = json.loads(meta.get("steps", "[]"))
        except Exception:
            steps = []
            
        try:
            equip = json.loads(meta.get("equipment", "[]"))
        except Exception:
            equip = []

        recipe = {
            "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "required_ingredients": req_ing,
            "nutrition_tags": nut_tags,
            "difficulty": meta.get("difficulty", "中等"),
            "cook_time_minutes": int(meta.get("cook_time_minutes", 30)),
            "calories": int(meta.get("calories", 300)),
            "steps": steps,
            "equipment": equip,
            "semantic_score": float(semantic_score)
        }
        candidates.append(recipe)

    return candidates

# ══════════════════════════════════════════════════════════════════
# 4. 多维度评分算法与 Reranker
# ══════════════════════════════════════════════════════════════════
def score_recipe(
    recipe: dict,
    available_ingredients: List[str],
    user_goals: List[str],
) -> dict:
    """
    单条菜谱的多维度自定义评分算法 (食材匹配度40% + 营养均衡度30% + 制作难度20% + 时间成本10%)
    """
    # ── 1. 食材匹配度（40%）────────────────
    required = recipe.get("required_ingredients", [])
    if required:
        matched = sum(
            1 for r in required
            if any(a in r or r in a for a in available_ingredients)
        )
        match_score = matched / len(required)
    else:
        match_score = 0.5

    # ── 2. 营养均衡度（30%）────────────────
    tags = recipe.get("nutrition_tags", [])
    nutrition_score = 0.5

    bonus = {
        "低卡": 0.15, "低脂": 0.12, "高蛋白": 0.15,
        "富含维生素": 0.10, "富含膳食纤维": 0.08, "低盐": 0.08, "低糖": 0.08,
    }
    penalty = {"油炸": -0.25, "高脂": -0.20, "高糖": -0.15}

    # 用户目标加成
    if "减脂" in user_goals:
        bonus["低卡"] = 0.25
        bonus["高蛋白"] = 0.22
        penalty["油炸"] = -0.35
        penalty["高脂"] = -0.30
    elif "增肌" in user_goals:
        bonus["高蛋白"] = 0.30

    for tag in tags:
        nutrition_score += bonus.get(tag, 0) + penalty.get(tag, 0)
    nutrition_score = max(0.0, min(1.0, nutrition_score))

    # ── 3. 制作难度（20%，越简单越高分）──────
    difficulty_score = {"简单": 1.0, "中等": 0.6, "复杂": 0.3}.get(
        recipe.get("difficulty", "中等"), 0.6
    )

    # ── 4. 时间成本（10%，越快越高分）────────
    t = recipe.get("cook_time_minutes", 30)
    if t <= 15:
        time_score = 1.0
    elif t <= 30:
        time_score = 0.8
    elif t <= 45:
        time_score = 0.6
    elif t <= 60:
        time_score = 0.4
    else:
        time_score = 0.2

    total = (
        match_score       * 0.4
        + nutrition_score * 0.3
        + difficulty_score * 0.2
        + time_score      * 0.1
    )

    return {
        "total":       round(total, 2),
        "match":       round(match_score, 2),
        "nutrition":   round(nutrition_score, 2),
        "difficulty":  round(difficulty_score, 2),
        "time":        round(time_score, 2),
    }

def rerank_candidates(
    candidates: List[dict],
    profile: dict,
    available_ingredients: List[str]
) -> List[dict]:
    """
    Reranker 混合重排：
    1. 应用硬性过滤规则（忌口、时间限制、厨具不匹配直接剔除）。
    2. 计算综合得分 = 0.4 * 语义检索相似度 + 0.6 * 用户画像自定义匹配分。
    3. 按照综合得分从高到低排序，返回前 3 道最优菜谱。
    """
    goal = profile.get("goal", [])
    avoid = profile.get("avoid", [])
    equipment = profile.get("equipment", [])
    cook_time_limit = profile.get("cook_time_limit", 120)

    reranked = []
    for recipe in candidates:
        recipe_name = recipe.get("name", "")
        required = recipe.get("required_ingredients", [])
        recipe_equipment = recipe.get("equipment", [])
        cook_time = recipe.get("cook_time_minutes", 30)

        # ── 1. 避开食材过滤 (硬过滤) ──
        should_avoid = False
        for a in avoid:
            a_clean = a.replace("不吃", "").replace("忌", "").strip()
            if not a_clean:
                continue
            # 检查原料列表
            if any(a_clean in req for req in required):
                should_avoid = True
                break
            # 检查菜名
            if a_clean in recipe_name:
                should_avoid = True
                break
            # 特殊处理 "不吃辣" -> 剔除辣椒、花椒、豆瓣酱等辣性调料
            if a_clean in ["辣", "辣口", "麻辣", "辣椒"]:
                spicy_ings = ["辣椒", "花椒", "泡椒", "豆瓣酱", "干辣椒", "辣"]
                if any(any(s in req for s in spicy_ings) for req in required) or "辣" in recipe_name:
                    should_avoid = True
                    break
            # 特殊处理 "忌油炸" -> 过滤标签里有 "油炸"
            if a_clean in ["油炸", "炸"]:
                if "油炸" in recipe.get("nutrition_tags", []):
                    should_avoid = True
                    break

        if should_avoid:
            continue

        # ── 2. 烹饪时间限制过滤 (硬过滤) ──
        if cook_time > cook_time_limit:
            continue

        # ── 3. 可用厨具限制过滤 (硬过滤) ──
        missing_equip = False
        if equipment:
            for req_eq in recipe_equipment:
                if not any(req_eq in user_eq or user_eq in req_eq for user_eq in equipment):
                    missing_equip = True
                    break
        if missing_equip:
            continue

        # ── 4. 计算自定义用户画像匹配分数 (0.6 权重) ──
        custom_scores = score_recipe(recipe, available_ingredients, goal)
        custom_score = custom_scores["total"]

        # ── 5. 计算混合得分 ──
        semantic_score = recipe.get("semantic_score", 0.5)
        total_score = 0.4 * semantic_score + 0.6 * custom_score

        scored_recipe = dict(recipe)
        scored_recipe["custom_score"] = round(custom_score, 2)
        scored_recipe["total_score"] = round(total_score, 2)
        
        # 计算缺少的材料清单
        missing = []
        for req in required:
            if not any(av in req or req in av for av in available_ingredients):
                missing.append(req)
        scored_recipe["missing_ingredients"] = missing

        reranked.append(scored_recipe)

    # 按照混合得分进行降序排列
    reranked.sort(key=lambda x: x["total_score"], reverse=True)
    return reranked[:3]

# ══════════════════════════════════════════════════════════════════
# 5. Prompts 与 系统设置
# ══════════════════════════════════════════════════════════════════
def _load_system_prompt() -> str:
    """从 prompts/system_prompt.txt 加载 System Prompt"""
    path = os.path.join(os.path.dirname(__file__), "..", "prompts", "system_prompt.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return _FALLBACK_PROMPT

_FALLBACK_PROMPT = """你是一名专业私人厨师 AI 助手。
本系统已通过 RAG 和 Reranker 过滤出 top_3 推荐菜谱。你必须对它们进行细节微调（调整厨具匹配和营养结构）。
如果用户在请求推荐，你必须严格按以下 JSON 格式输出，不要添加任何其他内容：
{
  "recipes": [
    {
      "name": "菜名",
      "description": "个性化定制亮点简介",
      "required_ingredients": ["所需食材"],
      "missing_ingredients": ["需额外购买的食材"],
      "nutrition_tags": ["高蛋白", "低脂"],
      "difficulty": "简单",
      "cook_time_minutes": 20,
      "calories": 280,
      "steps": ["步骤1", "步骤2", "步骤3"]
    }
  ]
}
如果用户是进行追问或聊天，请使用可爱暖心的语气直接用文字解答，不需要输出 JSON。"""

# ══════════════════════════════════════════════════════════════════
# 6. Multi-Agent Setup (Planner / Executor / Direct Chat)
# ══════════════════════════════════════════════════════════════════
class ChefState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    user_profile: Optional[dict]
    ingredients: Optional[List[str]]
    candidate_recipes: Optional[List[dict]]
    next_action: Optional[str]

def _extract_profile_and_ingredients(state: ChefState) -> tuple[dict, List[str], str]:
    """从 State 中提取偏好与食材"""
    profile = state.get("user_profile")
    if not profile:
        profile = {
            "goal": ["减脂", "高蛋白"],
            "avoid": ["不吃辣", "忌油炸"],
            "equipment": ["明火炒锅", "电饭煲", "微波炉"],
            "cook_time_limit": 30
        }

    ingredients = state.get("ingredients") or []
    query_str = ""
    for msg in reversed(state.get("messages", [])):
        if msg.type == "human":
            content = msg.content
            if isinstance(content, str):
                match = re.search(r"食材列表[：:](.*?)[。\n]?", content)
                if match:
                    items = [i.strip() for i in re.split(r"[,，]", match.group(1)) if i.strip()]
                    ingredients.extend(items)
                else:
                    query_str = content
            break

    ingredients = list(set([i.strip() for i in ingredients if i.strip()]))
    if not ingredients:
        ingredients = ["鸡胸肉", "番茄", "鸡蛋"]  # 默认降级

    if not query_str:
        query_str = ", ".join(ingredients)

    return profile, ingredients, query_str

# Planner Node
def _planner_node(state: ChefState) -> dict:
    """Planner Node: 分析最新消息，决定路由到推荐执行器(executor)还是闲聊回复(direct_chat)"""
    messages = state.get("messages", [])
    if not messages:
        return {"next_action": "chat"}

    last_message = messages[-1]
    
    # 检查是否包含图片 (多模态上传识别一般标志着食材推荐意图)
    has_image = False
    if isinstance(last_message, HumanMessage) and isinstance(last_message.content, list):
        for part in last_message.content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                has_image = True
                break
    
    if has_image:
        return {"next_action": "recommend"}

    # 分析文字意图
    prompt = (
        "你是一个智能私人厨师系统的意图规划器（Planner）。\n"
        "分析用户的最新输入，并决定路由方向。\n\n"
        "只从以下两个路由中选择一个：\n"
        "1. \"recommend\"：如果用户正在提供食材、要求推荐菜谱、上传食材图片、要求做饭点子，或者要求重新生成推荐。\n"
        "2. \"chat\"：如果用户在进行多轮闲聊，或者在针对上一次推荐的菜谱进行追问、问题解答（例如：“怎么做第一道菜？”、“第二道菜的卡路里是多少？”、“没有烤箱能用微波炉代替吗？”）。\n\n"
        f"历史消息：{[m.content[:50] for m in messages[-3:-1] if isinstance(m.content, str)] if len(messages) > 1 else '无'}\n"
        f"最新输入：{last_message.content if isinstance(last_message.content, str) else '图片/非纯文本'}\n\n"
        "请只返回单词 \"recommend\" 或 \"chat\"，绝对不要包含任何其他字符或Markdown代码块。"
    )

    try:
        response = model.invoke([HumanMessage(content=prompt)])
        intent = response.content.strip().lower()
        if "recommend" in intent:
            next_action = "recommend"
        else:
            next_action = "chat"
    except Exception as e:
        print(f"Planner LLM 意图识别失败: {e}. 默认路由至 recommend.")
        next_action = "recommend"

    return {"next_action": next_action}

def _router(state: ChefState) -> str:
    """路由决策边"""
    return state.get("next_action", "chat")

# Executor Node
def _executor_node(state: ChefState) -> dict:
    """Executor Node: 执行 RAG 召回 + 重排得分 + 大模型菜谱定制 JSON 输出"""
    profile, ingredients, query_str = _extract_profile_and_ingredients(state)

    # 1. RAG 向量搜索
    try:
        candidates = retrieve_recipes(query_str, top_k=10)
    except Exception as e:
        print(f"Executor RAG 检索出错: {e}")
        candidates = []

    # 2. Reranker 重排打分
    selected = rerank_candidates(candidates, profile, ingredients)
    if not selected and candidates:
        relaxed_profile = {"goal": profile.get("goal", []), "avoid": [], "equipment": [], "cook_time_limit": 120}
        selected = rerank_candidates(candidates, relaxed_profile, ingredients)

    # 3. 定制生成结构化 JSON
    context_text = "【以下是为您严格筛选出的推荐候选菜谱】:\n" + json.dumps(selected, ensure_ascii=False, indent=2)
    user_pref_text = f"\n【用户当前画像限制】：{json.dumps(profile, ensure_ascii=False)}"
    
    system_prompt = _load_system_prompt() + "\n\n" + context_text + user_pref_text
    history_messages = [SystemMessage(content=system_prompt)] + list(state["messages"])

    try:
        response = model.invoke(history_messages)
    except Exception as e:
        print(f"Executor LLM 生成失败: {e}")
        response = AIMessage(content="{\"recipes\": []}")

    return {"candidate_recipes": selected, "ingredients": ingredients, "messages": [response]}

# Direct Chat Node
def _direct_chat_node(state: ChefState) -> dict:
    """Direct Chat Node: 闲聊/烹饪追问/常规对话节点（不查向量库）"""
    system_prompt = (
        "你是一个温馨可爱的智能私人厨师助手。请使用可爱暖心、活泼亲切的语气直接回答用户的问题。\n"
        "如果有关于之前推荐的菜谱的提问（例如烹饪步骤、替换食材、营养成分），请依据上下文和专业烹饪常识给予详尽、贴心的解答。\n"
        "绝对不要输出菜谱 JSON 格式，用纯文字和可爱的Emoji进行友好交谈。"
    )
    
    history_messages = [SystemMessage(content=system_prompt)] + list(state["messages"])
    try:
        response = model.invoke(history_messages)
    except Exception as e:
        print(f"Chat LLM 交互失败: {e}")
        response = AIMessage(content="喵~ 黛黛有点分心了，您可以再说一遍吗？")

    return {"messages": [response]}

# ══════════════════════════════════════════════════════════════════
# 7. 构建与编译 Graph
# ══════════════════════════════════════════════════════════════════
graph_builder = StateGraph(ChefState)

# 注册节点
graph_builder.add_node("planner", _planner_node)
graph_builder.add_node("executor", _executor_node)
graph_builder.add_node("direct_chat", _direct_chat_node)

# 设置流程
graph_builder.set_entry_point("planner")
graph_builder.add_conditional_edges(
    "planner",
    _router,
    {
        "recommend": "executor",
        "chat": "direct_chat"
    }
)
graph_builder.add_edge("executor", END)
graph_builder.add_edge("direct_chat", END)

# 导出供外部使用的 Agent
agent = graph_builder.compile()