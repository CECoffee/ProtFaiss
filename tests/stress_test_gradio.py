import asyncio
import aiohttp
from aiohttp_sse_client import client as sse_client
import random
import string
import time
import json

# ==== 配置 ====
URL_JOIN = "http://127.0.0.1:7860/gradio_api/queue/join?"
URL_DATA = "http://127.0.0.1:7860/gradio_api/queue/data"
QUERY = ">Query_Protein\nMSNYFVSGISSGIGNALARLLAARGDTVYGLGRKLLSFNNASIHYRQIDLSCLLDLEHQ"
CONCURRENT = 1000        # 并发量，可调

def random_hash(n=11):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

async def send_request(session):
    session_hash = random_hash()
    trigger_id = random.randint(1, 100000)
    payload = {
        "data": [QUERY, 5],
        "fn_index": 0,
        "event_data": None,
        "session_hash": session_hash,
        "trigger_id": trigger_id
    }

    start = time.time()
    try:
        # 1️⃣ 提交任务
        async with session.post(URL_JOIN, json=payload) as resp:
            join_resp = await resp.json()
            event_id = join_resp.get("event_id")
            if not event_id:
                print("提交失败:", join_resp)
                return None

        # 2️⃣ SSE 流监听
        url_sse = f"{URL_DATA}?event_id={event_id}&session_hash={session_hash}"
        async with sse_client.EventSource(url_sse) as source:
            async for event in source:
                try:
                    data = json.loads(event.data)
                except json.JSONDecodeError:
                    continue

                msg = data.get("msg", "")
                # 任务完成
                if msg in ("process_completed", "close_stream"):
                    print("完成: ", event_id)
                    break

        total_time = time.time() - start
        return total_time

    except Exception as e:
        print("请求异常:", e)
        return None

async def main(concurrent=CONCURRENT):
    async with aiohttp.ClientSession() as session:
        tasks = [asyncio.create_task(send_request(session)) for _ in range(concurrent)]
        times = await asyncio.gather(*tasks)
        times = [t for t in times if t is not None]
        if times:
            print(f"\n并发 {concurrent} 请求完成")
            print(f"平均耗时: {sum(times)/len(times):.3f}s")
            print(f"最短耗时: {min(times):.3f}s")
            print(f"最长耗时: {max(times):.3f}s")
        else:
            print("没有成功请求")

if __name__ == "__main__":
    asyncio.run(main())
