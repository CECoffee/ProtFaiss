# bench_submit.py
import asyncio
import aiohttp
import random
import string
import time
import json
from typing import Optional

# ==== 配置 ====
BASE_URL = "http://127.0.0.1:8000"
SUBMIT_PATH = "/query/submit"
RESULT_PATH = "/query/result"              # will be used as /result/{task_id}
QUERY = ">Query_Protein\nMSNYFVSGISSGIGNALARLLAARGDTVYGLGRKLLSFNNASIHYRQIDLSCLLDLEHQ"
CONCURRENT = 1000                    # 并发量，可调
PER_TASK_TIMEOUT = 120.0             # 每任务最大等待秒数（提交->完成）
POLL_INITIAL_DELAY = 0.5             # 轮询初始等待 (s)
POLL_MAX_DELAY = 4.0                 # 轮询最大等待 (s)
MAX_POLL_ATTEMPTS = 100              # 最大轮询次数（以避免无限轮询）
TOP_K = 5
POOLING = "mean"

# ==== helper ====
def rand_hash(n=11):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

async def submit_and_wait(session: aiohttp.ClientSession, idx: int) -> Optional[float]:
    """
    提交 /submit -> 得到 task_id -> 轮询 /result/{task_id}
    返回总耗时（秒），或 None（表示失败/超时）
    """
    payload = {
        "sequence": QUERY,
        "top_k": TOP_K,
        "pooling": POOLING
    }
    try:
        # 1) 提交任务
        submit_url = BASE_URL + SUBMIT_PATH
        async with session.post(submit_url, json=payload, timeout=30) as resp:
            if resp.status != 200:
                text = await resp.text()
                # treat non-200 as failure
                # Return None but log
                print(f"[{idx}] submit HTTP {resp.status}: {text}")
                return None
            submit_json = await resp.json()
            task_id = submit_json.get("task_id")
            if not task_id:
                print(f"[{idx}] submit response missing task_id: {submit_json}")
                return None

        # 2) Poll result with exponential backoff
        poll_delay = POLL_INITIAL_DELAY
        start_ts = time.time()
        total_wait = 0.0
        attempts = 0
        result_url = f"{BASE_URL}{RESULT_PATH}/{task_id}"
        while True:
            attempts += 1
            # Respect overall task timeout
            elapsed = time.time() - start_ts
            if elapsed > PER_TASK_TIMEOUT:
                print(f"[{idx}] task {task_id} timeout after {elapsed:.1f}s")
                return None

            try:
                async with session.get(result_url, timeout=30) as r:
                    if r.status == 200:
                        data = await r.json()
                        status = data.get("status")
                        if status == "pending":
                            # not ready, continue polling
                            # fallthrough to sleep/backoff
                            pass
                        elif status == "done":
                            # success
                            total_time = time.time() - start_ts
                            print(f"done: {task_id}")
                            return total_time
                        elif status == "error":
                            print(f"[{idx}] task {task_id} returned error: {data.get('error')}")
                            return None
                        else:
                            # Unexpected status - treat as failure/stop
                            print(f"[{idx}] task {task_id} unexpected status: {status}")
                            return None
                    elif r.status in (403, 404):
                        text = await r.text()
                        print(f"[{idx}] poll HTTP {r.status}: {text}")
                        return None
                    else:
                        # other statuses: retry
                        text = await r.text()
                        print(f"[{idx}] poll HTTP {r.status}: {text}")
            except asyncio.TimeoutError:
                print(f"[{idx}] poll request timeout (attempt {attempts})")
            except Exception as e:
                print(f"[{idx}] poll request exception: {e}")

            # Exponential backoff sleep
            await asyncio.sleep(poll_delay)
            poll_delay = min(POLL_MAX_DELAY, poll_delay * 1.8)
            if attempts >= MAX_POLL_ATTEMPTS:
                print(f"[{idx}] reached max poll attempts ({attempts}) for task {task_id}")
                return None

    except Exception as e:
        print(f"[{idx}] unexpected exception: {e}")
        return None

async def run_benchmark(concurrent: int):
    connector = aiohttp.TCPConnector(limit=0, force_close=False)  # limit=0 => no limit
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Create tasks
        tasks = []
        for i in range(concurrent):
            tasks.append(asyncio.create_task(submit_and_wait(session, i+1)))

        # Gather with progress - we will await all
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Analyze results
    times = []
    errors = 0
    exceptions = 0
    for r in results:
        if isinstance(r, Exception):
            exceptions += 1
        elif r is None:
            errors += 1
        else:
            times.append(r)

    success = len(times)
    total = concurrent
    print("\n==== Summary ====")
    print(f"concurrent targets: {total}")
    print(f"successful completions: {success}")
    print(f"failed / timed out: {errors}")
    print(f"exceptions: {exceptions}")
    if times:
        print(f"avg time: {sum(times)/len(times):.3f}s")
        print(f"min time: {min(times):.3f}s")
        print(f"max time: {max(times):.3f}s")
    else:
        print("no successful runs.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Benchmark /submit -> /result polling")
    parser.add_argument("--concurrent", "-c", type=int, default=CONCURRENT, help="concurrent tasks to spawn")
    parser.add_argument("--url", type=str, default=BASE_URL, help="base URL of the API (scheme://host:port)")
    parser.add_argument("--timeout", type=float, default=PER_TASK_TIMEOUT, help="per-task timeout (s)")
    parser.add_argument("--monitor-gpu", action="store_true", help="Poll /gpu/status every 5s during test")
    parser.add_argument("--build-test", type=str, default=None, metavar="FASTA",
                        help="Submit a build job with the given FASTA file and monitor progress")
    args = parser.parse_args()

    BASE_URL = args.url.rstrip("/")
    PER_TASK_TIMEOUT = args.timeout

    if args.build_test:
        asyncio.run(_run_build_test(args.build_test, BASE_URL))
    elif args.monitor_gpu:
        asyncio.run(_run_with_gpu_monitor(args.concurrent, BASE_URL))
    else:
        asyncio.run(run_benchmark(args.concurrent))


async def _poll_gpu_status(base_url: str, stop_event: asyncio.Event):
    """Background task: poll /gpu/status every 5 seconds."""
    import aiohttp
    async with aiohttp.ClientSession() as session:
        while not stop_event.is_set():
            try:
                async with session.get(f"{base_url}/gpu/status", timeout=5) as r:
                    if r.status == 200:
                        data = await r.json()
                        gpus = data.get("gpus", [])
                        parts = [
                            f"GPU{g['id']}: {g['used']}MB/{g['total']}MB"
                            for g in gpus
                        ]
                        print(f"[GPU] {' | '.join(parts) if parts else 'no GPUs'}")
            except Exception as e:
                print(f"[GPU] status error: {e}")
            await asyncio.sleep(5)


async def _run_with_gpu_monitor(concurrent: int, base_url: str):
    """Run benchmark with GPU monitoring in background."""
    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(_poll_gpu_status(base_url, stop_event))
    try:
        await run_benchmark(concurrent)
    finally:
        stop_event.set()
        await monitor_task


async def _run_build_test(fasta_path: str, base_url: str):
    """Submit a build job and monitor progress until done."""
    import aiohttp
    print(f"[build-test] Submitting build job with {fasta_path} ...")
    async with aiohttp.ClientSession() as session:
        with open(fasta_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("file", f, filename="input.fasta", content_type="text/plain")
            data.add_field("name", "stress-test-build")
            data.add_field("algorithm", "flat")
            async with session.post(f"{base_url}/build/submit", data=data, timeout=30) as r:
                if r.status != 200:
                    print(f"[build-test] Submit failed: {r.status} {await r.text()}")
                    return
                result = await r.json()
                dataset_id = result["dataset_id"]
                print(f"[build-test] Job submitted: {dataset_id}")

        prev_detail = ""
        prev_pct = -1.0
        while True:
            await asyncio.sleep(2)
            async with session.get(f"{base_url}/build/status/{dataset_id}", timeout=10) as r:
                if r.status != 200:
                    print(f"[build-test] Status error: {r.status}")
                    break
                entry = await r.json()
                status = entry.get("status")
                pct = entry.get("progress_pct", 0)
                detail = entry.get("progress_detail", "")

                if detail != prev_detail or abs(pct - prev_pct) >= 1.0:
                    print(f"[build-test] {status} | {detail}")
                    prev_detail = detail
                    prev_pct = pct

                if status in ("ready", "error"):
                    print(f"[build-test] Final status: {status}")
                    if status == "error":
                        print(f"[build-test] Error: {entry.get('error_msg')}")
                    break
