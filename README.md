# 郑事通 · 郑州大学校园智能服务助手

基于 Streamlit + 火山方舟大模型 + 本地知识库（轻量 RAG）的校园问答助手。

## 功能

- 校园生活、后勤、教务、办事指引问答，答案附来源文档
- 待办进度看板、校园地图（高德步行导航）、常用网站入口
- 知识库 86 篇，采用 bigram + IDF 检索，命中不足时回退大模型生成

## 部署到 Streamlit Cloud

1. 新建 app，选本仓库、入口文件 `app.py`
2. 在 Settings → Secrets 里填入：

```toml
ARK_API_KEY = "你的火山方舟 API Key"
AMAP_API_KEY = "你的高德 Key"
```

3. Deploy

## 本地运行

```powershell
pip install -r requirements.txt
$env:ARK_API_KEY="你的 Key"; $env:AMAP_API_KEY="你的 Key"
python -m streamlit run app.py
```

`郑事通_单文件版.py` 是知识库内嵌的单文件版本，只需该文件即可运行（`tools/build_singlefile.py` 生成）。