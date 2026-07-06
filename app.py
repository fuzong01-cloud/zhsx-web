from flask import Flask, redirect, render_template, request, url_for

app = Flask(__name__)

users = {
    "admin": "123456",
    "student": "123456",
}


@app.route("/", methods=["GET", "POST"])
def login():
    message = ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username in users and users[username] == password:
            return redirect(url_for("success", username=username))

        message = "用户名或密码错误，请重新输入。"

    return render_template("login.html", message=message)


@app.route("/success")
def success():
    username = request.args.get("username", "")
    return render_template("success.html", username=username)


@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""
    message_type = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not username or not password:
            message = "用户名和密码不能为空。"
            message_type = "error"
        elif password != confirm_password:
            message = "两次输入的密码不一致。"
            message_type = "error"
        elif username in users:
            message = "该用户名已存在，请更换用户名。"
            message_type = "error"
        else:
            users[username] = password
            message = "注册成功，请返回登录界面。"
            message_type = "success"

    return render_template("register.html", message=message, message_type=message_type)


if __name__ == "__main__":
    app.run(debug=True)
