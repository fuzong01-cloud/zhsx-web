import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "flask-login-home-demo"

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def load_local_env():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))


load_local_env()

NLE_DEVICE_ID = "1516155"
NLE_API_HOST = "http://api.nlecloud.com"
SENSOR_HISTORY = []
HISTORY_LIMIT = 10
KIMI_API_BASE = os.environ.get("MOONSHOT_API_BASE", "https://api.moonshot.cn/v1").rstrip("/")
KIMI_MODEL = os.environ.get("KIMI_MODEL", "kimi-k2.6")
KIMI_LOCK = threading.Lock()
AI_HISTORY_LIMIT = 6
AI_CHAT_HISTORY_LIMIT = 12
SERVER_RUN_ID = uuid.uuid4().hex
AI_SESSION_VERSION = "2"

SENSORS = [
    {"name": "当前温度", "tag": "currentTemp", "unit": "℃", "icon": "thermometer"},
    {"name": "上限温度", "tag": "upperLimit", "unit": "℃", "icon": "thermometer"},
    {"name": "下限温度", "tag": "lowerLimit", "unit": "℃", "icon": "thermometer"},
    {"name": "温度报警", "tag": "alarm", "unit": "", "icon": "alarm"},
    {"name": "大气压力", "tag": "m_pressure", "unit": "hPa", "icon": "gauge"},
    {"name": "二氧化碳", "tag": "m_co2", "unit": "ppm", "icon": "cloud"},
    {"name": "风速", "tag": "m_wind_speed", "unit": "m/s", "icon": "wind"},
]

DEVICE_COMMANDS = {
    "actuator": "actuator",
}

THRESHOLD_COMMANDS = {
    "upperLimit": "upperLimit",
    "lowerLimit": "lowerLimit",
}

USERS = {
    "15600002034": {
        "password": "123456",
        "name": "王鹏飞",
        "student_id": "202320741241",
        "avatar": "https://images.unsplash.com/photo-1501004318641-b39e6451bec6?auto=format&fit=crop&w=900&q=80",
    }
}


@app.context_processor
def inject_current_user():
    username = session.get("username")
    return {"current_user": USERS.get(username) if username else None}


def is_valid_username(username):
    return username.isdigit() and len(username) == 11


def allowed_photo(filename):
    suffix = Path(filename).suffix.lower()
    return suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def request_json(url, method="GET", token="", body=None, bearer_token="", timeout=8):
    headers = {}
    data = None

    if token:
        headers["AccessToken"] = token
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, f"HTTP {exc.code}: {detail}"
    except URLError:
        return None, "无法连接云平台"
    except TimeoutError:
        return None, "请求超时"
    except json.JSONDecodeError:
        return None, "云平台返回数据格式异常"


def login_nlecloud(account, password):
    data, error = request_json(
        f"{NLE_API_HOST}/Users/Login",
        method="POST",
        body={"Account": account, "Password": password, "IsRememberMe": True},
    )

    if error:
        return "", error

    result = data.get("ResultObj") or {}
    token = result.get("AccessToken")

    if not token:
        return "", data.get("Msg", "云平台登录失败，未返回 AccessToken")

    return token, ""


def get_sensor_value(api_tag):
    token = session.get("nle_access_token")
    if not token:
        return {"ok": False, "value": "--", "error": "请先完成云平台授权"}

    params = urlencode({"deviceId": NLE_DEVICE_ID, "apiTag": api_tag})
    url = f"{NLE_API_HOST}/devices/{NLE_DEVICE_ID}/Sensors/{api_tag}?{params}"
    data, error = request_json(url, token=token)

    if error:
        return {"ok": False, "value": "--", "error": error}

    result = data.get("ResultObj")
    if not isinstance(result, dict):
        return {"ok": False, "value": "--", "error": data.get("Msg", "未获取到传感器数据")}

    value = result.get("Value")
    if value is None:
        value = result.get("value", "--")

    return {"ok": True, "value": value, "error": ""}


def send_device_command(api_tag, value):
    token = session.get("nle_access_token")
    if not token:
        return False, "请先完成云平台授权"

    url = f"{NLE_API_HOST}/Cmds?deviceId={NLE_DEVICE_ID}&apiTag={api_tag}"
    body = {"deviceId": NLE_DEVICE_ID, "apiTag": api_tag, "value": value}
    data, error = request_json(url, method="POST", token=token, body=body)
    if error:
        return False, error

    if data.get("Status") == 0 or data.get("ResultObj") is not None:
        return True, ""

    return False, data.get("Msg", "云平台未确认命令执行成功")


def format_number(value):
    return f"{value:g}"


def get_latest_thresholds():
    latest = SENSOR_HISTORY[-1]["values"] if SENSOR_HISTORY else {}
    return numeric_value(latest.get("upperLimit")), numeric_value(latest.get("lowerLimit"))


def apply_threshold_command(upper=None, lower=None):
    current_upper, current_lower = get_latest_thresholds()
    upper = current_upper if upper is None else upper
    lower = current_lower if lower is None else lower

    if upper is None or lower is None:
        return False, "请同时说明上限和下限，例如：把上限调到 30，下限调到 20。"

    if lower >= upper:
        return False, "下限必须小于上限。"

    if lower < -40 or upper > 100:
        return False, "温度阈值范围应在 -40 到 100 ℃之间。"

    upper_ok, upper_error = send_device_command(THRESHOLD_COMMANDS["upperLimit"], upper)
    if not upper_ok:
        return False, f"上限更新失败：{upper_error}"

    lower_ok, lower_error = send_device_command(THRESHOLD_COMMANDS["lowerLimit"], lower)
    if not lower_ok:
        return False, f"下限更新失败：{lower_error}"

    return True, f"已执行：上限 {format_number(upper)} ℃，下限 {format_number(lower)} ℃。"


def parse_control_command(message):
    text = message.replace(" ", "")
    if not text:
        return None

    if re.search(r"(打开|开启|启动).*(设备|开关|执行器|actuator)", text, re.IGNORECASE):
        return {"type": "device_switch", "enabled": True}

    if re.search(r"(关闭|关掉|停止).*(设备|开关|执行器|actuator)", text, re.IGNORECASE):
        return {"type": "device_switch", "enabled": False}

    if not re.search(r"(阈值|上限|下限|温度)", text):
        return None

    upper = None
    lower = None
    upper_match = re.search(r"上限(?:温度)?(?:调到|设置为|设为|改为|=|：|:)?(-?\d+(?:\.\d+)?)", text)
    lower_match = re.search(r"下限(?:温度)?(?:调到|设置为|设为|改为|=|：|:)?(-?\d+(?:\.\d+)?)", text)

    if upper_match:
        upper = float(upper_match.group(1))
    if lower_match:
        lower = float(lower_match.group(1))

    if upper is None and lower is None:
        both_match = re.search(r"(-?\d+(?:\.\d+)?)[℃度]?(?:到|~|-)(-?\d+(?:\.\d+)?)[℃度]?", text)
        if both_match:
            first = float(both_match.group(1))
            second = float(both_match.group(2))
            lower = min(first, second)
            upper = max(first, second)

    if upper is None and lower is None:
        return None

    return {"type": "thresholds", "upper": upper, "lower": lower}


def extract_json_object(text):
    text = (text or "").strip()
    if not text:
        return None

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def normalize_ai_control_command(data):
    if not isinstance(data, dict):
        return None

    action = data.get("action")
    if action == "none":
        return None

    if action == "set_thresholds":
        upper = numeric_value(data.get("upper"))
        lower = numeric_value(data.get("lower"))
        if upper is None and lower is None:
            return None
        return {"type": "thresholds", "upper": upper, "lower": lower}

    if action == "device_switch":
        enabled = data.get("enabled")
        if isinstance(enabled, bool):
            return {"type": "device_switch", "enabled": enabled}

    return None


def plan_control_command_with_ai(user_message):
    system_prompt = (
        "你是温室控制指令解析器，只输出 JSON，不要输出解释。"
        "你只能返回以下三种动作："
        '{"action":"set_thresholds","upper":数字或null,"lower":数字或null}，'
        '{"action":"device_switch","enabled":true或false}，'
        '{"action":"none"}。'
        "当用户明确或模糊要求调温度阈值时，根据历史数据和常识给出合理上下限；"
        "上限必须大于下限，范围 -40 到 100。"
        "如果用户只是询问、分析、聊天，不要执行，返回 none。"
    )
    current_upper, current_lower = get_latest_thresholds()
    context = (
        f"当前上限={current_upper if current_upper is not None else '未知'}，"
        f"当前下限={current_lower if current_lower is not None else '未知'}。\n"
        f"最近历史：\n{format_history_for_ai()}"
    )
    answer, error = request_kimi(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{context}\n\n用户指令：{user_message}"},
        ]
    )
    if error:
        return None, error

    data = extract_json_object(answer)
    return normalize_ai_control_command(data), ""


def execute_control_command(command):
    if command["type"] == "device_switch":
        ok, error = send_device_command(DEVICE_COMMANDS["actuator"], 1 if command["enabled"] else 0)
        if not ok:
            return False, f"设备控制失败：{error}"
        return True, f"已执行：{'打开' if command['enabled'] else '关闭'}设备。"

    if command["type"] == "thresholds":
        return apply_threshold_command(command.get("upper"), command.get("lower"))

    return False, "暂不支持这个控制指令。"


def build_sensor_data():
    sensor_data = []
    has_error = False

    for sensor in SENSORS:
        result = get_sensor_value(sensor["tag"])
        has_error = has_error or not result["ok"]
        sensor_data.append(
            {
                "name": sensor["name"],
                "tag": sensor["tag"],
                "unit": sensor["unit"],
                "icon": sensor["icon"],
                "value": result["value"],
                "error": result["error"],
            }
        )

    return sensor_data, has_error


def numeric_value(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def append_sensor_history(sensors, updated_at):
    values = {}
    for sensor in sensors:
        value = numeric_value(sensor["value"])
        if value is not None:
            values[sensor["tag"]] = value

    if not values:
        return

    SENSOR_HISTORY.append({"time": updated_at, "values": values})
    del SENSOR_HISTORY[:-HISTORY_LIMIT]


def format_history_for_ai(limit=AI_HISTORY_LIMIT):
    if not SENSOR_HISTORY:
        return "暂无历史记录。"

    labels = {
        "currentTemp": "当前温度",
        "upperLimit": "上限温度",
        "lowerLimit": "下限温度",
        "alarm": "温度报警",
        "m_pressure": "大气压力",
        "m_co2": "二氧化碳",
        "m_wind_speed": "风速",
    }
    lines = []
    for item in SENSOR_HISTORY[-limit:]:
        values = "，".join(
            f"{labels.get(tag, tag)}={value}"
            for tag, value in item["values"].items()
        )
        lines.append(f"{item['time']}：{values}")

    return "\n".join(lines)


def get_ai_chat_history():
    if (
        session.get("ai_server_run_id") != SERVER_RUN_ID
        or session.get("ai_session_version") != AI_SESSION_VERSION
    ):
        session["ai_server_run_id"] = SERVER_RUN_ID
        session["ai_session_version"] = AI_SESSION_VERSION
        session.pop("ai_chat_history", None)
        session.modified = True

    cleaned = []
    for item in session.get("ai_chat_history", []):
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            cleaned.append({"role": role, "content": content})

    if cleaned != session.get("ai_chat_history", []):
        session["ai_chat_history"] = cleaned[-AI_CHAT_HISTORY_LIMIT:]
        session.modified = True

    return cleaned[-AI_CHAT_HISTORY_LIMIT:]


def request_kimi(messages, wait_timeout=15):
    api_key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not api_key:
        return "", "未配置 MOONSHOT_API_KEY 环境变量"

    if not KIMI_LOCK.acquire(timeout=wait_timeout):
        return "", "AI 正在分析上一条请求，请稍后再试"

    try:
        data, error = request_json(
            f"{KIMI_API_BASE}/chat/completions",
            method="POST",
            bearer_token=api_key,
            body={
                "model": KIMI_MODEL,
                "messages": messages,
                "thinking": {"type": "disabled"},
            },
            timeout=35,
        )
    finally:
        KIMI_LOCK.release()

    if error:
        if "rate_limit_reached" in error or "HTTP 429" in error:
            return "", "AI 请求太频繁，请稍后再试"
        return "", error

    choices = data.get("choices") or []
    if not choices:
        return "", data.get("error", {}).get("message", "Kimi 未返回有效回复")

    message = choices[0].get("message") or {}
    return message.get("content", "").strip(), ""

def build_sensor_placeholders():
    return [
        {
            "name": sensor["name"],
            "tag": sensor["tag"],
            "unit": sensor["unit"],
            "icon": sensor["icon"],
            "value": "--",
            "error": "数据加载中",
        }
        for sensor in SENSORS
    ]


def get_cloud_auth_info():
    token = session.get("nle_access_token", "")
    return {
        "authorized": bool(token),
        "account": session.get("nle_account", "--"),
        "device_id": NLE_DEVICE_ID,
        "authorized_at": session.get("nle_authorized_at", "--"),
        "token_preview": f"{token[:6]}...{token[-6:]}" if len(token) > 12 else "--",
    }


@app.route("/", methods=["GET", "POST"])
def login():
    message = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not is_valid_username(username):
            message = "输入不合法：用户名必须是 11 位数字。"
            return render_template("login.html", message=message, username=username)

        user = USERS.get(username)
        if user and user["password"] == password:
            session["username"] = username
            return redirect(url_for("home"))

        message = "输入错误：用户名或密码不正确。"

    return render_template("login.html", message=message)


@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""
    message_type = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        name = request.form.get("name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        photo = request.files.get("photo")

        if not is_valid_username(username):
            message = "用户名必须是 11 位数字。"
            message_type = "error"
        elif username in USERS:
            message = "该用户名已存在，请更换用户名。"
            message_type = "error"
        elif not password or password != confirm_password:
            message = "密码不能为空，且两次输入必须一致。"
            message_type = "error"
        elif not name or not student_id:
            message = "姓名和学号不能为空。"
            message_type = "error"
        elif not photo or not photo.filename:
            message = "注册时必须上传照片。"
            message_type = "error"
        elif not allowed_photo(photo.filename):
            message = "照片格式仅支持 jpg、png、gif、webp。"
            message_type = "error"
        else:
            filename = secure_filename(f"{username}_{photo.filename}")
            photo.save(UPLOAD_DIR / filename)
            USERS[username] = {
                "password": password,
                "name": name,
                "student_id": student_id,
                "avatar": url_for("static", filename=f"uploads/{filename}"),
            }
            message = "注册成功，请返回登录。"
            message_type = "success"

    return render_template("register.html", message=message, message_type=message_type)


@app.route("/home")
def home():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    return render_template(
        "home.html",
        username=username,
        user=USERS[username],
        device_id=NLE_DEVICE_ID,
        sensors=build_sensor_placeholders(),
        has_error=False,
        updated_at="等待加载",
        cloud_authorized=bool(session.get("nle_access_token")),
    )


@app.route("/api/sensors")
def sensor_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    sensors, has_error = build_sensor_data()
    updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_sensor_history(sensors, updated_at)

    return jsonify(
        {
            "ok": True,
            "sensors": sensors,
            "has_error": has_error,
            "updated_at": updated_at,
        }
    )


@app.route("/api/history")
def history_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    return jsonify({"ok": True, "history": SENSOR_HISTORY[-HISTORY_LIMIT:]})


@app.route("/hardware")
def hardware():
    if not session.get("username"):
        return redirect(url_for("login"))

    return render_template("hardware.html", cloud_authorized=bool(session.get("nle_access_token")))


@app.route("/strategy")
def strategy():
    if not session.get("username"):
        return redirect(url_for("login"))

    return render_template("strategy.html", cloud_authorized=bool(session.get("nle_access_token")))


@app.route("/api/device-switch", methods=["POST"])
def device_switch_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    payload = request.get_json(silent=True) or {}
    enabled = bool(payload.get("enabled"))
    ok, error = send_device_command(DEVICE_COMMANDS["actuator"], 1 if enabled else 0)
    return jsonify({"ok": ok, "error": error, "enabled": enabled})


@app.route("/api/thresholds", methods=["POST"])
def thresholds_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    payload = request.get_json(silent=True) or {}
    try:
        upper = float(payload.get("upperLimit"))
        lower = float(payload.get("lowerLimit"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "阈值必须是数字"}), 400

    if lower >= upper:
        return jsonify({"ok": False, "error": "下限必须小于上限"}), 400

    if lower < -40 or upper > 100:
        return jsonify({"ok": False, "error": "温度阈值范围应在 -40 到 100 ℃之间"}), 400

    upper_ok, upper_error = send_device_command(THRESHOLD_COMMANDS["upperLimit"], upper)
    if not upper_ok:
        return jsonify({"ok": False, "error": f"上限更新失败：{upper_error}"}), 502

    lower_ok, lower_error = send_device_command(THRESHOLD_COMMANDS["lowerLimit"], lower)
    if not lower_ok:
        return jsonify({"ok": False, "error": f"下限更新失败：{lower_error}"}), 502

    return jsonify({"ok": True, "upperLimit": upper, "lowerLimit": lower})


@app.route("/api/ai-advice")
def ai_advice_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    messages = [
        {
            "role": "system",
            "content": (
                "你是智慧农业温室监测助手。请根据最近传感器历史数据，"
                "用中文给出简短、可执行的环境建议。回复控制在 80 字以内，"
                "重点关注温度、CO2、风速、报警状态。"
            ),
        },
        {
            "role": "user",
            "content": f"最近 {AI_HISTORY_LIMIT} 次历史记录如下：\n{format_history_for_ai()}",
        },
    ]
    answer, error = request_kimi(messages)
    if error:
        return jsonify({"ok": False, "error": error}), 502

    return jsonify({"ok": True, "advice": answer})


@app.route("/api/ai-chat", methods=["POST"])
def ai_chat_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    payload = request.get_json(silent=True) or {}
    user_message = (payload.get("message") or "").strip()
    if not user_message:
        return jsonify({"ok": False, "error": "请输入问题"}), 400

    chat_history = get_ai_chat_history()
    control_command = parse_control_command(user_message)
    planner_error = ""
    if not control_command:
        control_command, planner_error = plan_control_command_with_ai(user_message)

    if control_command:
        ok, answer = execute_control_command(control_command)
        chat_history.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": answer},
            ]
        )
        session["ai_chat_history"] = chat_history[-AI_CHAT_HISTORY_LIMIT:]
        session["ai_server_run_id"] = SERVER_RUN_ID
        session["ai_session_version"] = AI_SESSION_VERSION
        session.modified = True
        status = 200 if ok else 400
        return jsonify({"ok": ok, "answer": answer, "executed": ok}), status

    messages = [
        {
            "role": "system",
            "content": (
                "你是嵌入在温室环境监测系统里的 AI 助手。"
                "你能读取最近的传感器历史记录，并回答用户关于温室环境、数据趋势、异常原因和处理建议的问题。"
                "如果用户希望你执行调阈值或开关设备，但系统没有执行，请说明需要更明确的控制意图。"
                "回答要具体、简洁，优先结合数据，不要编造没有的数据。回复尽量控制在 120 字以内。"
            ),
        },
        {
            "role": "user",
            "content": f"当前系统最近 {AI_HISTORY_LIMIT} 次历史记录：\n{format_history_for_ai()}",
        },
    ]
    messages.extend(chat_history)
    if planner_error:
        messages.append({"role": "system", "content": f"控制意图解析暂不可用：{planner_error}"})
    messages.append({"role": "user", "content": user_message})

    answer, error = request_kimi(messages)
    if error:
        return jsonify({"ok": False, "error": error}), 502
    if not answer:
        answer, error = request_kimi(messages)
        if error:
            return jsonify({"ok": False, "error": error}), 502
        if not answer:
            return jsonify({"ok": False, "error": "AI 暂时没有生成内容，请换个问题再试"}), 502

    chat_history.extend(
        [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": answer},
        ]
    )
    session["ai_chat_history"] = chat_history[-AI_CHAT_HISTORY_LIMIT:]
    session["ai_server_run_id"] = SERVER_RUN_ID
    session["ai_session_version"] = AI_SESSION_VERSION
    session.modified = True

    return jsonify({"ok": True, "answer": answer})


@app.route("/api/ai-reset", methods=["POST"])
def ai_reset_api():
    if not session.get("username"):
        return jsonify({"ok": False, "error": "未登录"}), 401

    session.pop("ai_chat_history", None)
    session["ai_server_run_id"] = SERVER_RUN_ID
    session["ai_session_version"] = AI_SESSION_VERSION
    session.modified = True
    return jsonify({"ok": True})


@app.route("/profile", methods=["GET", "POST"])
def profile():
    username = session.get("username")
    if not username:
        return redirect(url_for("login"))

    user = USERS[username]
    message = ""
    message_type = ""

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        photo = request.files.get("photo")

        if not name or not student_id:
            message = "姓名和学号不能为空。"
            message_type = "error"
        elif password and password != confirm_password:
            message = "两次输入的密码不一致。"
            message_type = "error"
        elif photo and photo.filename and not allowed_photo(photo.filename):
            message = "照片格式仅支持 jpg、png、gif、webp。"
            message_type = "error"
        else:
            user["name"] = name
            user["student_id"] = student_id

            if password:
                user["password"] = password

            if photo and photo.filename:
                filename = secure_filename(f"{username}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{photo.filename}")
                photo.save(UPLOAD_DIR / filename)
                user["avatar"] = url_for("static", filename=f"uploads/{filename}")

            message = "个人信息修改成功。"
            message_type = "success"

    return render_template(
        "profile.html",
        username=username,
        user=user,
        message=message,
        message_type=message_type,
    )


@app.route("/cloud-login", methods=["GET", "POST"])
def cloud_login():
    if not session.get("username"):
        return redirect(url_for("login"))

    message = "当前已完成云平台授权。" if session.get("nle_access_token") else ""
    message_type = "success" if message else ""
    switch_mode = request.args.get("switch") == "1"

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "").strip()

        if not account or not password:
            message = "请输入云平台账号和密码。"
            message_type = "error"
        else:
            token, error = login_nlecloud(account, password)
            if error:
                message = error
                message_type = "error"
            else:
                session["nle_access_token"] = token
                session["nle_account"] = account
                session["nle_authorized_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message = "云平台授权成功，可以查看传感器数据。"
                message_type = "success"
                switch_mode = False

    return render_template(
        "cloud_login.html",
        message=message,
        message_type=message_type,
        auth_info=get_cloud_auth_info(),
        switch_mode=switch_mode,
    )


@app.route("/cloud-logout")
def cloud_logout():
    session.pop("nle_access_token", None)
    session.pop("nle_account", None)
    session.pop("nle_authorized_at", None)
    return redirect(url_for("cloud_login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
