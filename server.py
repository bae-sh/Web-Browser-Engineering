import html
import random
import socket
import urllib.parse

# 8장의 방명록 서버. 브라우저와 별개의 프로그램이다.
# 실행: pytk server.py  →  브라우저에서 http://localhost:8000/

# 주제 이름 → [(글, 쓴 사람)]
ENTRIES = {"cooking": [], "cars": []}

# 쿠키에 담긴 토큰 → 그 사용자의 세션 데이터. 데이터는 서버에 두고 쿠키에는
# 이 표를 찾을 열쇠만 담는다. 쿠키는 사용자가 마음대로 고칠 수 있기 때문이다.
SESSIONS = {}

LOGINS = {
    "crashoverride": "0cool",
    "cerealkiller": "emmanuel",
}


def handle_connection(conx):
    # 브라우저는 응답을 기다리며 연결을 열어 두므로 "끊길 때까지 읽기"가 안 된다.
    # 그래서 요청 줄과 헤더는 한 줄씩, 본문은 Content-Length만큼 읽는다.
    req = conx.makefile("b")
    reqline = req.readline().decode("utf8")
    method, url, version = reqline.split(" ", 2)
    assert method in ["GET", "POST"]

    headers = {}
    while True:
        line = req.readline().decode("utf8")
        if line == "\r\n":
            break
        header, value = line.split(":", 1)
        headers[header.casefold()] = value.strip()

    if "content-length" in headers:
        length = int(headers["content-length"])
        body = req.read(length).decode("utf8")
    else:
        body = None

    # 처음 온 방문자에게는 새 토큰을 만들어 준다. random.random()은 예측
    # 가능해서 실제 서비스에서는 쓰면 안 된다(secrets 모듈 같은 것을 쓴다).
    token = get_token(headers)
    is_new_visitor = token is None
    if is_new_visitor:
        token = str(random.random())[2:]
    session = SESSIONS.setdefault(token, {})

    status, body = do_request(session, method, url, headers, body)

    response = "HTTP/1.0 {}\r\n".format(status)
    response += "Content-Length: {}\r\n".format(len(body.encode("utf8")))
    if is_new_visitor:
        # 다음 요청부터 이 토큰을 Cookie 헤더에 담아 보내 달라는 뜻.
        # SameSite=Lax: 다른 사이트의 폼이 POST할 때는 이 쿠키를 싣지 말라는 뜻
        response += "Set-Cookie: token={}; SameSite=Lax\r\n".format(token)
    # 이 출처가 아닌 곳의 CSS, JS는 받지 말라고 브라우저에게 알린다
    csp = "default-src http://localhost:8000"
    response += "Content-Security-Policy: {}\r\n".format(csp)
    response += "\r\n" + body
    conx.send(response.encode("utf8"))
    conx.close()


def get_token(headers):
    # Cookie 헤더는 "a=1; token=123; b=2"처럼 여러 쿠키를 담을 수 있다.
    # 같은 localhost를 쓰는 다른 앱의 쿠키가 섞여 올 수도 있어서 쪼개서 찾는다.
    for pair in headers.get("cookie", "").split(";"):
        name, _, value = pair.strip().partition("=")
        if name == "token" and value:
            return value
    return None


def do_request(session, method, url, headers, body):
    parts = [part for part in url.split("/") if part]
    if method == "GET" and not parts:
        return "200 OK", show_topics(session)
    elif method == "POST" and not parts:
        # 로그인 폼은 /로 POST한다
        return do_login(session, form_decode(body))
    elif method == "GET" and parts == ["login"]:
        return "200 OK", login_form(session)
    elif method == "GET" and parts in (["comment.js"], ["comment.css"]):
        with open(parts[0], encoding="utf8") as f:
            return "200 OK", f.read()
    elif method == "POST" and parts == ["new"]:
        return "200 OK", add_topic(session, form_decode(body))
    elif method == "GET" and len(parts) == 1 and parts[0] in ENTRIES:
        return "200 OK", show_topic(session, parts[0])
    elif (
        method == "POST"
        and len(parts) == 2
        and parts[0] in ENTRIES
        and parts[1] == "add"
    ):
        return "200 OK", add_entry(session, form_decode(body), parts[0])
    else:
        return "404 Not Found", not_found(url, method)


def form_decode(body):
    params = {}
    for field in body.split("&"):
        if not field:
            # 이름 있는 input이 없는 폼은 빈 본문을 보낸다
            continue
        name, value = field.split("=", 1)
        # 브라우저에 따라 공백을 +로 보내기도 해서 unquote_plus를 쓴다
        name = urllib.parse.unquote_plus(name)
        value = urllib.parse.unquote_plus(value)
        params[name] = value
    return params


def login_form(session):
    body = "<!doctype html>"
    body += "<form action=/ method=post>"
    body += "<p>Username: <input name=username></p>"
    # 실제 브라우저는 type=password면 글자를 가려 보여 준다(연습문제 10-1)
    body += "<p>Password: <input name=password type=password></p>"
    body += "<p><button>Log in</button></p>"
    body += "</form>"
    return body


def do_login(session, params):
    username = params.get("username")
    password = params.get("password")
    # ==로 비밀번호를 비교하면 다른 글자를 만나는 순간 멈춰서, 걸린 시간으로
    # 비밀번호를 짐작할 수 있다. 실제로는 hmac.compare_digest 같은 걸 쓴다.
    if username in LOGINS and LOGINS[username] == password:
        # 세션은 서버에 있으므로 사용자가 이 값을 직접 조작할 수 없다
        session["user"] = username
        return "200 OK", show_topics(session)
    else:
        out = "<!doctype html>"
        out += "<h1>Invalid password for {}</h1>".format(username)
        return "401 Unauthorized", out


def login_status(session):
    if "user" in session:
        return "<p>Hello, " + session["user"] + "</p>"
    return "<p><a href=/login>Sign in to write in the guest book</a></p>"


def show_topics(session):
    out = "<!doctype html>"
    out += "<h1>Topics</h1>"
    out += login_status(session)
    for topic in ENTRIES:
        out += "<p><a href=/{}>{}</a></p>".format(topic, topic)
    out += "<form action=/new method=post>"
    out += "<p><input name=topic></p>"
    out += "<p><button>New topic</button></p>"
    out += "</form>"
    return out


def show_topic(session, topic):
    out = "<!doctype html>"
    out += "<link rel=stylesheet href=/comment.css>"
    out += "<h1>" + topic + "</h1>"
    out += "<p><a href=/>Home</a></p>"
    out += login_status(session)
    for entry, who in ENTRIES[topic]:
        # 사용자가 쓴 글은 데이터다. <script> 같은 태그가 코드로 해석되지
        # 않도록 &lt; 같은 형태로 바꿔서 내보낸다.
        out += "<p>" + html.escape(entry) + "\n"
        out += "<i>by " + html.escape(who) + "</i></p>"
    if "user" in session:
        # 폼마다 비밀값을 넣어 두고, 제출 때 같은 값이 오는지 확인한다.
        # 다른 사이트의 폼은 이 값을 알 수 없다.
        nonce = str(random.random())[2:]
        session["nonce"] = nonce
        out += "<form action=/{}/add method=post>".format(topic)
        out += "<p><input name=guest></p>"
        # 원래 type=hidden은 안 보여야 하지만 우리 브라우저는 그냥 그린다
        out += "<input name=nonce type=hidden value=" + nonce + ">"
        out += "<p><button>Sign the book!</button></p>"
        out += "</form>"
        # 처음엔 비어 있다가, 글이 너무 길면 comment.js가 경고를 써 넣는다.
        # comment.js는 폼이 있다고 가정하므로 폼과 함께 보낸다.
        out += "<strong></strong>"
        out += "<script src=/comment.js></script>"
    # CSP가 동작하는지 보기 위한 외부 스크립트. 브라우저가 막아야 한다.
    out += "<script src=https://example.com/evil.js></script>"
    return out


def add_entry(session, params, topic):
    # 폼을 숨겼어도 누구나 직접 POST를 보낼 수 있으니 서버에서 다시 확인한다
    nonce_ok = "nonce" in session and session["nonce"] == params.get("nonce")
    if "user" in session and nonce_ok:
        # 자바스크립트를 안 돌리는 브라우저도 있으니 서버에서도 길이를 확인한다
        if "guest" in params and len(params["guest"]) <= 100:
            ENTRIES[topic].append((params["guest"], session["user"]))
    return show_topic(session, topic)


def add_topic(session, params):
    topic = params.get("topic", "")
    if topic not in ENTRIES:
        ENTRIES[topic] = []
    return show_topics(session)


def not_found(url, method):
    out = "<!doctype html>"
    out += "<h1>{} {} not found!</h1>".format(method, url)
    return out


if __name__ == "__main__":
    s = socket.socket(
        family=socket.AF_INET,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    # 서버를 껐다 바로 켜도 같은 포트를 쓸 수 있게 한다
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 8000))
    s.listen()

    while True:
        conx, addr = s.accept()
        handle_connection(conx)
