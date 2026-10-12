import socket
import urllib.parse

# 8장의 방명록 서버. 브라우저와 별개의 프로그램이다.
# 실행: pytk server.py  →  브라우저에서 http://localhost:8000/

ENTRIES = ["Pavel was here"]


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

    status, body = do_request(method, url, headers, body)

    response = "HTTP/1.0 {}\r\n".format(status)
    response += "Content-Length: {}\r\n".format(len(body.encode("utf8")))
    response += "\r\n" + body
    conx.send(response.encode("utf8"))
    conx.close()


def do_request(method, url, headers, body):
    if method == "GET" and url == "/":
        return "200 OK", show_comments()
    elif method == "POST" and url == "/add":
        params = form_decode(body)
        return "200 OK", add_entry(params)
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


def show_comments():
    out = "<!doctype html>"
    for entry in ENTRIES:
        out += "<p>" + entry + "</p>"
    out += "<form action=add method=post>"
    out += "<p><input name=guest></p>"
    out += "<p><button>Sign the book!</button></p>"
    out += "</form>"
    return out


def add_entry(params):
    if "guest" in params:
        ENTRIES.append(params["guest"])
    return show_comments()


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
