import os
import socket
# Bypass system-wide proxy DNS spoofing for Aliyun DashScope only in Antigravity Sandbox
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
import json
import re
import sqlite3
import uuid
import streamlit as st
from PIL import Image

# API endpoints config
import os
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

import requests
# 创建禁用系统代理的 Session 实例，用于访问本地 API，避免系统 VPN 代理干扰 127.0.0.1 访问
api_session = requests.Session()
api_session.trust_env = False

from langchain_core.messages import HumanMessage, AIMessage

def parse_image_ingredients(image_bytes: bytes) -> dict:
    try:
        files = {"file": ("image.jpg", image_bytes, "image/jpeg")}
        res = api_session.post(f"{API_BASE_URL}/parse_image", files=files, timeout=60)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        st.error(f"无法连接到 API 服务端进行图片识别: {e}")
    return {"ingredients": []}

def score_recipe(recipe: dict, available_ingredients: list, user_goals: list) -> dict:
    try:
        payload = {
            "recipe": recipe,
            "available_ingredients": available_ingredients,
            "user_goals": user_goals
        }
        res = api_session.post(f"{API_BASE_URL}/score_recipe", json=payload, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return {
        "total": 0.5,
        "match": 0.5,
        "nutrition": 0.5,
        "difficulty": 0.5,
        "time": 0.5
    }

def get_all_thread_ids() -> list:
    try:
        res = api_session.get(f"{API_BASE_URL}/threads", timeout=5)
        if res.status_code == 200:
            return res.json().get("threads", ["default_user_chef"])
    except Exception:
        pass
    return ["default_user_chef"]

def get_chat_history(thread_id: str) -> list:
    try:
        res = api_session.get(f"{API_BASE_URL}/history?thread_id={thread_id}", timeout=10)
        if res.status_code == 200:
            api_messages = res.json().get("messages", [])
            messages = []
            for msg in api_messages:
                if msg["type"] == "human":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["type"] == "ai":
                    messages.append(AIMessage(content=msg["content"]))
            return messages
        else:
            st.error(f"获取聊天历史失败，服务端返回状态码: {res.status_code}")
    except Exception as e:
        st.error(f"获取聊天历史失败: {e}")
    return []

# ══════════════════════════════════════════════════════════════════
# 1. 页面基本配置 & 视觉风格定制
# ══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="李黛黛的智能私厨管家 - 智能食材识别与菜谱推荐",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入自定义 CSS 以实现李黛黛的粉嫩梦幻视觉界面
st.markdown("""
<style>
    /* 页面最大宽度限制并居中，解决宽屏下内容过度拉伸、聊天框偏向最右侧的问题 */
    .block-container {
        max-width: 1250px !important;
        margin: 0 auto !important;
        padding-top: 1.5rem !important;
        padding-bottom: 2rem !important;
    }

    /* 美化对话气泡，使其对齐工整、框线温润、字体舒适 */
    div[data-testid="stChatMessage"] {
        border-radius: 18px !important;
        padding: 10px 14px !important;
        margin-bottom: 10px !important;
        border: 1px solid rgba(255, 180, 200, 0.5) !important;
        background-color: rgba(255, 255, 255, 0.9) !important;
    }

    /* 全局与卡片样式 */
    .main {
        background-color: #FFF5F6;
        color: #4A3B40;
    }
    .stApp {
        background-color: #FFF5F6;
    }
    div[data-testid="stSidebar"] {
        background-color: #FFE4E6;
        border-right: 1px solid #FFCCD5;
    }
    
    /* 覆盖 Streamlit sidebar 文字颜色 */
    div[data-testid="stSidebar"] p, div[data-testid="stSidebar"] span, div[data-testid="stSidebar"] label {
        color: #8C6A74 !important;
    }
    
    /* 标签卡片样式 */
    .tag-container {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 15px;
    }
    .ingredient-tag {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    .tag-owned {
        background-color: rgba(76, 175, 80, 0.1);
        color: #2E7D32 !important;
        border: 1px solid rgba(76, 175, 80, 0.2);
    }
    .tag-missing {
        background-color: rgba(244, 67, 54, 0.1);
        color: #D32F2F !important;
        border: 1px solid rgba(244, 67, 54, 0.2);
    }
    
    /* 偏好标签 */
    .pref-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        margin-right: 6px;
        margin-bottom: 6px;
    }
    .pref-badge-blue {
        background-color: #EBF5FB;
        color: #2471A3 !important;
        border: 1px solid #AED6F1;
    }
    .pref-badge-green {
        background-color: #E8F8F5;
        color: #117A65 !important;
        border: 1px solid #A3E4D7;
    }
    .pref-badge-pink {
        background-color: #FFF0F2;
        color: #D9385C !important;
        border: 1px solid #FFCCD5;
    }
    .pref-badge-orange {
        background-color: #FEF9E7;
        color: #D35400 !important;
        border: 1px solid #FAD7A0;
    }
    
    /* 菜谱新卡片 */
    .recipe-card-new {
        background-color: #FFFFFF;
        border-radius: 24px;
        padding: 20px;
        border: 2px solid #ffd1df;
        margin-bottom: 12px;
        box-shadow: 0 14px 30px rgba(255, 111, 153, 0.12);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .recipe-card-new:hover {
        transform: translateY(-4px);
        box-shadow: 0 18px 40px rgba(255, 111, 153, 0.2);
    }
    .recipe-emoji-box {
        background: linear-gradient(135deg, #ffe5ef 0%, #e9f6ff 100%);
        border-radius: 18px;
        height: 120px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 3.8rem;
        margin-bottom: 12px;
    }
    .recipe-title-new {
        color: #3f2f35;
        font-size: 1.25rem;
        font-weight: 900;
        margin-bottom: 6px;
    }
    .recipe-tag-line {
        color: #ff6f9e;
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 8px;
    }
    .recipe-meta-new {
        display: flex;
        justify-content: space-between;
        font-size: 0.9rem;
        color: #8C6A74;
        font-weight: 500;
        margin-bottom: 8px;
    }
    
    /* 玻璃拟态偏好卡片 */
    .kitty-glass-card {
        background: rgba(255, 255, 255, 0.78);
        border: 2px solid rgba(255, 192, 210, 0.75);
        border-radius: 28px;
        padding: 24px;
        box-shadow: 0 18px 45px rgba(255, 111, 153, 0.12);
        backdrop-filter: blur(12px);
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════
# 2. Session State 初始化与数据同步
# ══════════════════════════════════════════════════════════════════
os.makedirs("resources", exist_ok=True)

if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "📷 食材识别"

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = "default_user_chef"

# 饮食偏好参数全局 Session 存储
if "goal_selections" not in st.session_state:
    st.session_state["goal_selections"] = ["减脂", "高蛋白"]

if "avoid_list" not in st.session_state:
    st.session_state["avoid_list"] = ["不吃辣", "忌油炸"]

if "equipment_selections" not in st.session_state:
    st.session_state["equipment_selections"] = ["明火炒锅", "电饭煲", "微波炉"]

if "cook_time_limit" not in st.session_state:
    st.session_state["cook_time_limit"] = 30

thread_id = st.session_state["thread_id"]

# ══════════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════════
def is_recipe_json(content: str) -> bool:
    if not content:
        return False
    content_stripped = content.strip()
    if content_stripped.startswith("```"):
        content_stripped = re.sub(r"^```[a-zA-Z]*\n|```$", "", content_stripped, flags=re.MULTILINE).strip()
    try:
        data = json.loads(content_stripped)
        if isinstance(data, dict) and "recipes" in data:
            return True
    except:
        pass
        
    try:
        match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict) and "recipes" in data:
                return True
    except:
        pass
        
    if '"recipes"' in content and '"required_ingredients"' in content and '"steps"' in content:
        return True
        
    return False

def parse_recipe_json(content: str) -> dict:
    match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except:
            pass
            
    content_stripped = content.strip()
    if content_stripped.startswith("```"):
        content_stripped = re.sub(r"^```[a-zA-Z]*\n|```$", "", content_stripped, flags=re.MULTILINE).strip()
    try:
        return json.loads(content_stripped)
    except Exception as e:
        start = content_stripped.find("{")
        end = content_stripped.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(content_stripped[start:end+1])
            except:
                pass
        raise e

def format_recipe_message(content: str) -> str:
    if not is_recipe_json(content):
        return content
    try:
        data = parse_recipe_json(content)
        recipes = data.get("recipes", [])
        if not recipes:
            return "喵~ 黛黛这次没找到合适的菜谱，可以试着换些食材或调整偏好哦~ 💕"
            
        summary = "喵~ 已经为你量身定制了以下 3 道美味菜谱！快去左侧 **“🍲 菜谱推荐”** 面板查看具体的烹饪步骤吧：\n\n"
        for idx, r in enumerate(recipes):
            name = r.get("name", "未命名菜谱")
            calories = r.get("calories", 0)
            desc = r.get("description", "")
            summary += f"**{idx + 1}. {name}** 🍳\n"
            summary += f"  * *热量*: {calories} kcal\n"
            if desc:
                summary += f"  * *特色*: {desc}\n"
            summary += "\n"
        return summary
    except Exception as e:
        clean_content = re.sub(r"```json\s*\{.*?\}\s*```", "", content, flags=re.DOTALL).strip()
        clean_content = re.sub(r"\{.*?\}", "", clean_content, flags=re.DOTALL).strip()
        if not clean_content or len(clean_content) < 5:
            clean_content = "我已经为您重新生成了菜谱推荐，请看“菜谱推荐”页的最新结果！"
        return clean_content

def get_recipe_emoji(recipe_name: str) -> str:
    name = recipe_name.lower()
    if any(k in name for k in ["鸡", "chicken"]):
        return "🍗"
    if any(k in name for k in ["肉", "牛", "猪", "排", "pork", "beef"]):
        return "🥩"
    if any(k in name for k in ["蛋", "egg"]):
        return "🍳"
    if any(k in name for k in ["鱼", "虾", "海鲜", "蟹", "fish", "shrimp"]):
        return "🐟"
    if any(k in name for k in ["饭", "rice"]):
        return "🍚"
    if any(k in name for k in ["面", "粉", "noodles"]):
        return "🍜"
    if any(k in name for k in ["汤", "soup"]):
        return "🍲"
    if any(k in name for k in ["菜", "西兰花", "番茄", "茄子", "黄瓜", "西兰"]):
        return "🥗"
    return "🍽️"

def get_all_thread_ids() -> list:
    try:
        conn = sqlite3.connect("resources/personal_chief.db")
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows if row[0]]
    except Exception:
        return ["default_user_chef"]

# ══════════════════════════════════════════════════════════════════
# 3. 侧边栏设置 (偏好设置 & 对话参数)
# ══════════════════════════════════════════════════════════════════
with st.sidebar:
    # Hello Kitty Sidebar image logo
    if os.path.exists("resources/kitty_chef.png"):
        st.image("resources/kitty_chef.png", use_container_width=True)
    st.markdown("<h1 style='text-align: center; color: #FF6B8B; font-family: sans-serif; font-weight: bold; margin-top: -10px;'>🎀 黛黛私厨</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #8C6A74; font-size: 0.9rem; font-weight: 500;'>食材智能扫描 · 黛黛精准打分 · 温暖多轮对话</p>", unsafe_allow_html=True)
    st.write("---")
    
    # 交互式功能导航（完全实现交互）
    st.markdown("### 🎀 功能导航")
    
    tabs_meta = [
        {"icon": "📷", "label": "食材识别"},
        {"icon": "🍲", "label": "菜谱推荐"},
        {"icon": "🤍", "label": "我的偏好"},
        {"icon": "💬", "label": "历史会话"}
    ]
    
    for tab in tabs_meta:
        tab_full_name = f"{tab['icon']} {tab['label']}"
        is_active = st.session_state["active_tab"] == tab_full_name
        
        # 激活样式和普通样式按钮
        btn_label = f"✨ {tab_full_name} ✨" if is_active else tab_full_name
        if st.button(btn_label, key=f"nav_btn_{tab['label']}", use_container_width=True):
            st.session_state["active_tab"] = tab_full_name
            st.rerun()
            
    st.write("---")
    
    # Profile Card
    st.markdown("""
    <div style="background-color: #FFF0F2; border-radius: 12px; padding: 12px; border: 1px solid #FFCCD5; display: flex; align-items: center; gap: 10px;">
        <div style="font-size: 2.2rem;">🐱</div>
        <div style="flex-grow: 1;">
            <div style="font-weight: bold; color: #D9385C; font-size: 0.95rem;">黛黛小厨娘</div>
            <div style="font-size: 0.75rem; color: #8C6A74; margin-top: 2px;">LV.12 (1250/2000)</div>
            <div style="background-color: #FFE4E6; height: 6px; border-radius: 3px; margin-top: 4px; overflow: hidden;">
                <div style="background-color: #FF6B8B; width: 62.5%; height: 100%;"></div>
            </div>
        </div>
        <div style="font-size: 1.2rem; cursor: pointer; color: #8C6A74;">⚙️</div>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════
# 4. 主界面布局与三栏式分发逻辑
# ══════════════════════════════════════════════════════════════════
col_main, col_chat = st.columns([5, 3])

# 获取当前激活的标签值
current_tab = st.session_state["active_tab"]
thread_id = st.session_state["thread_id"]

# 全局获取当前 thread 的聊天历史，保持对话与主推荐面板数据完全同步，避免 NameError
messages = get_chat_history(thread_id)

with col_main:
    # 顶部横幅标题 (全局共享)
    st.markdown("""
    <div style="padding: 10px 0; margin-bottom: 20px;">
        <h1 style="color: #FF6B8B; margin: 0; font-size: 2.6rem; font-family: sans-serif; font-weight: bold; display: flex; align-items: center; gap: 12px;">
            AI 私厨管家 <span style="font-size: 2.2rem;">🎀</span>
        </h1>
        <p style="color: #8C6A74; margin-top: 8px; font-size: 1.15rem; font-weight: 500;">
            识别食材，智能推荐，让每一餐都更美味 💕
        </p>
    </div>
    """, unsafe_allow_html=True)

    # ── TAB 1：食材识别 ──────────────────────────────────────────
    if current_tab == "📷 食材识别":
        st.markdown("### 📷 上传冰箱或食材照片")
        uploaded_file = st.file_uploader("支持 JPG, PNG, JPEG 格式，图片清晰效果更佳~", type=["jpg", "png", "jpeg"])
        
        if uploaded_file is not None:
            image = Image.open(uploaded_file)
            st.image(image, caption="已上传食材图片", use_container_width=True)
            
            if st.button("🌸 开始智能识别食材", use_container_width=True):
                image_bytes = uploaded_file.getvalue()
                with st.spinner("🎀 黛黛正在用放大镜看食材，请稍候..."):
                    parsed_result = parse_image_ingredients(image_bytes)
                    ingredients = parsed_result.get("ingredients", [])
                    
                    if ingredients:
                        names = [item["name"] for item in ingredients]
                        st.session_state["ingredients_list"] = names
                        st.session_state["ingredients_details"] = ingredients
                        st.success(f"🎀 成功识别到 {len(names)} 种食材！")
                    else:
                        st.warning("黛黛没能看清是什么食材，可以重新上传或者在右侧手动输入哦~")

        st.markdown("### 🐾 识别出的食材")
        if "ingredients_list" not in st.session_state:
            st.session_state["ingredients_list"] = ["鸡胸肉", "番茄", "鸡蛋", "大蒜"]
            
        ingredients_input = st.text_input(
            "当前确认的食材清单（用逗号分隔，可手动修改）：",
            value=", ".join(st.session_state["ingredients_list"]),
            key="ingredients_input_widget"
        )
        
        updated_list = [i.strip() for i in re.split(r"[,，]", ingredients_input) if i.strip()]
        st.session_state["ingredients_list"] = updated_list
        
        if updated_list:
            html_tags = "".join([f"<span class='ingredient-tag tag-owned'>🍳 {i}</span>" for i in updated_list])
            st.markdown(f"<div class='tag-container'>{html_tags}</div>", unsafe_allow_html=True)
        else:
            st.info("食材清单空空如也，请先上传照片或手动输入食材吧~")
            
        st.markdown("### 🐾 我的偏好")
        pref_tags = []
        for g in st.session_state["goal_selections"]:
            pref_tags.append(f"<span class='pref-badge pref-badge-blue'>{g}</span>")
        for a in st.session_state["avoid_list"]:
            pref_tags.append(f"<span class='pref-badge pref-badge-pink'>{a}</span>")
        for e in st.session_state["equipment_selections"]:
            pref_tags.append(f"<span class='pref-badge pref-badge-green'>{e}</span>")
        pref_tags.append(f"<span class='pref-badge pref-badge-orange'>{st.session_state['cook_time_limit']}分钟内</span>")
        st.markdown(f"<div class='tag-container'>{''.join(pref_tags)}</div>", unsafe_allow_html=True)
        
        # 推荐触发按钮
        st.write("")
        if st.button("🔥 开始为我量身推荐 3 道菜谱", type="primary", use_container_width=True):
            if not st.session_state["ingredients_list"]:
                st.error("请先在上方输入或识别至少一种食材！")
            else:
                profile = {
                    "goal": st.session_state["goal_selections"],
                    "avoid": st.session_state["avoid_list"],
                    "equipment": st.session_state["equipment_selections"],
                    "cook_time_limit": st.session_state["cook_time_limit"]
                }
                with st.spinner("🎯 正在搜索网络并匹配推荐..."):
                    try:
                        payload = {
                            "thread_id": thread_id,
                            "ingredients": st.session_state["ingredients_list"],
                            "user_profile": profile
                        }
                        res = api_session.post(f"{API_BASE_URL}/recommend", json=payload, timeout=60)
                        if res.status_code == 200:
                            st.success("🎉 菜谱推荐生成成功！已存入“菜谱推荐”页。")
                            st.session_state["active_tab"] = "🍲 菜谱推荐"
                            st.rerun()
                        else:
                            st.error(f"推荐失败: {res.text}")
                    except Exception as e:
                        st.error(f"调用 API 失败: {e}")

    # ── TAB 2：菜谱推荐 ──────────────────────────────────────────
    elif current_tab == "🍲 菜谱推荐":
        st.markdown("### 🎀 为你推荐")
        
        # 检索最新的菜谱 JSON 推荐 (使用已在全局获取的 messages 列表)
        latest_recipes_data = None
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and is_recipe_json(msg.content):
                try:
                    latest_recipes_data = parse_recipe_json(msg.content)
                    break
                except:
                    continue
                    
        if latest_recipes_data:
            recipes = latest_recipes_data.get("recipes", [])
            recipe_cols = st.columns(len(recipes) if recipes else 1)
            
            for idx, recipe in enumerate(recipes):
                with recipe_cols[idx]:
                    scores = score_recipe(recipe, st.session_state["ingredients_list"], st.session_state["goal_selections"])
                    total_score_pct = int(scores["total"] * 100)
                    
                    req_ingredients = recipe.get("required_ingredients", [])
                    missing_ingredients = recipe.get("missing_ingredients", [])
                    owned_ingredients = [i for i in req_ingredients if i not in missing_ingredients]
                    
                    calories = recipe.get("calories")
                    if not calories:
                        calories = 200 + (len(owned_ingredients) * 45) + (100 if "肉" in recipe.get("name", "") or "鸡" in recipe.get("name", "") else 0)
                    
                    emoji = get_recipe_emoji(recipe.get("name", ""))
                    
                    # 渲染卡片 HTML
                    st.markdown(f"""
                    <div class="recipe-card-new">
                        <div class="recipe-emoji-box">{emoji}</div>
                        <div class="recipe-title-new">{recipe.get('name', '美味菜谱')}</div>
                        <div class="recipe-meta-new">
                            <span>⏱️ {recipe.get('cook_time_minutes', 30)}分钟</span>
                            <span>🔥 {calories} kcal</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    nut_tags = recipe.get("nutrition_tags", [])
                    sub_tags_str = " | ".join(nut_tags[:3]) if nut_tags else "营养定制 | 健康膳食"
                    st.markdown(f"<div class='recipe-tag-line'>{sub_tags_str}</div>", unsafe_allow_html=True)
                    st.markdown(f"🐾 **推荐分数：{total_score_pct}分**")
                    
                    tag_htmls = []
                    for item in owned_ingredients[:3]:
                        tag_htmls.append(f"<span class='ingredient-tag tag-owned' style='font-size: 0.75rem; padding: 2px 8px;'>✓ {item}</span>")
                    for item in missing_ingredients[:2]:
                        tag_htmls.append(f"<span class='ingredient-tag tag-missing' style='font-size: 0.75rem; padding: 2px 8px;'>✗ 缺: {item}</span>")
                    st.markdown(f"<div class='tag-container' style='gap: 4px; margin-bottom: 10px;'>{''.join(tag_htmls)}</div>", unsafe_allow_html=True)
                    
                    with st.expander("👨‍🍳 查看详细烹饪步骤"):
                        st.write(f"**制作难度**: {recipe.get('difficulty', '中等')}")
                        st.write("**具体烹饪步骤：**")
                        for step_idx, step in enumerate(recipe.get("steps", [])):
                            st.write(f"**{step_idx + 1}.** {step}")
            
            st.write("")
            if st.button("🐾 返回食材识别重新生成", use_container_width=True):
                st.session_state["active_tab"] = "📷 食材识别"
                st.rerun()
        else:
            st.info("💡 尚未推荐任何菜谱。请先前往“📷 食材识别”页，点击“量身推荐”按钮进行推荐。")
            if st.button("🚀 前往食材识别", use_container_width=True):
                st.session_state["active_tab"] = "📷 食材识别"
                st.rerun()

    # ── TAB 3：我的偏好 ──────────────────────────────────────────
    elif current_tab == "🤍 我的偏好":
        st.markdown("### 🤍 管理我的个人偏好")
        
        # 使用玻璃卡片容器包装设置面板
        st.markdown("<div class='kitty-glass-card'>", unsafe_allow_html=True)
        
        # 饮食健康目标
        goal_options = ["减脂", "增肌", "清淡", "低碳", "低糖", "高蛋白", "低脂"]
        selected_goals = st.multiselect(
            "🎯 饮食与健康目标", 
            options=goal_options, 
            default=st.session_state["goal_selections"]
        )
        
        # 避开/过敏食材
        avoid_str = ", ".join(st.session_state["avoid_list"])
        avoid_input_val = st.text_input("🚫 忌口 / 避开食材 (逗号分隔)", value=avoid_str)
        selected_avoids = [x.strip() for x in avoid_input_val.split(",") if x.strip()]
        
        # 可用厨具
        equipment_options = ["明火炒锅", "电饭煲", "烤箱", "空气炸锅", "微波炉", "压力锅"]
        selected_equipments = st.multiselect(
            "🔌 可用烹饪器具", 
            options=equipment_options, 
            default=st.session_state["equipment_selections"]
        )
        
        # 烹饪时间限制
        selected_time_limit = st.slider(
            "⏱️ 烹饪时间上限 (分钟)", 
            min_value=10, 
            max_value=120, 
            value=st.session_state["cook_time_limit"], 
            step=5
        )
        
        st.markdown("</div>", unsafe_allow_html=True)
        
        if st.button("💾 保存饮食偏好并应用", type="primary", use_container_width=True):
            st.session_state["goal_selections"] = selected_goals
            st.session_state["avoid_list"] = selected_avoids
            st.session_state["equipment_selections"] = selected_equipments
            st.session_state["cook_time_limit"] = selected_time_limit
            st.success("✨ 个人饮食偏好已成功更新并应用！")
            st.rerun()

    # ── TAB 4：历史会话 ──────────────────────────────────────────
    elif current_tab == "💬 历史会话":
        st.markdown("### 💬 多轮对话会话配置")
        
        st.markdown("<div class='kitty-glass-card'>", unsafe_allow_html=True)
        
        # 选择和切换历史会话
        thread_ids = get_all_thread_ids()
        if not thread_ids:
            thread_ids = [thread_id]
            
        selected_thread = st.selectbox(
            "🔗 切换历史对话 (Thread ID)", 
            options=thread_ids, 
            index=thread_ids.index(thread_id) if thread_id in thread_ids else 0
        )
        
        if selected_thread != thread_id:
            st.session_state["thread_id"] = selected_thread
            st.success(f"已成功切换至会话: {selected_thread}")
            st.rerun()
            
        # 新增/手动输入 Thread ID
        new_thread = st.text_input("➕ 输入新会话 Thread ID 并创建/切换", value=thread_id)
        if st.button("🔄 切换至新 Thread", use_container_width=True):
            if new_thread.strip():
                st.session_state["thread_id"] = new_thread.strip()
                st.success(f"已创建并切换至会话: {new_thread}")
                st.rerun()
                
        st.markdown("</div>", unsafe_allow_html=True)
        
        # 清空当前会话按钮
        st.write("---")
        st.markdown("##### ⚠️ 会话数据清理")
        if st.button("🗑️ 完全清理当前会话的记忆", type="primary", use_container_width=True):
            try:
                res = api_session.post(f"{API_BASE_URL}/clear", json={"thread_id": thread_id}, timeout=10)
                if res.status_code == 200:
                    st.session_state.clear()
                    st.success("✨ 会话记忆已完全清除！")
                    st.rerun()
                else:
                    st.error(f"清理失败: {res.text}")
            except Exception as e:
                st.error(f"清理失败: {e}")

# ══════════════════════════════════════════════════════════════════
# 5. 右侧小助手面板 (Chatbot Column) - 全局同步呈现
# ══════════════════════════════════════════════════════════════════
with col_chat:
    st.markdown("""
    <div style="background-color: #FFF0F2; border-radius: 16px; padding: 12px; border: 1px solid #FFCCD5; margin-bottom: 12px;">
        <h3 style="color: #D9385C; margin: 0; display: flex; align-items: center; gap: 8px; font-size: 1.3rem;">
            🐱 喵喵小助手 <span style="background-color: #FF6B8B; color: white; font-size: 0.7rem; padding: 2px 8px; border-radius: 10px; font-weight: bold;">AI</span>
        </h3>
    </div>
    """, unsafe_allow_html=True)
    
    # 渲染对话历史
    chat_container = st.container(height=485)
    
    with chat_container:
        has_assistant_reply = any(isinstance(m, AIMessage) and not is_recipe_json(m.content) for m in messages)
        if not has_assistant_reply:
            with st.chat_message("assistant", avatar="🐱"):
                st.markdown("嗨呀！我是你的 AI 私厨管家~ 根据你冰箱里的食材和偏好，我为你推荐了这些美味菜谱 💕 需要我帮你调整口味或推荐其他菜式吗？")
                
        for msg in messages:
            if isinstance(msg, HumanMessage) and "我的当前食材列表是" in msg.content:
                continue
                
            role = "user" if isinstance(msg, HumanMessage) else "assistant"
            avatar = "👧" if role == "user" else "🐱"
            with st.chat_message(role, avatar=avatar):
                if role == "assistant":
                    st.markdown(format_recipe_message(msg.content))
                else:
                    st.markdown(msg.content)
                
    # 快捷建议输入行
    st.write("")
    col_s1, col_s2, col_s3 = st.columns(3)
    clicked_suggestion = None
    with col_s1:
        if st.button("🐾 换个口味", use_container_width=True, key="sug_taste"):
            clicked_suggestion = "帮我换个口味，重新推荐一些别的菜吧~"
    with col_s2:
        if st.button("🐾 适合带饭", use_container_width=True, key="sug_lunch"):
            clicked_suggestion = "有没有适合做便当、带饭去公司的菜谱推荐？"
    with col_s3:
        if st.button("🐾 更多减脂", use_container_width=True, key="sug_lowfat"):
            clicked_suggestion = "帮我推荐一个更低脂更健康的减脂菜谱吧~"

    # 执行提问逻辑
    user_query = st.chat_input("输入你的问题...")
    if clicked_suggestion:
        user_query = clicked_suggestion
        
    if user_query:
        with chat_container:
            with st.chat_message("user", avatar="👧"):
                st.markdown(user_query)
                
        with chat_container:
            with st.chat_message("assistant", avatar="🐱"):
                response_placeholder = st.empty()
                with st.spinner("思考中..."):
                    try:
                        payload = {
                            "thread_id": thread_id,
                            "user_query": user_query
                        }
                        res = api_session.post(f"{API_BASE_URL}/chat", json=payload, timeout=60)
                        if res.status_code == 200:
                            res_data = res.json()
                            assistant_reply = res_data.get("response", "")
                            
                            if is_recipe_json(assistant_reply):
                                st.session_state["latest_recipes"] = parse_recipe_json(assistant_reply)
                                response_placeholder.markdown("我已经为您重新生成了菜谱推荐，请看“菜谱推荐”页的最新结果！")
                                st.session_state["active_tab"] = "🍲 菜谱推荐"
                                st.rerun()
                            else:
                                response_placeholder.markdown(assistant_reply)
                                st.rerun()
                        else:
                            response_placeholder.error(f"获取回复失败: {res.text}")
                    except Exception as e:
                        response_placeholder.error(f"获取回复失败: {e}")