import gzip
import socket
import ssl
import time


# pytk canvas.py http://browser.engineering
# python canvas.py http://browser.engineering


# pytk canvas.py --tree "file://$PWD/test.html"
class URL:
    # (scheme, host, port) -> (socket, makefile 객체)
    connections = {}
    # "scheme://host:port/path" -> (body, expiry). expiry가 None이면 무기한
    cache = {}

    def __init__(self, url):
        self.view_source = False
        if url.startswith("view-source:"):
            self.view_source = True
            url = url[len("view-source:") :]

        if url.startswith("data:"):
            self.scheme = "data"
            # data:text/html,Hello 이런 타입으로 들어오게 됨.
            self.mediatype, self.data = url[len("data:") :].split(",", 1)
            return

        self.scheme, url = url.split("://", 1)
        assert self.scheme in ["http", "https", "file"]

        if self.scheme == "file":
            self.path = url
            return

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443

        if "/" not in url:
            url = url + "/"
        self.host, url = url.split("/", 1)
        self.path = "/" + url
        if ":" in self.host:
            self.host, self.port = self.host.split(":", 1)
            self.port = int(self.port)

    def request(self, max_redirects=10):
        if self.scheme == "data":
            return self.data

        if self.scheme == "file":
            return self.request_file()

        cache_key = "{}://{}:{}{}".format(self.scheme, self.host, self.port, self.path)
        now = time.time()
        if cache_key in URL.cache:
            cached_body, expiry = URL.cache[cache_key]
            if expiry is None or now < expiry:
                return cached_body
            del URL.cache[cache_key]

        key = (self.scheme, self.host, self.port)
        if key in URL.connections:
            s, response = URL.connections[key]
        else:
            s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            s.connect((self.host, self.port))
            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            response = s.makefile("rb")
            URL.connections[key] = (s, response)

        headers = {
            "Host": self.host,
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip",
            #  Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 크롬은 매우 복잡
            "User-Agent": "baesh",
        }
        request = "GET {} HTTP/1.1\r\n".format(self.path)
        for header, value in headers.items():
            request += "{}: {}\r\n".format(header, value)
        request += "\r\n"
        s.send(request.encode("utf-8"))

        status_line = response.readline().decode("utf-8")
        version, status, explanation = status_line.split(" ", 2)
        response_headers = {}
        while True:
            line = response.readline().decode("utf-8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        if response_headers.get("transfer-encoding") == "chunked":
            body_bytes = self.read_chunked(response)
        elif "content-length" in response_headers:
            content_length = int(response_headers["content-length"])
            body_bytes = response.read(content_length)
        else:
            body_bytes = b""

        if response_headers.get("content-encoding") == "gzip":
            body_bytes = gzip.decompress(body_bytes)

        body = body_bytes.decode("utf-8")

        if status.startswith("3") and "location" in response_headers:
            if max_redirects <= 0:
                raise Exception("Too many redirects")
            location = response_headers["location"]
            if "://" not in location:
                location = "{}://{}:{}{}".format(
                    self.scheme, self.host, self.port, location
                )
            result_body = URL(location).request(max_redirects - 1)
        else:
            result_body = body

        if status in ["200", "301", "404"]:
            should_cache = True
            expiry = None
            if "cache-control" in response_headers:
                directives = response_headers["cache-control"].lower().split(",")
                for directive in directives:
                    directive = directive.strip()
                    if directive.startswith("max-age="):
                        expiry = now + int(directive[len("max-age=") :])
                    else:
                        # no-store를 포함해, max-age 외의 값이면 캐시하지 않음
                        should_cache = False
            if should_cache:
                URL.cache[cache_key] = (result_body, expiry)

        return result_body

    def read_chunked(self, response):
        data = b""
        while True:
            size_line = response.readline().decode("utf-8")
            # "1a; 확장자" 형태일 수 있어 세미콜론 앞부분만 사용
            size = int(size_line.split(";")[0].strip(), 16)
            if size == 0:
                response.readline()  # 마지막 청크 뒤의 빈 줄(\r\n)
                break
            data += response.read(size)
            response.readline()  # 각 청크 데이터 뒤의 \r\n
        return data

    def request_file(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()


class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []  # 텍스트는 항상 잎(leaf)이지만 Element와 형태를 맞춘다
        self.parent = parent

    def __repr__(self):
        return repr(self.text)


class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.attributes = attributes
        self.children = []
        self.parent = parent

    def __repr__(self):
        return "<" + self.tag + ">"


def print_tree(node, indent=0):
    # 들여쓰기로 트리 구조를 눈으로 확인하는 디버깅용 도구
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


class HTMLParser:
    # 여는 태그만 쓰고 닫지 않는 태그들(명세 용어로는 "void" 태그)
    SELF_CLOSING_TAGS = [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]

    # head 안에 들어가야 하는 태그들. body를 암시적으로 열지 head를 열지 판단하는 데 쓴다
    HEAD_TAGS = [
        "base",
        "basefont",
        "bgsound",
        "noscript",
        "link",
        "meta",
        "title",
        "style",
        "script",
    ]

    def __init__(self, body):
        self.body = body
        # 아직 닫히지 않은 태그들을 부모 -> 자식 순서로 담는다.
        # [0]은 트리의 뿌리, [-1]은 가장 최근에 열린 태그(= 새 노드가 붙을 자리).
        self.unfinished = []

    def parse(self):
        # 3장의 lex와 글자 훑는 방식은 같지만, 토큰 리스트를 만드는 대신
        # add_text/add_tag가 트리에 노드를 붙인다.
        text = ""
        in_tag = False
        i = 0
        while i < len(self.body):
            c = self.body[i]
            # 4-3: 스크립트 본문에서는 </script>만 태그로 인정하고, 그 외의 < 와 >는
            # 자바스크립트의 비교 연산자이므로 전부 그냥 글자로 취급한다.
            if (
                not in_tag
                and bool(self.unfinished)
                and self.unfinished[-1].tag == "script"
                and not self.body[i : i + len("</script")].casefold() == "</script"
            ):
                text += c
            elif c == "<":
                in_tag = True
                if text:
                    self.add_text(text)
                text = ""
            elif c == ">":
                in_tag = False
                self.add_tag(text)
                text = ""
            else:
                text += c
            i += 1
        if not in_tag and text:
            self.add_text(text)
        return self.finish()

    def get_attributes(self, text):
        # 값 안에 공백이 없다고 가정하고 공백으로 잘라 태그 이름과 속성들을 분리한다
        parts = text.split()
        tag = parts[0].casefold()  # HTML 태그/속성 이름은 대소문자를 구분하지 않는다
        attributes = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                # 따옴표로 감싼 값이면 따옴표를 벗겨낸다
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.casefold()] = value
            else:
                # <input disabled>처럼 값이 생략된 속성은 빈 문자열로 둔다
                attributes[attrpair.casefold()] = ""
        return tag, attributes

    def in_pre(self):
        # 3-5 이식: pre 안에서는 공백과 빈 줄 자체가 의미를 가지므로 버리면 안 된다
        return any(node.tag == "pre" for node in self.unfinished)

    def add_text(self, text):
        # 태그 사이의 줄바꿈/들여쓰기까지 노드로 만들면 트리가 지저분해지므로 버린다.
        # (아직 트리가 없는 doctype 직후의 개행에서 터지는 것도 이걸로 막힌다.)
        if text.isspace() and not self.in_pre():
            return
        self.implicit_tags(None)
        parent = self.unfinished[-1]
        node = Text(text, parent)
        parent.children.append(node)

    def add_tag(self, tag):
        tag, attributes = self.get_attributes(tag)
        # <!doctype html>이나 주석은 요소가 아니므로 그냥 버린다
        if tag.startswith("!"):
            return
        self.implicit_tags(tag)
        if tag.startswith("/"):
            # 문서 마지막 닫는 태그는 붙일 부모가 없으므로 finish()에 맡긴다
            if len(self.unfinished) == 1:
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        elif tag in self.SELF_CLOSING_TAGS:
            # 닫는 태그가 오지 않으므로 열자마자 바로 부모에 붙여 완성시킨다
            parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            # 첫 태그는 부모가 없다(None)
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def implicit_tags(self, tag):
        # html/head/body는 생략 가능하므로, 빠진 것이 있으면 대신 넣어준다.
        # 한 번에 하나씩만 넣기 때문에 여러 개가 빠진 경우를 위해 반복한다.
        while True:
            open_tags = [node.tag for node in self.unfinished]
            if open_tags == [] and tag != "html":
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif (
                open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS
            ):
                # head에 들어갈 수 없는 태그가 나왔으면 head가 끝난 것으로 본다
                self.add_tag("/head")
            else:
                break

    def finish(self):
        # 빈 문서라도 html/body는 있어야 하므로 한 번 채워준다
        if not self.unfinished:
            self.implicit_tags(None)
        # 닫히지 않고 남은 태그들을 전부 부모에 붙여 트리를 완성한다
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()


def show(body):
    print_tree(HTMLParser(body).parse())


def load(url):
    body = url.request()
    if url.view_source:
        print(body, end="")
    else:
        show(body)


if __name__ == "__main__":
    import os
    import sys

    if len(sys.argv) > 1:
        load(URL(sys.argv[1]))
    else:
        default_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "test.html"
        )
        load(URL("file://" + default_path))
