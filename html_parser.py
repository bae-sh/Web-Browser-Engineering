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
        # 태그 이름과 속성들을 분리한다. 따옴표로 감싼 값 안에는 공백이 들어갈 수
        # 있으므로(class="wide narrow") 그냥 공백으로 자르면 값이 두 동막으로
        # 쪼개진다. 그래서 글자를 훑으면서 지금 따옴표 안인지 밖인지를 추적하고,
        # 따옴표 밖의 공백에서만 자른다. 따옴표 자체는 값에 넣지 않는다.
        parts = []
        buf = ""
        quote = ""
        for c in text:
            if quote:
                if c == quote:
                    quote = ""
                else:
                    buf += c
            elif c in "'\"":
                quote = c
            elif c.isspace():
                if buf:
                    parts.append(buf)
                buf = ""
            else:
                buf += c
        if buf:
            parts.append(buf)

        tag = parts[0].casefold()  # HTML 태그/속성 이름은 대소문자를 구분하지 않는다
        attributes = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
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
