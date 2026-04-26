"""
tests/test_api.py
手动 API 测试脚本

用法:
    # 运行所有测试
    python3 tests/test_api.py

    # 运行单个测试
    python3 tests/test_api.py health
    python3 tests/test_api.py llm
    python3 tests/test_api.py tts
    python3 tests/test_api.py image
    python3 tests/test_api.py bgm
    python3 tests/test_api.py video  <image_url>           # 需要提供图片 URL
    python3 tests/test_api.py synth  <video_url> <audio_url>  # 需要视频+音频 URL
"""

import json
import sys
import time

import requests

# ─── 配置 ───────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:9000"

# ─── 工具函数 ────────────────────────────────────────────────────────────────

def _req(method: str, path: str, data: dict | None = None, timeout: int = 10) -> dict | None:
    """发送 HTTP 请求，打印结果，返回 JSON 或 None"""
    url = f"{BASE_URL}{path}"
    print(f"\n{'─'*60}")
    print(f"  [{method}] {url}")
    if data:
        print(f"  Body: {json.dumps(data, ensure_ascii=False)[:200]}")
    print(f"{'─'*60}")

    try:
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, json=data, timeout=timeout)

        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ OK  →  {json.dumps(result, ensure_ascii=False)[:400]}")
            return result
        else:
            print(f"❌ HTTP {resp.status_code}  →  {resp.text[:400]}")
    except requests.exceptions.ConnectionError:
        print(f"💥 连接失败：请确认 api_service 已在 {BASE_URL} 启动")
    except Exception as e:
        print(f"💥 异常：{e}")
    return None


def wait_for_task(task_id: str, interval: int = 3, timeout: int = 120) -> dict | None:
    """轮询任务直到完成或超时"""
    print(f"\n⏳ 轮询 task_id={task_id}  (间隔 {interval}s, 超时 {timeout}s)")
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        res = _req("GET", f"/tasks/{task_id}")
        if res:
            status = res.get("status")
            if status == "completed":
                print(f"✅ 任务完成！elapsed={res.get('elapsed_seconds', '?')}s")
                return res
            elif status == "failed":
                print(f"❌ 任务失败：{res.get('error')}")
                return res
            else:
                print(f"   状态={status}，等待 {interval}s ...")
        time.sleep(interval)
    print("⏰ 等待超时")
    return None

# ─── 各独立测试函数 ───────────────────────────────────────────────────────────

def test_health():
    """1. 健康检查：检查所有后端服务状态"""
    print("\n" + "="*60)
    print("  🏥 [1/7] Health Check")
    print("="*60)
    res = _req("GET", "/health")
    if res:
        for b in res.get("backends", []):
            icon = "🟢" if b["healthy"] else "🔴"
            err  = f"  ({b['error']})" if b.get("error") else ""
            print(f"  {icon} {b['name']}{err}")
    return res


def test_llm():
    """2. LLM 文本生成 (NVIDIA NIM)"""
    print("\n" + "="*60)
    print("  🤖 [2/7] LLM Generate")
    print("="*60)
    return _req("POST", "/llm/generate", {
        "messages": [
            {"role": "system", "content": "你是一个创意小说家。"},
            {"role": "user",   "content": "用一句话写一个赛博朋克故事开头。"},
        ],
        "max_tokens": 200,
        "temperature": 0.8,
    })


def test_tts(text: str = "测试语音合成功能，霓虹灯闪烁的城市里，一个人工智能正在觉醒。"):
    """3. TTS 语音合成 (Edge TTS)"""
    print("\n" + "="*60)
    print("  🔊 [3/7] TTS Synthesize")
    print("="*60)
    res = _req("POST", "/tts/synthesize", {
        "text": text,
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "format": "mp3",
    })
    if res and "task_id" in res:
        result = wait_for_task(res["task_id"])
        if result and result.get("result"):
            audio_url = result["result"].get("audio_url")
            print(f"\n🎵 音频地址：{BASE_URL}{audio_url}")
            return audio_url
    return None


def test_image(prompt: str = "A futuristic cyberpunk city at night, neon signs, rain-slicked streets, cinematic", steps: int = 4):
    """4. 文生图 (ComfyUI + Z-Image-Turbo)"""
    print("\n" + "="*60)
    print("  🖼️  [4/7] Image Generate")
    print("="*60)
    res = _req("POST", "/image/generate", {
        "prompt": prompt,
        "negative_prompt": "", # Z-Image-Turbo 不使用 negative prompt
        "width": 640,
        "height": 480,
        "steps": steps,
        "cfg": 1.0,
        "seed": -1,
    })
    if res and "task_id" in res:
        result = wait_for_task(res["task_id"], timeout=180)
        if result and result.get("result"):
            images = result["result"].get("images", [])
            if images:
                image_url = images[0]["url"]
                print(f"\n🖼️  图像地址：{BASE_URL}{image_url}")
                return image_url
    return None


def test_bgm(prompt: str = "Epic cyberpunk orchestral music, electronic beats, dramatic tension"):
    """5. 背景音乐生成 (ComfyUI ACE-Step)"""
    print("\n" + "="*60)
    print("  🎼 [5/7] BGM Generate")
    print("="*60)
    res = _req("POST", "/bgm/generate", {
        "prompt": prompt,
        "duration_seconds": 15,
        "seed": -1,
    })
    if res and "task_id" in res:
        result = wait_for_task(res["task_id"], timeout=180)
        if result and result.get("result"):
            audio_url = result["result"].get("audio_url")
            print(f"\n🎼 BGM 地址：{BASE_URL}{audio_url}")
            return audio_url
    return None


def test_video(image_url: str, prompt: str = "Camera slowly pans across the cyberpunk cityscape, neon lights flickering"):
    """6. 图生视频 (ComfyUI + Wan2.2 I2V)
    
    Args:
        image_url: 图像的 /files/... 路径（从 test_image 返回值获取）
    """
    print("\n" + "="*60)
    print("  🎬 [6/7] Video Generate (I2V)")
    print("="*60)
    print(f"  输入图像：{image_url}")
    res = _req("POST", "/video/generate", {
        "image_url": image_url,
        "prompt": prompt,
        "negative_prompt": "blurry, static, low quality",
        "num_frames": 81,   # Wan2.2 标准 81 帧 ≈ 3.4s @24fps
        "fps": 24,
        "width": 640,
        "height": 480,
        "seed": -1,
    })
    if res and "task_id" in res:
        result = wait_for_task(res["task_id"], timeout=600)  # 视频生成较慢
        if result and result.get("result"):
            video_url = result["result"].get("video_url")
            print(f"\n🎬 视频地址：{BASE_URL}{video_url}")
            return video_url
    return None


def test_video_synth(video_url, audio_url, bgm_url=None):
    print("\n" + "="*60)
    print("  🎞️  [7/7] Video Synthesize (video + audio)")
    print("="*60)
    print(f"  视频：{video_url}")
    print(f"  音频(TTS)：{audio_url}")
    if bgm_url:
        print(f"  背景音乐：{bgm_url}")

    res = _req("POST", "/video/synthesize", {
        "video_url": video_url,
        "audio_url": audio_url,
        "bgm_url": bgm_url,
        "output_filename": None,
    })
    if res and res.get("video_url"):
        print(f"\n🎞️  合成视频：{BASE_URL}{res['video_url']}")
    return res


# ─── 入口 ─────────────────────────────────────────────────────────────────────

def run_all():
    """按顺序运行全部测试（会自动传递上下游 URL）"""
    print("\n" + "🚀 "*20)
    print("  开始全量 API 测试")
    print("🚀 "*20)

    test_health()
    test_llm()
    audio_url = test_tts()
    image_url = test_image()
    bgm_url   = test_bgm()

    video_url = None
    if image_url:
        video_url = test_video(image_url)
    else:
        print("\n⚠️  跳过 Video Generate（未获取到 image_url）")

    if video_url and (audio_url or bgm_url):
        test_video_synth(video_url, audio_url, bgm_url=bgm_url)
    else:
        print("\n⚠️  跳过 Video Synthesize（缺少 video_url 或音频素材）")

    print("\n" + "✅ "*20)
    print("  全量测试结束")
    print("✅ "*20)


_COMMANDS = {
    "health": (test_health,     "健康检查",              []),
    "llm":    (test_llm,        "LLM 文本生成，写一个小小说，几句话就行",          []),
    "tts":    (test_tts,        "TTS 语音合成",          ["[text]"]),
    "image":  (test_image,      "文生图",                ["[prompt]", "[steps]"]),
    "bgm":    (test_bgm,        "BGM 背景音乐生成",      ["[prompt]"]),
    "video":  (test_video,      "图生视频",              ["<image_url>", "[prompt]"]),
    "synth":  (test_video_synth,"视频+音频合成",         ["<video_url>", "<audio_url>", "[bgm_url]"]),
    "all":    (run_all,         "运行全部",              []),
}


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        # 无参数时打印帮助菜单
        print("\n" + "─"*60)
        print("  AI Novel Video — API 手动测试脚本")
        print("─"*60)
        print("  用法: python3 tests/test_api.py <命令> [参数...]")
        print()
        print("  命令列表：")
        for cmd, (fn, desc, params) in _COMMANDS.items():
            param_str = " ".join(params)
            print(f"    {cmd:<10} {desc:<20} {param_str}")
        print()
        print("  示例：")
        print("    python3 tests/test_api.py health")
        print("    python3 tests/test_api.py llm")
        print("    python3 tests/test_api.py tts '你好世界'")
        print("    python3 tests/test_api.py image 'a red dragon' 20")
        print("    python3 tests/test_api.py bgm 'epic battle music'")
        print("    python3 tests/test_api.py video /files/images/xxx.png")
        print("    python3 tests/test_api.py synth /files/videos/v.mp4 /files/audio/a.mp3")
        print("    python3 tests/test_api.py all")
        print("─"*60)
        sys.exit(0)

    cmd = args[0].lower()
    extra = args[1:]

    if cmd not in _COMMANDS:
        print(f"❌ 未知命令 '{cmd}'，可用命令：{', '.join(_COMMANDS)}")
        sys.exit(1)

    fn, desc, _ = _COMMANDS[cmd]
    print(f"\n→ 执行：{desc}")
    fn(*extra)
