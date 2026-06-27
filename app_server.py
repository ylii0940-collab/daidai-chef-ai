import os
import json
import sqlite3
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from agents.personal_chief import graph_builder, score_recipe, parse_image_ingredients

app = FastAPI(title="李黛黛的智能私厨 API 服务", version="2.0")

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 确保资源文件夹存在
os.makedirs("resources", exist_ok=True)

# 初始化 SqliteSaver 持久化检查点
db_path = "resources/personal_chief.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
memory = SqliteSaver(conn)

# 在服务端编译带 SQLite 记忆功能的 Agent
agent_with_memory = graph_builder.compile(checkpointer=memory)

# ── Pydantic 请求模型 ──────────────────────────────────────────
class RecommendRequest(BaseModel):
    thread_id: str
    ingredients: List[str]
    user_profile: Dict[str, Any]

class ChatRequest(BaseModel):
    thread_id: str
    user_query: str

class ClearRequest(BaseModel):
    thread_id: str

class ScoreRecipePayload(BaseModel):
    recipe: Dict[str, Any]
    available_ingredients: List[str]
    user_goals: List[str]

# ── API 路由实现 ──────────────────────────────────────────────

@app.post("/recommend")
async def api_recommend(payload: RecommendRequest):
    """
    接收用户食材和偏好画像，调用 Executor Agent 完成 RAG + 重排并推荐菜谱
    """
    config = {"configurable": {"thread_id": payload.thread_id}}
    prompt_text = (
        f"这是我的食材列表：{', '.join(payload.ingredients)}。\n"
        f"请严格根据我的最新偏好进行搜索并推荐 3 道最合适我烹饪的菜谱。"
    )
    try:
        response = agent_with_memory.invoke(
            {
                "messages": [HumanMessage(content=prompt_text)],
                "user_profile": payload.user_profile,
                "ingredients": payload.ingredients
            },
            config=config
        )
        return {
            "status": "success",
            "response": response["messages"][-1].content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用 Agent 失败: {str(e)}")

@app.post("/chat")
async def api_chat(payload: ChatRequest):
    """
    多轮会话接口，由 Planner Agent 识别意图路由至 Executor 或 Direct Chat Node
    """
    config = {"configurable": {"thread_id": payload.thread_id}}
    try:
        response = agent_with_memory.invoke(
            {"messages": [HumanMessage(content=payload.user_query)]},
            config=config
        )
        return {
            "status": "success",
            "response": response["messages"][-1].content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"调用 Agent 失败: {str(e)}")

@app.get("/history")
async def api_history(thread_id: str):
    """
    根据会话 ID 获取完整的聊天历史消息列表
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = agent_with_memory.get_state(config)
        messages = state.values.get("messages", [])
        
        serializable = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                # 支持处理多模态人类消息内容
                content = msg.content
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                    content = " ".join(text_parts) if text_parts else "[上传了图片食材]"
                serializable.append({"type": "human", "content": content})
            elif isinstance(msg, AIMessage):
                serializable.append({"type": "ai", "content": msg.content})
            elif isinstance(msg, SystemMessage):
                serializable.append({"type": "system", "content": msg.content})
                
        return {"messages": serializable}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取会话历史失败: {str(e)}")

@app.get("/threads")
async def api_threads():
    """
    查询所有已有的会话 Thread ID 列表
    """
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
        rows = cursor.fetchall()
        thread_ids = [row[0] for row in rows if row[0]]
        if not thread_ids:
            thread_ids = ["default_user_chef"]
        return {"threads": thread_ids}
    except Exception:
        return {"threads": ["default_user_chef"]}

@app.post("/clear")
async def api_clear(payload: ClearRequest):
    """
    清除指定会话的所有记忆与状态
    """
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (payload.thread_id,))
        cursor.execute("DELETE FROM checkpoint_writes WHERE thread_id = ?", (payload.thread_id,))
        cursor.execute("DELETE FROM checkpoint_blobs WHERE thread_id = ?", (payload.thread_id,))
        conn.commit()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清空会话记忆失败: {str(e)}")

@app.post("/parse_image")
async def api_parse_image(file: UploadFile = File(...)):
    """
    接收上传的食材图片并调用多模态模型进行结构化识别
    """
    try:
        image_bytes = await file.read()
        result = parse_image_ingredients(image_bytes)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"食材图片识别失败: {str(e)}")

@app.post("/score_recipe")
async def api_score_recipe(payload: ScoreRecipePayload):
    """
    计算特定菜谱针对当前可用食材和画像目标的微观得分
    """
    try:
        scores = score_recipe(payload.recipe, payload.available_ingredients, payload.user_goals)
        return scores
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评分失败: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_server:app", host="0.0.0.0", port=8000, reload=True)
