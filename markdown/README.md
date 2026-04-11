# AI爽文小说创作平台 - 快速开始指南

## 📖 项目简介

本项目是一个端到端的AI驱动内容创作平台，能够自动完成从小说构思到动态漫画视频的全流程生产。

## 🗂️ 项目结构

```
ai-novel-platform/
├── architecture/          # 架构设计文档
│   ├── 01-overview.md     # 总架构概览
│   ├── 02-story-engine.md # 小说生成引擎
│   ├── 03-visual-engine.md# 视觉生成引擎
│   ├── 04-audio-engine.md # 音频生成引擎
│   ├── 05-workflow-engine.md # 工作流编排
│   └── 06-deployment.md   # 部署架构
├── modules/               # 各模块实现代码
├── docs/                  # 详细文档
└── deployment/            # 部署配置
```

## 🎯 核心功能

| 模块 | 功能 | 技术亮点 |
|------|------|----------|
| **小说生成引擎** | 自动创作爽文小说 | 爽点设计系统、节奏控制、质量评估 |
| **视觉生成引擎** | 生成动态漫画 | 角色一致性、图生视频、镜头运动 |
| **音频生成引擎** | 生成配音和配乐 | 声音克隆、情感合成、音画同步 |
| **工作流引擎** | 编排自动化流程 | 状态机、错误恢复、资源调度 |

## 🚀 快速开始

### 1. 环境要求

- **Kubernetes 1.25+**
- **NVIDIA GPU Operator**
- **Helm 3.0+**

### 2. 部署步骤

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/ai-novel-platform.git
cd ai-novel-platform

# 2. 安装依赖
helm dependency update deployment/helm

# 3. 部署基础设施
kubectl apply -f deployment/k8s/namespace.yaml
helm install ai-novel-infra deployment/helm/infra

# 4. 部署应用
helm install ai-novel-app deployment/helm/app \
  --set gpu.enabled=true \
  --set gpu.count=8

# 5. 验证部署
kubectl get pods -n ai-novel
kubectl get svc -n ai-novel
```

### 3. API使用示例

```python
import requests

# 1. 创建小说生产任务
response = requests.post("https://api.ai-novel.com/v1/novels", json={
    "title": "重生之我是系统流大师",
    "genre": "玄幻",
    "style": "爽文",
    "total_chapters": 100,
    "target_word_count": 300000,
    "shuangdian_intensity": "high",
    "visual_production": True,
    "audio_production": True
})

task_id = response.json()["task_id"]
print(f"Task created: {task_id}")

# 2. 查询进度
while True:
    status = requests.get(f"https://api.ai-novel.com/v1/tasks/{task_id}").json()
    print(f"Progress: {status['progress']}% - {status['message']}")
    
    if status["state"] == "completed":
        break
    elif status["state"] == "error":
        print(f"Error: {status['error']}")
        break
    
    time.sleep(10)

# 3. 下载结果
result = requests.get(f"https://api.ai-novel.com/v1/novels/{task_id}/download").json()
print(f"Download links:")
print(f"  Novel JSON: {result['novel_json']}")
print(f"  Videos: {result['videos']}")
```

## 📚 架构文档导航

| 文档 | 内容 | 适用读者 |
|------|------|----------|
| [01-overview.md](./01-overview.md) | 整体架构总览 | 所有人 |
| [02-story-engine.md](./02-story-engine.md) | 小说生成详细设计 | 算法工程师 |
| [03-visual-engine.md](./03-visual-engine.md) | 视觉生成详细设计 | 视觉工程师 |
| [04-audio-engine.md](./04-audio-engine.md) | 音频生成详细设计 | 音频工程师 |
| [05-workflow-engine.md](./05-workflow-engine.md) | 工作流编排设计 | 系统工程师 |
| [06-deployment.md](./06-deployment.md) | 部署和运维 | 运维工程师 |

## 🤝 贡献指南

我们欢迎社区贡献！请阅读 [CONTRIBUTING.md](../docs/CONTRIBUTING.md) 了解如何参与。

## 📄 许可证

本项目采用 [MIT License](../LICENSE) 开源。

## 📞 联系方式

- **项目主页**: https://github.com/your-org/ai-novel-platform
- **文档中心**: https://docs.ai-novel.com
- **社区论坛**: https://forum.ai-novel.com
- **技术支持**: support@ai-novel.com

---

**让AI为每一个故事注入灵魂 ✨**
