import gzip
import os
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

    def resolve(self, url):
        # <link href="...">처럼 페이지 안에 적힌 상대 URL을 절대 URL로 바꾼다.
        # 기준점은 self, 즉 그 링크가 적혀 있던 페이지의 URL이다.
        if "://" in url:
            # 이미 스킴이 있는 완전한 URL
            return URL(url)
        if url.startswith("//"):
            # 스킴만 물려받는 형태(//example.com/main.css)
            return URL(self.scheme + ":" + url)
        if not url.startswith("/"):
            # 경로 상대 URL. 현재 경로에서 파일 이름을 떼어낸 디렉터리가 기준이 된다.
            # ".."를 풀어주는 것도 브라우저 몫이라 여기서 직접 처리한다.
            dir, _ = self.path.rsplit("/", 1)
            while url.startswith("../"):
                _, url = url.split("/", 1)
                if "/" in dir:
                    dir, _ = dir.rsplit("/", 1)
            url = dir + "/" + url
        if self.scheme == "file":
            # file 스킴은 host/port가 없으므로 경로만 붙인다
            return URL("file://" + url)
        return URL("{}://{}:{}{}".format(self.scheme, self.host, self.port, url))


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


def tree_to_list(tree, list):
    # 트리를 납작한 목록으로 펴서 "조건에 맞는 노드 전부 찾기"를 쉽게 만든다.
    # children만 있으면 되므로 HTML 트리와 레이아웃 트리 모두에 쓸 수 있다.
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list


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


class CSSParser:
    # 재귀 하강 파서. 작은 파싱 함수를 여러 개 만들고 서로 조합해서 쓴다.
    # 각 함수는 self.i를 전진시키고 자기가 읽어낸 값을 반환한다는 규칙을 지킨다.
    def __init__(self, s):
        self.s = s
        self.i = 0

    def whitespace(self):
        # 공백은 의미가 없으므로 건너뛰기만 하고 반환값이 없다
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self):
        # 속성 이름(letter, -), 숫자(., -), 단위(%), 색(#)에 쓰이는 글자들을 모은다
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                self.i += 1
            else:
                break
        if not (self.i > start):
            # 한 글자도 못 읽었다면 애초에 단어가 있을 자리가 아니었다
            raise Exception("Parsing error: expected word at {}".format(self.i))
        return self.s[start : self.i]

    def literal(self, literal):
        # 콜론, 세미콜론, 중괄호처럼 정해진 글자 하나를 확인하고 넘어간다
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception(
                "Parsing error: expected {!r} at {}".format(literal, self.i)
            )
        self.i += 1

    def ignore_until(self, chars):
        # 파싱에 실패했을 때 회복 지점까지 건너뛴다. 멈춘 글자를 알려주고,
        # 끝까지 못 찾으면 None을 반환한다.
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            self.i += 1
        return None

    def pair(self):
        # "속성: 값" 한 쌍. 작은 파싱 함수들을 조합해 만든다.
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        val = self.word()
        return prop.casefold(), val

    def body(self):
        # 속성-값 쌍의 나열. style 속성 전체와 { } 안쪽 모두 이걸로 읽는다.
        pairs = {}
        while self.i < len(self.s) and self.s[self.i] != "}":
            try:
                prop, val = self.pair()
                pairs[prop] = val
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except Exception:
                # 브라우저는 이해 못하는 선언을 조용히 버리고 나머지를 살린다.
                # 파서를 디버깅할 때는 이 try를 잠깐 지워보면 원인이 드러난다.
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs

    def selector(self):
        # 지원하는 셀렉터는 태그 셀렉터와 후손 셀렉터 두 가지다.
        # "article div p"처럼 이어지면 왼쪽부터 차례로 감싸 나간다.
        out = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            descendant = TagSelector(self.word().casefold())
            out = DescendantSelector(out, descendant)
            self.whitespace()
        return out

    def parse(self):
        # 스타일 시트 = (셀렉터, 본문) 규칙의 나열
        rules = []
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal("{")
                self.whitespace()
                body = self.body()
                self.literal("}")
                rules.append((selector, body))
            except Exception:
                # 셀렉터에서 실패하면 그 규칙 전체를 버리고 다음 } 뒤로 넘어간다
                why = self.ignore_until(["}"])
                if why == "}":
                    self.literal("}")
                    self.whitespace()
                else:
                    break
        return rules


class TagSelector:
    def __init__(self, tag):
        self.tag = tag
        # 캐스케이드 순서를 정하는 값. 구체적인 셀렉터가 이겨야 한다.
        self.priority = 1

    def matches(self, node):
        return isinstance(node, Element) and self.tag == node.tag

    def __repr__(self):
        return self.tag


class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.ancestor = ancestor
        self.descendant = descendant
        # 태그를 많이 나열한 셀렉터일수록 우선순위가 높아진다
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node):
        # 먼저 자기 자신이 오른쪽 셀렉터에 맞는지 보고, 그다음 조상을 거슬러
        # 올라가며 왼쪽 셀렉터에 맞는 조상이 있는지 찾는다.
        if not self.descendant.matches(node):
            return False
        while node.parent:
            if self.ancestor.matches(node.parent):
                return True
            node = node.parent
        return False

    def __repr__(self):
        return "{} {}".format(self.ancestor, self.descendant)


def cascade_priority(rule):
    # sorted()에 넘길 정렬 키. 우선순위가 같으면 sorted가 원래 순서를 유지하므로
    # 파일에 나온 순서가 자동으로 동점 처리 기준이 된다.
    selector, body = rule
    return selector.priority


# 부모에게서 물려받는 속성들과 그 기본값. 배경색은 상속되지 않지만 글자 관련
# 속성은 상속된다. 텍스트 노드는 셀렉터로 고를 수 없으므로 색과 폰트가 이렇게
# 부모에게서 내려와야 한다.
INHERITED_PROPERTIES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "color": "black",
}


def style(node, rules):
    # 여러 출처의 스타일을 우선순위가 낮은 것부터 덮어써 가며 node.style을 만든다.
    node.style = {}

    # 1) 상속. 명시적인 규칙이 이걸 덮어쓸 수 있어야 하므로 가장 먼저 깐다.
    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    # 2) 스타일 시트 규칙. 호출하는 쪽에서 우선순위 순으로 정렬해 넘겨주므로
    #    뒤에 오는 규칙이 앞의 규칙을 덮어쓰면 곧 우선순위대로 적용된 셈이 된다.
    for selector, body in rules:
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    # 3) style 속성. 어떤 스타일 시트보다 우선한다.
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            node.style[property] = value

    # 4) font-size의 %를 픽셀로 환산한다(계산된 스타일).
    #    자식에게 물려주기 전에 해야 <h1 style="font-size:150%"> 안의 글자가
    #    150%를 또 곱해 받는 일이 없다.
    if node.style["font-size"].endswith("%"):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    for child in node.children:
        style(child, rules)


# 브라우저 기본 스타일 시트. 예전에 BlockLayout 코드에 박혀 있던 서식 규칙들이
# 여기로 옮겨졌다. 웹 페이지가 제공하는 스타일 시트가 이보다 우선한다.
DEFAULT_STYLE_SHEET_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "browser.css"
)
with open(DEFAULT_STYLE_SHEET_PATH, "r", encoding="utf-8") as _f:
    DEFAULT_STYLE_SHEET = CSSParser(_f.read()).parse()


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
