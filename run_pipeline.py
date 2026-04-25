#!/usr/bin/env python3
"""
Pipeline Runner - 通过 FastAPI 调用完成从小说生成到视频生成的整个流程

所有 AI 服务（LLM、Image、TTS、Video）均通过 FastAPI 网关调用。
默认 provider 配置：
  - LLM: NVIDIA NIM (nemotron-3-super-120b-a12b)
  - Image: ComfyUI + Z-Image-Turbo (640x480)
  - Video: ComfyUI + Wan2.2 I2V (640x480)
  - TTS: Edge TTS

用法:
    python run_pipeline.py --project-id "test_project" --chapter 1
    python run_pipeline.py --project-id "test_project" --all-chapters
    python run_pipeline.py --project-id "test_project" --phase 1
"""

import asyncio
import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

import httpx

sys.path.insert(0, str(Path(__file__).parent))


# ── FastAPI 客户端 ─────────────────────────────────────────────────────────────

class APIClient:
    """FastAPI 服务客户端"""

    def __init__(self, base_url: str = "http://localhost:9000"):
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=300.0)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── LLM ────────────────────────────────────────────────────────────────────

    async def llm_generate(self, messages: List[Dict], max_tokens: int = 4096,
                          temperature: float = 0.7, stream: bool = False) -> Dict:
        """调用 LLM 生成文本"""
        client = await self._get_client()
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        resp = await client.post("/llm/generate", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def llm_stream(self, messages: List[Dict], max_tokens: int = 4096,
                        temperature: float = 0.7) -> str:
        """调用 LLM 流式生成文本"""
        client = await self._get_client()
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        async with client.stream("POST", "/llm/stream", json=payload) as resp:
            resp.raise_for_status()
            full_content = ""
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    if line == "data: [DONE]":
                        break
                    try:
                        content = json.loads(line[6:])
                        if content:
                            full_content += content
                    except json.JSONDecodeError:
                        continue
            return full_content

    async def llm_health(self) -> bool:
        """检查 LLM 健康状态"""
        try:
            client = await self._get_client()
            resp = await client.get("/llm/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ── Image ─────────────────────────────────────────────────────────────────

    async def image_generate(self, prompt: str, negative_prompt: str = "",
                            width: int = 640, height: int = 480,
                            steps: int = 20, cfg: float = 7.0,
                            seed: int = -1, model: str = "",
                            workflow: str = "") -> str:
        """提交图像生成任务，返回 task_id"""
        client = await self._get_client()
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
            "seed": seed,
            "model": model,
            "workflow": workflow,
        }
        resp = await client.post("/image/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["task_id"]

    async def image_wait(self, task_id: str, poll_interval: float = 2.0,
                        max_wait: float = 300.0) -> Dict:
        """等待图像生成任务完成"""
        client = await self._get_client()
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            resp = await client.get(f"/image/tasks/{task_id}")
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "completed":
                return data["result"]
            elif data["status"] == "failed":
                raise RuntimeError(f"Image generation failed: {data.get('error', 'unknown')}")
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"Image generation timed out after {max_wait}s")

    async def image_health(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/image/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ── Video ─────────────────────────────────────────────────────────────────

    async def video_generate(self, image_url: str, prompt: str = "",
                            motion_prompt: str = "", negative_prompt: str = "",
                            num_frames: int = 81, fps: int = 24,
                            width: int = 640, height: int = 480,
                            seed: int = -1, model: str = "",
                            workflow: str = "") -> str:
        """提交视频生成任务，返回 task_id"""
        client = await self._get_client()
        payload = {
            "image_url": image_url,
            "prompt": prompt,
            "motion_prompt": motion_prompt,
            "negative_prompt": negative_prompt,
            "num_frames": num_frames,
            "fps": fps,
            "width": width,
            "height": height,
            "seed": seed,
            "model": model,
            "workflow": workflow,
        }
        resp = await client.post("/video/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["task_id"]

    async def video_wait(self, task_id: str, poll_interval: float = 5.0,
                        max_wait: float = 600.0) -> Dict:
        """等待视频生成任务完成"""
        client = await self._get_client()
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            resp = await client.get(f"/video/tasks/{task_id}")
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "completed":
                return data["result"]
            elif data["status"] == "failed":
                raise RuntimeError(f"Video generation failed: {data.get('error', 'unknown')}")
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"Video generation timed out after {max_wait}s")

    async def video_health(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/video/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ── TTS ────────────────────────────────────────────────────────────────────

    async def tts_synthesize(self, text: str, voice: str = "zh-CN-XiaoxiaoNeural",
                            rate: str = "+0%", pitch: str = "+0Hz",
                            format: str = "mp3") -> str:
        """提交 TTS 合成任务，返回 task_id"""
        client = await self._get_client()
        payload = {
            "text": text,
            "voice": voice,
            "rate": rate,
            "pitch": pitch,
            "format": format,
        }
        resp = await client.post("/tts/synthesize", json=payload)
        resp.raise_for_status()
        return resp.json()["task_id"]

    async def tts_wait(self, task_id: str, poll_interval: float = 2.0,
                       max_wait: float = 120.0) -> Dict:
        """等待 TTS 任务完成"""
        client = await self._get_client()
        start = time.monotonic()
        while time.monotonic() - start < max_wait:
            resp = await client.get(f"/tasks/{task_id}")
            resp.raise_for_status()
            data = resp.json()
            if data["status"] == "completed":
                return data["result"]
            elif data["status"] == "failed":
                raise RuntimeError(f"TTS synthesis failed: {data.get('error', 'unknown')}")
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"TTS synthesis timed out after {max_wait}s")

    async def tts_health(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/tts/health")
            return resp.status_code == 200
        except Exception:
            return False

    # ── Health ─────────────────────────────────────────────────────────────────

    async def full_health(self) -> Dict:
        """获取所有后端健康状态"""
        client = await self._get_client()
        resp = await client.get("/health")
        resp.raise_for_status()
        return resp.json()


# ── Pipeline ───────────────────────────────────────────────────────────────────

class PipelineRunner:
    """通过 FastAPI 调用完成整个流水线"""

    def __init__(self, project_id: str, api_url: str = "http://localhost:9000"):
        self.project_id = project_id
        self.api = APIClient(api_url)
        self.output_dir = Path("outputs") / project_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def close(self):
        await self.api.close()

    async def check_health(self) -> bool:
        """检查所有服务健康状态"""
        print("\n🔍 检查服务健康状态...")
        try:
            health = await self.api.full_health()
            all_ok = health.get("healthy", False)
            print(f"   整体状态: {'✅ 健康' if all_ok else '⚠️  部分异常'}")
            for b in health.get("backends", []):
                status = "✅" if b["healthy"] else "❌"
                print(f"   {status} {b['name']}")
            return True
        except Exception as e:
            print(f"   ⚠️  无法获取健康状态: {e}")
            return False

    async def run(
        self,
        chapter_number: Optional[int] = None,
        all_chapters: bool = False,
        phase: Optional[int] = None,
        force_regenerate: bool = False,
    ):
        """运行流水线"""
        print("\n" + "=" * 70)
        print("🎬 AI Novel Video Pipeline 启动")
        print("=" * 70)
        print(f"项目ID: {self.project_id}")
        print(f"API: {self.api.base_url}")
        print(f"阶段: {phase or '全部'}")
        print("=" * 70)

        # 健康检查
        await self.check_health()

        # Phase 1: 小说生成 (LLM)
        if phase is None or phase == 1:
            await self._run_phase1_novel()

        # Phase 2: 图像 + TTS + 视频
        if phase is None or phase == 2:
            chapters = [chapter_number] if chapter_number else list(range(1, 4))  # 默认3章
            if all_chapters:
                chapters = list(range(1, 4))
            for ch in chapters:
                await self._run_phase2_media(ch)

        print("\n" + "=" * 70)
        print("✅ 流水线执行完成!")
        print("=" * 70)

    async def _run_phase1_novel(self):
        """Phase 1: 使用 LLM 生成小说"""
        print("\n" + "-" * 60)
        print("📝 Phase 1: 小说生成 (NVIDIA NIM LLM)")
        print("-" * 60)

        # 系统提示词
        system_prompt = """你是一个专业的小说作家，擅长创作修仙、玄幻类型的故事。
请根据用户需求生成小说内容，要求：
1. 情节紧凑，高潮迭起
2. 角色鲜明，对话生动
3. 场景描写丰富，画面感强
4. 每章3000-5000字"""

        # 用户请求
        user_request = f"""为项目 {self.project_id} 创作一个修仙小说章节。

要求：
- 主角获得神秘传承
- 有战斗场面
- 有成长和突破
- 结尾有悬念

请生成第一章内容。"""

        print("   📡 调用 NVIDIA NIM LLM...")
        try:
            result = await self.api.llm_generate(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_request},
                ],
                max_tokens=8000,
                temperature=0.7,
            )
            content = result.get("content", "")
            print(f"   ✅ 生成文本 {len(content)} 字符")

            # 保存到文件
            novel_path = self.output_dir / "novel" / f"chapter_1.txt"
            novel_path.parent.mkdir(parents=True, exist_ok=True)
            novel_path.write_text(content, encoding="utf-8")
            print(f"   💾 已保存: {novel_path}")

            return content
        except Exception as e:
            print(f"   ❌ LLM 调用失败: {e}")
            return ""

    async def _run_phase2_media(self, chapter_number: int):
        """Phase 2: 生成图像、TTS、Video"""
        print("\n" + "-" * 60)
        print(f"🎬 Phase 2: 媒体生成 (第 {chapter_number} 章)")
        print("-" * 60)

        # 加载章节内容
        chapter_path = self.output_dir / "novel" / f"chapter_{chapter_number}.txt"
        if not chapter_path.exists():
            print(f"   ⚠️  章节文件不存在: {chapter_path}")
            return

        chapter_content = chapter_path.read_text(encoding="utf-8")
        print(f"   📖 加载章节内容: {len(chapter_content)} 字符")

        # 1. 生成关键帧图像
        print("\n   🎨 Step 1: 生成关键帧图像...")
        await self._generate_keyframes(chapter_number, chapter_content)

        # 2. 生成 TTS 音频
        print("\n   🔊 Step 2: 生成 TTS 音频...")
        await self._generate_tts_audio(chapter_number, chapter_content)

        # 3. 生成视频
        print("\n   🎬 Step 3: 生成视频...")
        await self._generate_videos(chapter_number)

    async def _generate_keyframes(self, chapter_number: int, content: str):
        """生成关键帧图像"""
        # 提取场景描述（简化处理，实际应该用 LLM 分析）
        scenes = [
            f"玄幻修仙场景，神秘山洞，光芒照耀，云雾缭绕",
            f"战斗场景，主角施展法术，能量爆发，特效光效",
            f"修炼场景，打坐冥想，灵气汇聚，星空背景",
        ]

        for i, scene_prompt in enumerate(scenes):
            print(f"   生成图像 {i+1}/{len(scenes)}...")
            try:
                task_id = await self.api.image_generate(
                    prompt=scene_prompt,
                    negative_prompt="blurry, low quality, bad anatomy",
                    width=640,
                    height=480,
                    steps=20,
                )
                result = await self.api.image_wait(task_id)
                images = result.get("images", [])
                if images:
                    print(f"      ✅ 生成: {images[0].get('url', 'N/A')}")
            except Exception as e:
                print(f"      ❌ 失败: {e}")

    async def _generate_tts_audio(self, chapter_number: int, content: str):
        """生成 TTS 音频"""
        # 简单分段处理
        paragraphs = content.split("\n\n")[:5]  # 只处理前5段

        for i, para in enumerate(paragraphs):
            if len(para) < 20:
                continue
            print(f"   生成音频 {i+1}/{len(paragraphs)}...")
            try:
                task_id = await self.api.tts_synthesize(
                    text=para[:500],  # 限制长度
                    voice="zh-CN-XiaoxiaoNeural",
                    rate="+0%",
                )
                result = await self.api.tts_wait(task_id)
                audio_url = result.get("audio_url", "")
                if audio_url:
                    print(f"      ✅ 生成: {audio_url}")
            except Exception as e:
                print(f"      ❌ 失败: {e}")

    async def _generate_videos(self, chapter_number: int):
        """生成视频（从已生成的图像）"""
        # 图像保存在全局 outputs/images/ 目录
        images_dir = Path("outputs") / "images"
        if not images_dir.exists():
            print("   ⚠️  无图像文件，跳过视频生成")
            return

        image_files = list(images_dir.glob("*.png")) + list(images_dir.glob("*.jpg"))
        if not image_files:
            print("   ⚠️  无图像文件，跳过视频生成")
            return

        print(f"   找到 {len(image_files)} 张图像")

        for img_file in image_files[:2]:  # 只处理前2张
            print(f"   生成视频: {img_file.name}...")
            try:
                # 图像路径转为 /files/ URL（outputs/images/ -> /files/outputs/images/）
                image_url = f"/files/outputs/images/{img_file.name}"

                task_id = await self.api.video_generate(
                    image_url=image_url,
                    prompt="cinematic smooth motion",
                    motion_prompt="slow movement, high quality",
                    num_frames=81,
                    fps=24,
                    width=640,
                    height=480,
                )
                result = await self.api.video_wait(task_id, max_wait=600)
                video_url = result.get("video_url", "")
                if video_url:
                    print(f"      ✅ 生成: {video_url}")
            except Exception as e:
                print(f"      ❌ 失败: {e}")


# ── Main ────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="AI Novel Video Pipeline - 通过 FastAPI 调用完成整个流程",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
默认 Provider 配置:
  - LLM: NVIDIA NIM (nemotron-3-super-120b-a12b)
  - Image: ComfyUI + Z-Image-Turbo (640x480)
  - Video: ComfyUI + Wan2.2 I2V (640x480)
  - TTS: Edge TTS

示例:
  # 运行完整流水线
  python run_pipeline.py --project-id "test_project"

  # 只运行 Phase 1 (小说生成)
  python run_pipeline.py --project-id "test_project" --phase 1

  # 指定章节
  python run_pipeline.py --project-id "test_project" --chapter 1
        """,
    )

    parser.add_argument("--project-id", "-p", type=str, required=True, help="项目ID")
    parser.add_argument("--api-url", "-u", type=str, default="http://localhost:9000",
                       help="FastAPI 服务地址")
    parser.add_argument("--chapter", "-c", type=int, help="指定章节号")
    parser.add_argument("--all-chapters", "-a", action="store_true", help="运行所有章节")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3],
                       help="指定阶段 (1=小说, 2=媒体, 3=合成)")
    parser.add_argument("--force", "-f", action="store_true", help="强制重新生成")

    args = parser.parse_args()

    runner = PipelineRunner(args.project_id, args.api_url)

    try:
        await runner.run(
            chapter_number=args.chapter,
            all_chapters=args.all_chapters,
            phase=args.phase,
            force_regenerate=args.force,
        )
    except KeyboardInterrupt:
        print("\n⚠️  用户中断执行")
    except Exception as e:
        print(f"\n❌ 执行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await runner.close()


if __name__ == "__main__":
    asyncio.run(main())