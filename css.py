import os

from html_parser import Element


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
                self.whitespace()
                # 선언이 온전히 끝났는지 확인한 뒤에야 값을 채택한다. 세미콜론
                # 이거나, 블록의 마지막 선언이면 } 앞이어야 한다.
                #
                # 확인 전에 먼저 저장하면 "color: var(--x)"처럼 뒤에 이해 못할
                # 것이 붙은 선언에서 word()가 읽어낸 앞토막("var")만 살아남는다.
                # 그 값은 나중에 폰트나 색으로 쓰이다가 예외를 내고 페이지 전체를
                # 죽인다. 브라우저는 이해 못하는 선언을 통째로 버려야 한다.
                if self.i < len(self.s) and self.s[self.i] == ";":
                    self.literal(";")
                    self.whitespace()
                elif self.i < len(self.s) and self.s[self.i] != "}":
                    raise Exception(
                        "Parsing error: expected ';' or '}}' at {}".format(self.i)
                    )
                pairs[prop] = val
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

    def selector_name(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "-_":
                self.i += 1
            else:
                break
        if not (self.i > start):
            raise Exception(
                "Parsing error: expected selector name at {}".format(self.i)
            )
        return self.s[start : self.i]

    def simple_selector(self):
        # 단순 셀렉터 하나. 점으로 시작하면 클래스 셀렉터, 아니면 태그 셀렉터다.
        if self.i < len(self.s) and self.s[self.i] == ".":
            self.literal(".")
            # 태그 이름은 대소문자를 구분하지 않지만 클래스 이름은 구분하므로
            # 여기서는 casefold를 하지 않는다.
            return ClassSelector(self.selector_name())
        return TagSelector(self.selector_name().casefold())

    def sequence_selector(self):
        selectors = [self.simple_selector()]
        # 시퀀스가 이어진다는 신호는 다음 글자 하나다.
        # self.i가 문자열 끝을 넘지 않았는지도 같이 확인해야 한다.
        while self.i < len(self.s) and self.s[self.i] == ".":
            selectors.append(self.simple_selector())
        if len(selectors) == 1:
            return selectors[0]
        return SequenceSelector(selectors)

    def selector(self):
        # 공백으로 띄운 단순 셀렉터들을 왼쪽부터 후손 관계로 엮는다.
        # "article div p"는 (article div) p 처럼 왼쪽으로 결합한다.
        out = self.sequence_selector()
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            descendant = self.sequence_selector()
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


class ClassSelector:
    def __init__(self, cls):
        self.cls = cls
        # 클래스 셀렉터는 태그 셀렉터를 이겨야 한다. 실제 CSS도 클래스를 태그보다
        # 훨씬 무겁게 보므로 넉넉하게 10을 준다.
        self.priority = 10

    def matches(self, node):
        if not isinstance(node, Element):
            return False
        # class 속성은 공백으로 구분된 목록이다. class="a b"는 .a와 .b 양쪽에
        # 걸려야 하므로 문자열을 통째로 비교하면 안 되고 쪼개서 확인해야 한다.
        return self.cls in node.attributes.get("class", "").split()

    def __repr__(self):
        return "." + self.cls


class SequenceSelector:
    def __init__(self, selectors):
        # selectors: TagSelector / ClassSelector 들이 담긴 리스트
        self.selectors = selectors
        self.priority = sum(selector.priority for selector in selectors)

    def matches(self, node):
        return all(selector.matches(node) for selector in self.selectors)

    def __repr__(self):
        return "".join(repr(selector) for selector in self.selectors)


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

# 값의 종류가 정해져 있는 속성들. 레이아웃과 그리기 코드가 이 값들만 다룰 줄
# 안다. em/rem/vw 같은 단위, 숫자 font-weight(600), oblique 등은 아직 모른다.
SUPPORTED_VALUES = {
    "font-weight": {"normal", "bold"},
    "font-style": {"normal", "italic"},
}


def is_supported(property, value):
    # 브라우저는 이해 못하는 선언을 조용히 버린다. 버리면 그 속성은 1단계에서
    # 깔아 둔 상속값이나 기본값을 그대로 쓰게 되므로 화면이 깨지지 않는다.
    # 반대로 모르는 값을 그냥 받아 두면 폰트나 색으로 변환하는 순간 예외가 나서
    # 페이지 전체가 죽는다.
    if property == "font-size":
        # %는 style()이 곧 px로 환산한다. 그 외 단위는 아직 지원하지 않는다.
        if value.endswith("px"):
            number = value[:-2]
        elif value.endswith("%"):
            number = value[:-1]
        else:
            return False
        try:
            float(number)
        except ValueError:
            return False
        return True
    if property in SUPPORTED_VALUES:
        return value in SUPPORTED_VALUES[property]
    return True


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
            if not is_supported(property, value):
                continue
            node.style[property] = value

    # 3) style 속성. 어떤 스타일 시트보다 우선한다.
    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for property, value in pairs.items():
            if not is_supported(property, value):
                continue
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
