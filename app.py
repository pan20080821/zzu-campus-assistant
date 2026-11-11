import streamlit as st
import os
import glob
import json
import requests
import folium
import streamlit_folium as stf
from volcenginesdkarkruntime import Ark

# folium 默认从 cdn.jsdelivr.net 加载 leaflet，该 CDN 在当前网络被重置（ERR_CONNECTION_RESET），
# 改用可达的 unpkg / cdnjs / code.jquery；仅用于图标旋转(spin)的 rotate CSS 不可达且本项目未用，移除
folium.folium._default_js = folium.folium.Map.default_js = [
    ("leaflet", "https://unpkg.com/leaflet@1.9.3/dist/leaflet.js"),
    ("jquery", "https://code.jquery.com/jquery-3.7.1.min.js"),
    ("bootstrap", "https://unpkg.com/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js"),
    ("awesome_markers", "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js"),
]
folium.folium._default_css = folium.folium.Map.default_css = [
    ("leaflet_css", "https://unpkg.com/leaflet@1.9.3/dist/leaflet.css"),
    ("bootstrap_css", "https://unpkg.com/bootstrap@5.2.2/dist/css/bootstrap.min.css"),
    ("glyphicons_css", "https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css"),
    ("awesome_markers_font_css", "https://unpkg.com/@fortawesome/fontawesome-free@6.2.0/css/all.min.css"),
    ("awesome_markers_css", "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css"),
]

# ========== 配置区 ==========
def _secret(name):
    """读取密钥：优先环境变量（本地运行），其次 Streamlit secrets（云端部署）。"""
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return None


ARK_API_KEY = _secret("ARK_API_KEY")
MODEL_ID = "ep-m-20261029193914-q8dl9"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_PATH = os.path.join(BASE_DIR, "knowledge_cleaned")  # 读取AI整理后的干净知识库
AMAP_API_KEY = _secret("AMAP_API_KEY")  # 高德Web服务Key：有则用高德步行（贴合底图），无则回退OSRM
# ============================

theme_config = {
    "郑大深蓝": {"header": "#405492", "button": "#405492", "hover": "#2e3b6b"},
    "清新浅蓝": {"header": "#639cd9", "button": "#639cd9", "hover": "#4b7cb3"},
    "薄荷绿": {"header": "#58b792", "button": "#58b792", "hover": "#3f8c6e"},
    "活力橘色": {"header": "#f28c38", "button": "#f28c38", "hover": "#d47222"},
}

quick_questions = [
    "柳园电费怎么交",
    "图书馆开放时间",
    "校园卡补办流程",
    "食堂营业时间",
    "校医院在哪"
]

# 高频问题硬缓存，秒出答案，零错误
hot_answer_map = {
    "柳园电费怎么交": """【卡片】
🔹 项目：柳园宿舍电费
🔹 缴费入口：郑大校园服务小程序
🔹 操作步骤：
1. 打开小程序 → 宿舍水电
2. 绑定宿舍（园区+楼栋+房间）
3. 输入金额充值
🔹 提示：23:00后无法充值""",
    "图书馆开放时间": """【卡片】
🔹 项目：主图书馆开放时间
🔹 周一至周五：08:00–22:00
🔹 周六、周日：08:30–22:00
🔹 提示：节假日会临时调整，以馆内通知为准""",
    "校园卡补办流程": """【卡片】
🔹 项目：校园卡补办
🔹 线上：郑大校园服务小程序挂失+预约补办
🔹 线下：行政楼卡务中心
🔹 费用：工本费20元
🔹 取卡：3个工作日后领取""",
    "食堂营业时间": """【卡片】
🔹 项目：各园区食堂
🔹 早餐：07:00–08:30
🔹 午餐：11:00–13:00
🔹 晚餐：17:00–19:00
🔹 夜宵：部分食堂20:00–21:30""",
    "校医院在哪": """【卡片】
🔹 项目：校医院
🔹 位置：主校区南侧，菊园附近
🔹 门诊时间：工作日 08:30–11:30，14:30–17:30
🔹 急诊：24小时值班"""
}

st.set_page_config(
    page_title="郑事通",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="auto"
)

# 初始化变量
if "selected_theme" not in st.session_state:
    st.session_state.selected_theme = "郑大深蓝"
if "quick_prompt" not in st.session_state:
    st.session_state.quick_prompt = ""
if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.messages.append({
        "role": "assistant",
        "content": "您好，欢迎使用郑事通郑州大学校园智能服务助手。您可咨询校园生活、教务办事、后勤保障等相关问题，我将为您提供准确的信息指引。"
    })

# 校园待办看板：自动识别提问中的事务，先询问再由用户确认加入
if "todos" not in st.session_state:
    st.session_state.todos = []
if "todo_id_counter" not in st.session_state:
    st.session_state.todo_id_counter = 0
if "pending_todo" not in st.session_state:
    st.session_state.pending_todo = None  # 待用户确认的候选待办
# 地图导航：起点、终点、已处理点击
if "map_origin" not in st.session_state:
    st.session_state.map_origin = None
if "map_dest" not in st.session_state:
    st.session_state.map_dest = None
if "map_click_handled" not in st.session_state:
    st.session_state.map_click_handled = None


def change_theme():
    st.session_state.selected_theme = st.session_state.theme_select


# ========== 知识库检索函数（优化版）==========
@st.cache_data(show_spinner=False)
def load_all_docs():
    docs = {}
    if not os.path.exists(KNOWLEDGE_PATH):
        os.makedirs(KNOWLEDGE_PATH)
        return docs
    for file_path in glob.glob(os.path.join(KNOWLEDGE_PATH, "*.txt")):
        filename = os.path.basename(file_path).replace(".txt", "")
        with open(file_path, "r", encoding="utf-8") as f:
            docs[filename] = f.read().strip()
    return docs


@st.cache_resource(show_spinner=False)
def get_ark_client():
    return Ark(api_key=ARK_API_KEY, base_url="https://ark.cn-beijing.volces.com/api/v3")


# 文档专属词：用户问题里没出现这些词时，对应文档降权，避免泛问题被特定场景文档抢走
EXCLUSIVE_TERMS = {
    "图书馆静音舱预约": ["静音舱", "面试舱", "研讨间", "舱"],
    # 问"到火车站怎么走"是出行路线，不是购票优惠；不含这些专属词时让学生证文档降权
    "学生证与火车票优惠": ["学生证", "优惠", "学生票", "12306", "资质", "充磁", "区间", "补办", "乘车"],
}

# 保研领域触发词：只有问题里出现这些词，保研推免文档才参与竞争；
# 否则"管理/规划/书法/旅游"等通用词会让保研文档误抢非保研问题
BAOYAN_TRIGGERS = ("保研", "推免", "免研", "免试", "推荐免试")

# ========== 校园待办自动提取（规则模板，确定性、零成本、不依赖大模型）==========
# 问题里同时包含 match 全部关键词时，自动生成对应待办卡片
TODO_TEMPLATES = [
    {"match": ["校园卡", "补办"], "title": "补办校园卡", "material": "身份证",
     "place": "行政楼卡务中心", "duration": "约10分钟", "note": "先在小程序线上挂失，工本费20元"},
    {"match": ["校园卡", "挂失"], "title": "挂失校园卡", "material": "无",
     "place": "郑大校园服务小程序", "duration": "约2分钟", "note": "先线上挂失，再按指引补办"},
    {"match": ["电费"], "title": "缴纳宿舍电费", "material": "无",
     "place": "郑大校园服务小程序", "duration": "约3分钟", "note": "绑定宿舍后充值，23:00后无法充值"},
    {"match": ["保研"], "title": "准备保研推免材料", "material": "成绩单、外语证明、竞赛论文",
     "place": "本学院教务办", "duration": "数天", "note": "关注绩点排名与外语门槛，以当年学院通知为准"},
    {"match": ["转专业"], "title": "提交转专业申请", "material": "申请表、成绩单",
     "place": "转入学院教务办", "duration": "按通知", "note": "转出不限制、转入有考核，试读2周"},
    {"match": ["图书馆", "预约"], "title": "预约图书馆座位", "material": "无",
     "place": "图书馆预约系统", "duration": "约1分钟", "note": "选好楼层时段，按时签到"},
    {"match": ["学生证", "补办"], "title": "补办学生证", "material": "审批表、一寸照片",
     "place": "学生处事务管理科", "duration": "按学期批次", "note": "先交学院审核，集中办理"},
    {"match": ["医保"], "title": "办理医保/报销", "material": "医保卡、票据",
     "place": "校医院", "duration": "按流程", "note": "转诊需提前审批，以校医院通知为准"},
    {"match": ["体测", "免测"], "title": "申请体测免测", "material": "医院证明",
     "place": "体育学院/体测部门", "duration": "按受理批次", "note": "官方未明确材料，提前咨询"},
    {"match": ["快递"], "title": "取快递", "material": "取件码",
     "place": "柳园/松园菜鸟驿站", "duration": "约10分钟", "note": "营业时间9:00—20:00，自助出库"},
]


def detect_todo_candidate(prompt):
    """识别问题是否为待办事件，返回候选待办（不写入）；非待办或已有同标题未完成项则返回 None"""
    for t in TODO_TEMPLATES:
        if all(k in prompt for k in t["match"]):
            # 已有同标题且未完成的待办，不再重复询问
            if any(x["title"] == t["title"] and not x["done"] for x in st.session_state.todos):
                return None
            return {k: v for k, v in t.items() if k != "match"}
    return None


def commit_todo(todo):
    """用户确认后，把候选待办正式写入列表"""
    st.session_state.todo_id_counter += 1
    todo["id"] = st.session_state.todo_id_counter
    todo["done"] = False
    st.session_state.todos.append(todo)


def llm_detect_todo(prompt, client):
    """规则没命中时用大模型兜底：判断是否待办，返回候选（不写入），非待办或重复返回 None"""
    sp = (
        "判断用户问题是否为一个需要办理的具体待办事务（含线上/线下办事、申请、补办、缴费、预约、报销等动作）。"
        "若是，只输出JSON：{\"title\":\"\",\"material\":\"\",\"place\":\"\",\"duration\":\"\",\"note\":\"\"}；"
        "若只是咨询、概念、方法、闲聊而非待办，只输出{}。"
        "每个字段用简短词组，不超过15字，不写长句、不加括号解释；不确定的字段填“未明确”。不要输出JSON以外的内容。"
    )
    try:
        r = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "system", "content": sp}, {"role": "user", "content": prompt}],
            max_tokens=200, temperature=0,
            extra_body={"thinking": {"type": "disabled"}},
        )
        text = r.choices[0].message.content.strip()
        # 兼容模型用 ```json 代码块包裹的情况
        if text.startswith("```"):
            text = text.strip("`").replace("json", "", 1).strip()
        data = json.loads(text)
    except Exception:
        return None
    if not data or "title" not in data or not data["title"]:
        return None
    if any(x["title"] == data["title"] and not x["done"] for x in st.session_state.todos):
        return None
    return {
        "title": data["title"],
        "material": data.get("material") or "未明确",
        "place": data.get("place") or "未明确",
        "duration": data.get("duration") or "未明确",
        "note": data.get("note") or "未明确",
        "source": "llm",
    }

# ========== 地图导航：点击选起点/终点，OSRM 绘制真实道路路线 ==========
# 郑州大学主校区（高新区科学大道100号）初始视角
ZZU_CENTER = (34.817, 113.535)
AMAP_TILES = ("https://webrd0{s}.is.autonavi.com/appmaptile?"
              "lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}")


def osrm_route(origin, dest):
    """用 OSRM 真实道路几何；返回(折线坐标, 道路距离, 步行时长)。公共OSRM时长按汽车，
    故步行时长按 1.33m/s（约4.8km/h）由真实距离重算"""
    url = ("https://router.project-osrm.org/route/v1/foot/"
           f"{origin[1]},{origin[0]};{dest[1]},{dest[0]}"
           "?overview=full&geometries=geojson")
    try:
        data = requests.get(url, timeout=10).json()
        if data.get("code") != "Ok":
            return None
        rt = data["routes"][0]
        coords = [(p[1], p[0]) for p in rt["geometry"]["coordinates"]]  # GeoJSON[lng,lat]→[lat,lng]
        dist = rt["distance"]
        return coords, dist, dist / 1.33
    except Exception:
        return None


def amap_walk_route(origin, dest):
    """高德步行规划：路线与高德底图同源、精准贴合，步行时长为高德真实值。
    返回(折线坐标, 距离, 步行时长)"""
    params = {
        "key": AMAP_API_KEY,
        "origin": f"{origin[1]},{origin[0]}",
        "destination": f"{dest[1]},{dest[0]}",
    }
    try:
        data = requests.get("https://restapi.amap.com/v3/direction/walking",
                            params=params, timeout=10).json()
        if data.get("status") != "1":
            return None
        path = data["route"]["paths"][0]
        coords = []
        for step in path["steps"]:
            for item in step["polyline"].split(";"):
                lng, lat = item.split(",")
                coords.append((float(lat), float(lng)))
        return coords, int(path["distance"]), int(path["duration"])
    except Exception:
        return None


def get_walk_route(origin, dest):
    """统一入口：有高德Key优先用高德（与底图同源、贴合），否则回退OSRM。
    返回(坐标, 距离, 时长, 来源)，全部失败返回 None"""
    if AMAP_API_KEY:
        res = amap_walk_route(origin, dest)
        if res:
            return res[0], res[1], res[2], "高德"
    res = osrm_route(origin, dest)
    if res:
        return res[0], res[1], res[2], "OSRM"
    return None


def build_campus_map():
    """根据当前起点/终点构建 folium 地图（高德底图 + 标记 + 路线）"""
    m = folium.Map(location=list(ZZU_CENTER), zoom_start=16, tiles=None, control_scale=True)
    folium.TileLayer(tiles=AMAP_TILES, attr="© 高德地图",
                     subdomains="1234", name="高德矢量").add_to(m)
    o, d = st.session_state.map_origin, st.session_state.map_dest
    if o:
        folium.Marker(o, tooltip="起点",
                      icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(m)
    if d:
        folium.Marker(d, tooltip="终点",
                      icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(m)
    if o and d:
        res = get_walk_route(o, d)
        if res:
            coords = res[0]
            folium.PolyLine(coords, color="#2f6fed", weight=5, tooltip="步行路线").add_to(m)
    return m


def search_knowledge(query, docs):
    if not docs:
        return ""
    # 用 2 字滑窗(bigram)提取关键词，不依赖分词库；单字会导致"食堂"被拆成"食/堂"匹配不到
    # 含疑问代词(怎/么/如/何/什)的 bigram 不携带主题信息，过滤掉，避免"怎么"误命中无关文档
    stop_chars = set("的了吗呢是在我你他她它这那都也就和与及或把被让向从到为很太非常个们之而于怎如何么什")
    keywords = set()
    for i in range(len(query) - 1):
        bg = query[i:i+2]
        if any(c in stop_chars for c in bg):
            continue
        keywords.add(bg)

    # 自动计算每个关键词的文档频率(df)：在很多文档出现的词区分度低（IDF思想），
    # 无需手工维护通用词表，避免"管理/时间/学生/大学"等通用词累计误命中
    n_docs = len(docs)
    doc_freq = {kw: sum(1 for nm, ct in docs.items() if kw in nm or kw in ct) for kw in keywords}
    # 低区分度词：出现在 ≥10% 文档里的通用词，命中只给基础分，不参与主题判定
    low_specificity = {kw for kw in keywords if doc_freq[kw] / n_docs >= 0.10}

    scores = {}
    for name, content in docs.items():
        # 提取"相关问题"行（人工整理的常用问法入口），命中给高权重
        faq_line = ""
        for line in content.splitlines():
            if line.startswith("相关问题"):
                faq_line = line
                break
        score = 0
        for kw in keywords:
            if kw in low_specificity:
                # 通用词无论命中文件名/faq/正文都只给1分，无法靠通用词堆砌过阈值
                if kw in name or kw in faq_line or kw in content:
                    score += 1
            else:
                if kw in name:
                    score += 10  # 高区分度主题词命中文件名
                if kw in faq_line:
                    score += 8   # 命中常用问题入口
                elif kw in content:
                    score += 3   # 普通正文命中，避免用词不一致时漏检
        scores[name] = score

    # 完整实体前缀匹配：若问题以文档名开头的核心词起头，从长到短给一次奖励。
    # 用于打破 bigram 子串平局，例如"书法学院"含"法学院"，但只有"法学院"文档以"法学院"开头；
    # 要求问题"以该前缀开头"，避免"保研要求…"这类通用词在句尾造成的误奖励
    for name in scores:
        for L in range(len(name), 2, -1):
            if query.startswith(name[:L]):
                scores[name] += 6 + L
                break

    # 专属词降权：用户没提"静音舱"等词时，静音舱文档不抢通用"图书馆预约"问题
    for name in scores:
        terms = EXCLUSIVE_TERMS.get(name)
        if terms and not any(t in query for t in terms):
            scores[name] -= 15

    # 保研领域门槛：保研推免文档只回答保研问题；问题不含保研触发词时统一降权，
    # 避免"管理/规划/书法/旅游"等通用词让保研文档误抢日常问题（学习方法经验文档不纳入）
    if not any(t in query for t in BAOYAN_TRIGGERS):
        for name in scores:
            if name.endswith("保研推免要求") or name == "保研要求暂未公开学院清单":
                scores[name] -= 15

    sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    # 阈值过滤：分数不够直接认为无相关资料，不强行匹配
    if sorted_docs and sorted_docs[0][1] >= 5:
        return docs[sorted_docs[0][0]], sorted_docs[0][1]
    return "", 0


# 侧边栏
with st.sidebar:
    st.title("⚙️ 设置")
    st.markdown("### 郑事通")
    st.caption("郑大百事通，服务零距离。")
    st.divider()
    st.selectbox(
        "🎨 选择主题配色",
        list(theme_config.keys()),
        index=list(theme_config.keys()).index(st.session_state.selected_theme),
        key="theme_select",
        on_change=change_theme
    )
    st.divider()
    if st.button("🗑️ 清空全部对话", use_container_width=True):
        st.session_state.messages = []
        st.session_state.quick_prompt = ""
        st.rerun()
    st.divider()

    # 常用网站直达（可折叠，点击在新标签页打开）
    with st.expander("🔗 常用网站直达", expanded=False):
        useful_sites = {
            "校内系统": [
                ("郑大官网", "https://www.zzu.edu.cn"),
                ("信息门户", "https://info.s.zzu.edu.cn"),
                ("教务部", "http://www5.zzu.edu.cn/jwc"),
                ("图书馆", "https://library.zzu.edu.cn"),
                ("研究生院", "https://gs.zzu.edu.cn"),
                ("招生网", "https://ao.zzu.edu.cn"),
                ("网上办事大厅", "https://ehall.v.zzu.edu.cn"),
            ],
            "学习平台": [
                ("学习通", "https://www.chaoxing.com"),
                ("智慧树", "https://www.zhihuishu.com"),
                ("U校园", "https://u.unipus.cn"),
                ("中国大学MOOC", "https://www.icourse163.org"),
            ],
            "学术与升学": [
                ("中国知网", "https://www.cnki.net"),
                ("学信网", "https://www.chsi.com.cn"),
                ("研招网", "https://yz.chsi.com.cn"),
                ("四六级报名", "http://cet.neea.edu.cn"),
            ],
        }
        for group, items in useful_sites.items():
            st.caption(group)
            for name, url in items:
                st.markdown(f"[{name}]({url})")

    with st.expander("ℹ️ 关于郑事通", expanded=False):
        st.markdown("“郑事通”是郑州大学校园智能服务助手，依托人工智能技术整合校园生活、教务教学、后勤保障、办事指引等多场景信息资源，为全体在校师生提供精准、高效的信息咨询与事务导办服务，助力提升校园公共服务效率与师生生活体验。")

    st.divider()
    st.caption("基于火山方舟 + 本地知识库搭建")

c = theme_config[st.session_state.selected_theme]
st.markdown(f"""
<style>
    .stApp {{
        background-color: #ffffff;
        color: #111111;
    }}
    [data-testid="stHeader"] {{
        background-color: {c["header"]};
    }}
    .stButton>button {{
        background-color: {c["button"]};
        color: white;
    }}
    .stButton>button:hover {{
        background-color: {c["hover"]};
    }}
</style>
""", unsafe_allow_html=True)

st.title("🎓 郑事通")
st.markdown("*郑大百事通，服务零距离。*")

# 顶部待办看板（折叠栏）：✓标记完成、🗑️删除
active_count = sum(1 for t in st.session_state.todos if not t["done"])
with st.expander(f"📋 我的待办（{active_count} 项待完成）", expanded=active_count > 0):
    if not st.session_state.todos:
        st.caption("还没有待办。提问时我会自动帮你整理需要办的事。")
    for todo in st.session_state.todos:
        col_main, col_done, col_del = st.columns([0.72, 0.14, 0.14])
        with col_main:
            if todo["done"]:
                st.markdown(f"~~{todo['title']}~~ ✅")
            else:
                st.markdown(f"**{todo['title']}**")
                st.caption(
                    f"材料：{todo['material']}　|　地点：{todo['place']}　|　"
                    f"耗时：{todo['duration']}　|　注意：{todo['note']}"
                )
        with col_done:
            done_label = "✓" if not todo["done"] else "↩"
            if st.button(done_label, key=f"toggle_{todo['id']}", use_container_width=True):
                todo["done"] = not todo["done"]
                st.rerun()
        with col_del:
            if st.button("🗑️", key=f"delete_{todo['id']}", use_container_width=True):
                st.session_state.todos = [
                    x for x in st.session_state.todos if x["id"] != todo["id"]
                ]
                st.rerun()

# 地图导航折叠栏：点击选起点和终点，自动绘制真实道路路线
with st.expander("🗺️ 校园地图导航（点击选点，自动绘制路线）", expanded=False):
    st.caption("先点地图选起点，再点选终点；两点齐全后自动绘制步行路线。")
    if st.button("🔄 重新选点", key="map_reset"):
        st.session_state.map_origin = None
        st.session_state.map_dest = None
        st.session_state.map_click_handled = None
        st.rerun()

    map_data = stf.st_folium(
        build_campus_map(), key="campus_map",
        returned_objects=["last_clicked"],
        use_container_width=True, height=480,
    )
    last_clicked = map_data["last_clicked"]
    if last_clicked is not None:
        # streamlit-folium 0.27 返回 dict {"lat":..,"lng":..}，兼容对象形式
        lat = last_clicked["lat"] if isinstance(last_clicked, dict) else last_clicked.lat
        lng = last_clicked["lng"] if isinstance(last_clicked, dict) else last_clicked.lng
        pt = (round(lat, 6), round(lng, 6))
        if pt != st.session_state.map_click_handled:
            st.session_state.map_click_handled = pt
            if st.session_state.map_origin is None:
                st.session_state.map_origin = pt
            elif st.session_state.map_dest is None:
                st.session_state.map_dest = pt
            else:
                # 两点已存在时再点，视为重新开始
                st.session_state.map_origin = pt
                st.session_state.map_dest = None
            st.rerun()

    # 路线信息
    if st.session_state.map_origin and st.session_state.map_dest:
        res = get_walk_route(st.session_state.map_origin, st.session_state.map_dest)
        if res:
            _, dist, sec, source = res
            if source == "高德":
                st.caption(f"🚶 步行距离约 {dist:.0f} 米，预计步行 {sec/60:.0f} 分钟"
                           "（高德步行路线，贴合实际道路）")
            else:
                st.caption(f"🚶 道路距离约 {dist:.0f} 米，步行约 {sec/60:.0f} 分钟"
                           "（未配置高德Key，时长按4.8km/h估算，路线可能不贴合）")

st.markdown("💡 快捷提问（点击直接出答案）：")
cols = st.columns(len(quick_questions))
for i, q in enumerate(quick_questions):
    if cols[i].button(q):
        st.session_state.quick_prompt = q

# 渲染历史消息（统一用聊天气泡，去掉【卡片】标记）
for msg in st.session_state.messages:
    content = msg["content"]
    if msg["role"] == "assistant" and content.startswith("【卡片】"):
        content = content.replace("【卡片】", "")
    with st.chat_message(msg["role"]):
        st.markdown(content)

# 待办确认条：识别到候选待办时，先询问用户是否加入
if st.session_state.pending_todo:
    p = st.session_state.pending_todo
    with st.chat_message("assistant"):
        st.markdown(f"📌 我识别到这可能是一个待办事项「**{p['title']}**」，要加入待办列表吗？")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ 加入待办", key="confirm_add_todo", use_container_width=True):
                commit_todo(p)
                st.session_state.pending_todo = None
                st.rerun()
        with col_no:
            if st.button("❌ 暂不加入", key="confirm_skip_todo", use_container_width=True):
                st.session_state.pending_todo = None
                st.rerun()

user_input = st.chat_input("请输入你的问题")
prompt = st.session_state.quick_prompt if st.session_state.quick_prompt else user_input

if prompt:
    # 识别是否为待办事件；命中则先放入候选，稍后询问用户确认（不直接加入）
    candidate = detect_todo_candidate(prompt)
    if candidate:
        st.session_state.pending_todo = candidate
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 优先走硬缓存（秒出，无思考）
    if prompt in hot_answer_map:
        reply = hot_answer_map[prompt]
        st.session_state.messages.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.markdown(reply.replace("【卡片】", ""))
    else:
        # 非缓存问题走知识库
        docs = load_all_docs()
        reference, top_score = search_knowledge(prompt, docs)

        # 强命中：直接本地回答，不调 LLM，秒回（文档本身已结构化清洗）
        if top_score >= 8:
            reply = reference
            if reply.startswith("相关问题"):
                reply = reply.split("\n", 1)[1].strip()
            st.session_state.messages.append({"role": "assistant", "content": reply})
            with st.chat_message("assistant"):
                st.markdown(reply)
        else:
            with st.chat_message("assistant"):
                if not ARK_API_KEY:
                    st.error("❌ 未配置 ARK_API_KEY，本地知识库又没有该问题的答案。")
                    st.markdown("请到火山方舟控制台获取 API Key。本地运行设环境变量，云端部署写进 `.streamlit/secrets.toml`：")
                    st.code('ARK_API_KEY = "你的Key"')
                else:
                    # 双模式：有本地资料优先用资料；无资料则放开，让大模型用通用知识快速回答
                    if reference:
                        system_prompt = """你是郑事通，郑州大学校园智能服务助手。
规则：
1. 优先依据下方【参考资料】回答，资料未覆盖的细节可结合常识适当补充，但不要编造与资料冲突的信息；
2. 精简分点，不加客套话。

【参考资料】
""" + reference[:800]
                        waiting = "🔍 已检索到本地资料，正在整理回答…"
                    else:
                        system_prompt = """你是郑事通，郑州大学校园智能服务助手。
本地知识库暂未收录该问题，请直接基于你的知识快速回答：
1. 精简分点，给出可操作的建议；
2. 涉及具体数字、政策、时间等可能变动的信息，提醒以官方最新通知为准；
3. 不加客套话。
"""
                        waiting = "🤔 知识库未收录，正在用通用知识快速回答…"

                    client = get_ark_client()
                    # 规则没命中时，用大模型兜底识别待办（本地强命中问题不走到这里，保持秒回）
                    if candidate is None:
                        llm_candidate = llm_detect_todo(prompt, client)
                        if llm_candidate:
                            st.session_state.pending_todo = llm_candidate
                            candidate = llm_candidate  # 供末尾判断是否重绘
                    # 首字返回前先给提示，避免界面空白像卡住
                    output_box = st.empty()
                    output_box.markdown(waiting)
                    # 只发最近 2 轮历史，减少输入 token、加快首字
                    recent_history = st.session_state.messages[-4:]
                    stream = client.chat.completions.create(
                        model=MODEL_ID,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            *recent_history
                        ],
                        stream=True,
                        temperature=0.3,
                        max_tokens=300,
                        extra_body={"thinking": {"type": "disabled"}}  # 关闭深度思考，首字从数十秒降到约1秒
                    )
                    answer_text = ""
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        if delta.content:
                            answer_text += delta.content
                            output_box.markdown(answer_text)
                    reply = answer_text
                    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.quick_prompt = ""
    # 识别到候选待办时重绘一次，让聊天区的确认条正确显示
    if candidate:
        st.rerun()

