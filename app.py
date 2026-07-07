import json
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

NLE_DEVICE_ID = "1516155"
NLE_API_HOST = "http://api.nlecloud.com"

SENSORS = [
    {"name": "当前温度", "tag": "currentTemp", "unit": "℃", "icon": "thermometer"},
    {"name": "上限温度", "tag": "upperLimit", "unit": "℃", "icon": "thermometer"},
    {"name": "下限温度", "tag": "lowerLimit", "unit": "℃", "icon": "thermometer"},
    {"name": "温度报警", "tag": "alarm", "unit": "", "icon": "alarm"},
    {"name": "大气压力", "tag": "m_pressure", "unit": "hPa", "icon": "gauge"},
    {"name": "二氧化碳", "tag": "m_co2", "unit": "ppm", "icon": "cloud"},
    {"name": "风速", "tag": "m_wind_speed", "unit": "m/s", "icon": "wind"},
]

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


def request_json(url, method="GET", token="", body=None):
    headers = {}
    data = None

    if token:
        headers["AccessToken"] = token

    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode("utf-8")), ""
    except HTTPError as exc:
        return None, f"HTTP {exc.code}"
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
    return jsonify(
        {
            "ok": True,
            "sensors": sensors,
            "has_error": has_error,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


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
