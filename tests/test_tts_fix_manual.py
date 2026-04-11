import asyncio
from pathlib import Path
import sys
import os

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from stage3_audio.tts_engine import TTSEngine, EdgeTTSEngine

async def test_tts_fix():
    print("Test 1: Verify EdgeTTSEngine with neutral rate (+0%)")
    engine = TTSEngine()
    edge_engine = EdgeTTSEngine({})
    
    test_text = "这是一个简单的测试文本。"
    test_voice = "zh-CN-XiaoxiaoNeural"
    output_path = Path("test_neutral.mp3")
    
    try:
        # Test neutral rate
        duration = await edge_engine.generate(test_text, test_voice, output_path, rate="+0%")
        print(f"✅ EdgeTTS success! Duration: {duration:.2f}s")
    except Exception as e:
        print(f"❌ EdgeTTS failed: {e}")
    finally:
        if output_path.exists():
            output_path.unlink()

    print("\nTest 2: Verify Mock Audio validity")
    mock_output = Path("test_mock.mp3")
    try:
        await engine._create_mock_audio(mock_output, "some text")
        print(f"✅ Mock audio created at {mock_output}")
        
        # Verify with ffmpeg
        check_cmd = f"ffmpeg -i {mock_output} -f null - 2>&1"
        result = os.popen(check_cmd).read()
        
        if "Invalid argument" in result or "Error" in result:
             print(f"❌ Mock audio is INVALID for ffmpeg:\n{result}")
        else:
             print("✅ Mock audio is VALID for ffmpeg.")
             
    except Exception as e:
        print(f"❌ Mock audio test failed with error: {e}")
    finally:
        if mock_output.exists():
            mock_output.unlink()

if __name__ == "__main__":
    asyncio.run(test_tts_fix())
