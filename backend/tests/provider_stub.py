"""Local protocol fixture for integration tests; never used as product fallback."""

import asyncio
import json
import re

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
embedding_events = []


def vector(text):
    if any(word in text for word in ("年假", "annual")):
        return [1.0, 0.0, 0.0, 0.0]
    if "报销" in text:
        return [0.0, 1.0, 0.0, 0.0]
    return [0.0, 0.0, 0.0, 1.0]


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    body = await request.json()
    texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
    event = {"input": "\n".join(texts), "status": "started"}
    embedding_events.append(event)
    if any("旧版本慢构建" in text for text in texts):
        await asyncio.sleep(4)
    event["status"] = "completed"
    dimensions = int(body["model"].rsplit("-", 1)[-1]) if re.search(r"-\d+$", body["model"]) else 4
    return {
        "data": [
            {"index": index, "embedding": vector(text) + [0.0] * (dimensions - 4)}
            for index, text in enumerate(texts)
        ],
        "usage": {"prompt_tokens": 5 * len(texts), "total_tokens": 5 * len(texts)},
    }


@app.get("/embedding-events")
async def events():
    return embedding_events


@app.post("/v1/rerank")
async def rerank(request: Request):
    body = await request.json()
    query = body["query"]
    relevant = any(word in query for word in ("年假", "报销"))
    return {
        "results": [
            {"index": index, "relevance_score": 0.95 if relevant else 0.05}
            for index in range(min(body.get("top_n", 5), len(body["documents"])))
        ],
        "usage": {"total_tokens": 7},
    }


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body["messages"]
    prompt = messages[-1]["content"]
    if "改写" in messages[0]["content"]:
        question = prompt.rsplit("当前问题：", 1)[-1]
        answer = "员工年假有多少天" if "多少" in question else question
    elif "知识片段" in prompt:
        question = prompt.rsplit("本轮原始要求：", 1)[-1]
        answer = "报销需要发票和审批单。[1]" if "报销" in question else "员工年假为 10 天。[1]"
    else:
        answer = "OK"
    usage = {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
    if not body.get("stream"):
        return {"model": body["model"], "choices": [{"message": {"content": answer}}], "usage": usage}

    async def events():
        for part in re.findall(r".{1,6}", answer):
            yield "data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n"
        yield (
            "data: "
            + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage})
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
