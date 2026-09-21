import tkinter
import tkinter.font

from broswer import (
    DEFAULT_STYLE_SHEET,
    URL,
    CSSParser,
    Element,
    HTMLParser,
    Text,
    cascade_priority,
    print_tree,
    style,
    tree_to_list,
)

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
SCROLLBAR_WIDTH = 12
PRE_FAMILY = "Courier New"  # pre 안에서 쓰는 고정폭 폰트


def is_block_level(node):

    return node.style.get("display", "inline") == "block"


FONTS = {}


def get_font(size, weight, style, family=None):
    # family은 pre 안의 고정폭 폰트처럼 "이 폰트만은 종류를 못박아야 할 때"만 넘긴다.
    # None이면 Tk 기본 폰트를 쓰고, family까지 캐시 키에 포함해 pre용과 일반용이
    # 서로 다른 Font 객체로 캐시된다.
    key = (size, weight, style, family)
    if key not in FONTS:
        if family:
            font = tkinter.font.Font(
                family=family, size=size, weight=weight, slant=style
            )
        else:
            font = tkinter.font.Font(size=size, weight=weight, slant=style)
        # Label을 함께 캐싱하면 metrics 성능이 좋아진다(파이썬 문서 권장)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


def get_node_font(node, family=None):
    # 노드의 계산된 스타일을 Tk가 이해하는 폰트로 옮긴다.
    # BlockLayout(줄바꿈 판단용)과 TextLayout(실제 그리기용)이 함께 쓴다.
    weight = node.style["font-weight"]
    slant = node.style["font-style"]
    if slant == "normal":
        slant = "roman"  # CSS의 normal을 Tk는 roman이라고 부른다
    # CSS 픽셀을 Tk 포인트로 환산한다(CSS는 1인치를 96픽셀 72포인트로 본다)
    size = int(float(node.style["font-size"][:-2]) * 0.75)
    return get_font(size, weight, slant, family)


COLORS = {}
_color_probe = None


def resolve_color(color, default="black"):
    # CSS 색 이름 중에는 Tk가 모르는 것이 있다(rebeccapurple, transparent,
    # #rrggbbaa 등). 그대로 넘기면 그리는 순간 TclError가 나서 페이지 전체가
    # 죽으므로, Tk에게 미리 물어보고 모르는 색이면 기본값으로 떨어뜨린다.
    #
    # 폰트와 달리 색은 style() 단계에서 걸러낼 수 없다. 어떤 이름을 아는지는
    # Tk만 알고, broswer.py는 Tk에 의존하지 않기 때문이다.
    global _color_probe
    if color not in COLORS:
        if _color_probe is None:
            _color_probe = tkinter.Label()
        try:
            _color_probe.winfo_rgb(color)
            COLORS[color] = color
        except tkinter.TclError:
            COLORS[color] = None
    return COLORS[color] or default


class Rect:
    # 그리기 명령과 브라우저 UI 요소의 경계를 한 가지 방식으로 표현한다.
    # 클릭이 어디에 떨어졌는지 판정할 때도 이걸 쓴다.
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def contains_point(self, x, y):
        return (
            x >= self.left and x < self.right and y >= self.top and y < self.bottom
        )

    def __repr__(self):
        return "Rect({}, {}, {}, {})".format(
            self.left, self.top, self.right, self.bottom
        )


class DrawText:
    def __init__(self, x1, y1, text, font, color):
        self.text = text
        self.font = font
        self.color = color  # CSS color 속성에서 온 글자색
        # 모든 그리기 명령이 rect를 갖도록 통일했다. 화면 밖 명령을 건너뛸 때
        # 명령 종류를 따지지 않고 rect만 보면 되기 때문이다.
        self.rect = Rect(
            x1, y1, x1 + font.measure(text), y1 + font.metrics("linespace")
        )

    def execute(self, scroll, canvas):
        # 스크롤 보정을 각 그리기 명령이 스스로 한다
        canvas.create_text(
            self.rect.left,
            self.rect.top - scroll,
            text=self.text,
            font=self.font,
            anchor="nw",
            fill=self.color,
        )


class DrawRect:
    def __init__(self, rect, color):
        self.rect = rect
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            width=0,  # 기본값이면 1픽셀 검은 테두리가 생기므로 없앤다
            fill=self.color,
        )


class DrawLine:
    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = Rect(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        canvas.create_line(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            fill=self.color,
            width=self.thickness,
        )


class DrawOutline:
    def __init__(self, rect, color, thickness):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            width=self.thickness,
            outline=self.color,
        )


def paint_tree(layout_object, display_list):
    # 부모를 먼저 칠하고 자식으로 내려가므로, 자식이 부모 배경 위에 그려진다
    display_list.extend(layout_object.paint())
    for child in layout_object.children:
        paint_tree(child, display_list)


class DocumentLayout:
    def __init__(self, node, window_width):
        self.node = node
        self.parent = None
        self.previous = None
        self.children = []
        # 창 크기가 바뀌면 줄바꿈이 달라지므로 창 폭을 받아 둔다(2-3 이식)
        self.window_width = window_width
        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def layout(self):
        child = BlockLayout([self.node], self, None)
        self.children.append(child)
        # 글자가 창 가장자리에 붙어 잘리지 않도록 좌우/위아래로 여백을 둔다
        self.width = self.window_width - 2 * HSTEP
        self.x = HSTEP
        self.y = VSTEP
        child.layout()
        self.height = child.height

    def paint(self):
        return []

    def __repr__(self):
        return "DocumentLayout(x={}, y={}, width={}, height={})".format(
            self.x, self.y, self.width, self.height
        )


class BlockLayout:
    def __init__(self, nodes, parent, previous):
        self.nodes = nodes
        # 익명 블록(5-5)은 노드를 여럿 담지만, 대표 노드 하나가 필요한 곳이 있다.
        # 클릭 히트 테스트가 layout_object.node를 읽고, LineLayout도 소속 노드를
        # 하나 받는다. 항상 첫 노드를 대표로 쓴다.
        self.node = nodes[0]
        self.parent = parent
        # 이전 형제. 세로 위치를 정할 때 "형제 바로 아래"를 계산하는 데 쓴다.
        self.previous = previous
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None
        # p 태그 아래 여백처럼 자식 높이의 합에 더해야 하는 몫. margin 속성이
        # 아직 없어서 코드로 남겨 둔 부분이다.
        self.extra_height = 0

    def layout_mode(self):
        # 자식에 블록 요소가 하나라도 있으면 블록 모드(자식을 세로로 쌓기),
        # 아니면 인라인 모드(글자를 줄 단위로 흘리기)로 처리한다.
        if len(self.nodes) > 1:
            # 노드가 여럿이면 부모가 인라인급 형제들을 묶어 만든 익명 블록이다
            return "inline"
        if isinstance(self.nodes[0], Text):
            return "inline"
        elif any(is_block_level(child) for child in self.nodes[0].children):
            return "block"
        elif self.nodes[0].children:
            return "inline"
        else:
            return "block"

    def add_block(self, nodes, previous):
        # 익명 블록이든 평범한 블록이든 형제 하나로 세어야 다음 형제의 y가 맞는다.
        # 그래서 만든 블록을 돌려주고, 호출한 쪽이 previous를 갱신하게 한다.
        block = BlockLayout(nodes, self, previous)
        self.children.append(block)
        return block

    def layout(self):
        # 계산 순서가 중요하다. width/x/y는 부모와 이전 형제를 읽으므로 자식보다
        # 먼저 구해야 하고, height는 자식을 읽으므로 자식 레이아웃 뒤에 구해야 한다.
        self.x = self.parent.x
        self.width = self.parent.width
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        mode = self.layout_mode()
        if mode == "block":
            # HTML 트리(node.children)를 읽어 레이아웃 트리(self.children)를 만든다.
            # 블록 모드에서는 노드가 항상 하나이므로 nodes[0]의 자식을 훑는다.
            #
            # 인라인급 자식은 연속된 구간 전체가 한 줄로 이어져야 하므로 즉시
            # 블록을 만들지 않고 pending에 모아 둔다. 블록급 자식을 만나거나
            # 자식이 다 끝나면 그때 모아 둔 것을 익명 블록 하나로 닫는다.
            previous = None
            pending = []
            for child in self.nodes[0].children:
                if is_block_level(child):
                    if pending:
                        previous = self.add_block(pending, previous)
                        pending = []
                    previous = self.add_block([child], previous)
                else:
                    pending.append(child)
            if pending:
                previous = self.add_block(pending, previous)
        else:
            # 인라인 모드의 자식은 LineLayout이다. 예전처럼 display_list에 좌표를
            # 직접 쌓는 대신, 줄과 단어가 각자 레이아웃 객체가 되어 스스로 위치와
            # 크기를 갖는다. 링크를 클릭하려면 단어마다 위치를 알아야 하기 때문이다.
            # cursor_x는 줄바꿈 시점을 판단하는 용도로만 남았다.
            self.cursor_x = 0
            self.in_pre = False
            self.new_line()
            for node in self.nodes:
                self.recurse(node)

        for child in self.children:
            child.layout()

        # 블록 모드는 자식 블록들의 높이 합, 인라인 모드는 줄들의 높이 합이다.
        # 두 경우가 같은 식으로 계산되는 것이 LineLayout 도입의 부수 효과다.
        self.height = sum(child.height for child in self.children) + self.extra_height

    def recurse(self, node):
        # 자식을 방문하기 전후로 open_tag/close_tag를 부르므로 여닫는 순서가 유지된다
        if isinstance(node, Text):
            self.text(node)
        else:
            self.open_tag(node)
            for child in node.children:
                self.recurse(child)
            self.close_tag(node)

    # i/b/small/big의 서식 처리는 browser.css로 옮겨갔다. 여기 남은 것은 CSS
    # 속성으로는 아직 표현할 수 없는 것들뿐이다(줄바꿈, 문단 여백, pre 모드).
    def open_tag(self, node):
        if node.tag == "br":
            self.new_line()
        elif node.tag == "pre":
            # pre 진입 전까지 쌓인 일반 텍스트 줄을 먼저 닫고, 이후 text()가
            # pre_text()로 분기하도록 in_pre를 켠다.
            self.new_line()
            self.in_pre = True

    def close_tag(self, node):
        if node.tag == "p":
            # 문단 아래 여백. margin 속성이 아직 없어서 코드로 남겨둔다.
            self.extra_height += VSTEP
        elif node.tag == "pre":
            # pre 안에서 쌓인 마지막 줄을 닫고 일반 텍스트 처리로 되돌린다.
            self.new_line()
            self.in_pre = False

    def new_line(self):
        # 줄 하나를 닫고 새 줄을 연다. 새 줄은 이전 줄을 previous로 가지므로
        # LineLayout이 스스로 자기 y를 "이전 줄 바로 아래"로 계산할 수 있다.
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        self.children.append(LineLayout(self.node, self, last_line))

    def add_word(self, node, word, family=None):
        # 지금 줄(children의 마지막 LineLayout)에 단어 하나를 TextLayout으로 붙인다
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        line.children.append(TextLayout(node, word, line, previous_word, family))

    def text(self, node):
        if self.in_pre:
            self.pre_text(node)
            return
        # 개행(\n)을 만나면 줄을 바꿔 원문 문단 구조를 유지한다(2장 연습문제 이식)
        lines = node.text.split("\n")
        for i, line in enumerate(lines):
            for word in line.split():
                self.word(node, word)
            if i < len(lines) - 1:
                self.new_line()

    def word(self, node, word):
        font = get_node_font(node)
        w = font.measure(word)
        # width에는 이미 좌우 여백이 빠져 있으므로 그대로 비교하면 된다
        if self.cursor_x + w > self.width:
            self.new_line()
        self.add_word(node, word)
        self.cursor_x += w + font.measure(" ")

    def pre_text(self, node):
        # pre 요구사항: 공백/들여쓰기를 그대로 보존하고, 줄 안에서 자동 줄바꿈을
        # 하지 않는다. 그래서 word()처럼 line.split()으로 단어를 쪼개지 않고
        # 한 줄 전체를 하나의 "단어"처럼 통째로 넣는다. 줄바꿈은 오직 원문에
        # 있는 \n에서만 일어난다.
        #
        # pre 안은 항상 고정폭 폰트를 강제한다(PRE_FAMILY). font-family 속성은
        # 아직 없으므로 family를 직접 넘겨서 폭이 일정하게 유지되도록 한다.
        lines = node.text.split("\n")
        for i, line in enumerate(lines):
            if line:
                self.add_word(node, line, PRE_FAMILY)
            elif i < len(lines) - 1:
                # 내용이 없는 줄. LineLayout은 자식이 없으면 높이가 0이라 코드
                # 블록 중간의 공백 줄이 사라진다. 폭 0짜리 TextLayout을 하나
                # 넣어 두면 폰트 높이만큼 자리를 차지한다.
                self.add_word(node, "", PRE_FAMILY)
            if i < len(lines) - 1:
                self.new_line()

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)

    def paint(self):
        cmds = []
        # 배경색을 CSS에서 읽는다. 배경은 상속되지 않으므로 이 블록에 대응하는
        # 요소가 직접 가진 값만 본다. 익명 블록(5-5)은 대응하는 요소가 없으니
        # 건너뛴다. 익명 블록의 노드는 전부 인라인급이라 이 조건으로 걸러진다.
        # 글자는 이제 TextLayout이 각자 칠하므로 여기서는 배경만 다룬다.
        if is_block_level(self.node):
            bgcolor = self.node.style.get("background-color", "transparent")
            if bgcolor != "transparent":
                # 배경은 못 알아보면 아예 칠하지 않는 편이 낫다. 글자색과 달리
                # 엉뚱한 기본색을 깔면 그 위의 글자가 안 보일 수 있다.
                bgcolor = resolve_color(bgcolor, None)
                if bgcolor:
                    cmds.append(DrawRect(self.self_rect(), bgcolor))
        return cmds

    def __repr__(self):
        # 익명 블록은 노드가 여럿이므로 담고 있는 것을 모두 나열한다
        names = ",".join(
            node.tag if isinstance(node, Element) else "text" for node in self.nodes
        )
        return "BlockLayout[{}](<{}>, x={}, y={}, width={}, height={})".format(
            self.layout_mode(), names, self.x, self.y, self.width, self.height
        )


class LineLayout:
    # 텍스트 한 줄. 자식인 TextLayout들의 세로 정렬(베이스라인 맞추기)을 책임진다.
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def layout(self):
        # 줄은 세로로 쌓이고 부모의 폭을 그대로 쓴다. 블록과 계산 방식이 같다.
        self.width = self.parent.width
        self.x = self.parent.x
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        # 단어의 폰트와 폭이 있어야 베이스라인을 구할 수 있으므로 먼저 눕힌다.
        # 이때 단어의 y는 아직 비어 있다.
        for word in self.children:
            word.layout()

        if not self.children:
            # 빈 줄(예: pre 진입 직전에 닫힌 줄)은 자리를 차지하지 않는다.
            # max()가 빈 리스트에서 터지는 것도 여기서 막는다.
            self.height = 0
            return

        # 예전 flush()가 하던 일. 줄 안에서 가장 큰 ascent에 베이스라인을 맞춰야
        # 크기가 다른 글자들이 아래쪽으로 가지런히 정렬된다.
        max_ascent = max(word.font.metrics("ascent") for word in self.children)
        baseline = self.y + 1.25 * max_ascent
        for word in self.children:
            word.y = baseline - word.font.metrics("ascent")
        max_descent = max(word.font.metrics("descent") for word in self.children)
        self.height = 1.25 * (max_ascent + max_descent)

    def paint(self):
        return []

    def __repr__(self):
        return "LineLayout(x={}, y={}, width={}, height={})".format(
            self.x, self.y, self.width, self.height
        )


class TextLayout:
    # 단어 하나. 이 객체가 생겼기 때문에 링크가 화면 어디에 있는지 알 수 있고,
    # 클릭을 어떤 단어에 떨어뜨릴지 판정할 수 있게 됐다.
    def __init__(self, node, word, parent, previous, family=None):
        self.node = node
        self.word = word
        self.family = family  # pre 안에서만 고정폭 폰트를 강제한다
        self.children = []
        self.parent = parent
        self.previous = previous
        self.x = None
        self.y = None  # y는 부모 LineLayout이 베이스라인을 정한 뒤 채워 준다
        self.width = None
        self.height = None
        self.font = None

    def layout(self):
        self.font = get_node_font(self.node, self.family)
        self.width = self.font.measure(self.word)
        if self.previous:
            # pre 안은 원문 공백을 그대로 살리므로 단어 사이에 공백을 넣지 않는다
            space = 0 if self.family else self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x
        self.height = self.font.metrics("linespace")

    def paint(self):
        color = resolve_color(self.node.style["color"])
        return [DrawText(self.x, self.y, self.word, self.font, color)]

    def __repr__(self):
        return "TextLayout({!r}, x={}, y={}, width={}, height={})".format(
            self.word, self.x, self.y, self.width, self.height
        )


class Tab:
    # 웹 페이지 하나. 자기 문서와 스크롤 위치, 방문 기록을 갖는다.
    # 창이나 이벤트는 모르고, Browser가 시키는 대로만 움직인다.
    def __init__(self, tab_width, tab_height):
        self.width = tab_width
        self.height = tab_height
        self.url = None
        self.history = []  # 뒤로 가기를 위해 방문한 URL을 쌓아 둔다
        self.scroll = 0
        self.nodes = None
        self.document = None
        self.display_list = []

    def load(self, url):
        self.url = url if isinstance(url, URL) else URL(url)
        self.history.append(self.url)
        self.scroll = 0
        body = self.url.request()
        self.nodes = HTMLParser(body).parse()

        # 브라우저 기본 스타일 시트를 깔고, 그 위에 페이지가 링크한 것들을 얹는다.
        # copy()를 하는 이유는 DEFAULT_STYLE_SHEET가 모듈 전역이라 페이지마다
        # extend하면 규칙이 계속 누적되기 때문이다.
        rules = DEFAULT_STYLE_SHEET.copy()
        for link in self.stylesheet_links():
            try:
                body = link.request()
            except Exception:
                # 못 받아온 스타일 시트는 무시하고 페이지는 계속 그린다
                continue
            rules.extend(CSSParser(body).parse())

        # 우선순위 순으로 정렬해 넘긴다. 같은 순위끼리는 파일 순서가 유지된다.
        style(self.nodes, sorted(rules, key=cascade_priority))

        self.build_document()

    def stylesheet_links(self):
        # <link rel="stylesheet" href="..."> 를 모두 찾아 절대 URL로 바꿔 준다
        return [
            self.url.resolve(node.attributes["href"])
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            and node.tag == "link"
            and node.attributes.get("rel") == "stylesheet"
            and "href" in node.attributes
        ]

    def build_document(self):
        # 레이아웃 트리를 새로 만들고, 그리기 명령 목록을 모은다
        self.document = DocumentLayout(self.nodes, self.width)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)

    def resize(self, width, height):
        # 창 폭이 바뀌면 줄바꿈이 달라지므로 레이아웃을 다시 계산한다(2-3)
        self.width, self.height = width, height
        if self.nodes is not None:
            self.build_document()
        self.scroll = min(self.scroll, self.max_scroll())

    def click(self, x, y):
        # 클릭 처리는 렌더링을 거꾸로 되짚는 일이다. 화면 좌표에서 출발해
        # 페이지 좌표로, 거기서 레이아웃 객체로, 다시 HTML 요소로 거슬러 간다.
        y += self.scroll  # 화면 좌표 → 페이지 좌표
        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width and obj.y <= y < obj.y + obj.height
        ]
        if not objs:
            return
        # 그릴 때 뒤에서 앞으로 칠하므로, 판정은 반대로 마지막 것부터 본다
        elt = objs[-1].node

        # 클릭된 것은 보통 링크 안의 텍스트 노드다. 실제 주소를 알려면 트리를
        # 거슬러 올라가 <a> 요소를 찾아야 한다.
        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elt = elt.parent

    def go_back(self):
        # load()가 history에 다시 쌓으므로, 두 개를 빼내고 그중 앞의 것을 연다.
        # 그냥 history[-2]를 열면 뒤로 가기를 두 번 눌렀을 때 제자리를 맴돈다.
        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)

    def document_height(self):
        # 트리 기반 레이아웃 덕분에 문서 전체 높이를 바로 알 수 있다.
        # 위아래 VSTEP 여백까지 포함해야 마지막 줄이 잘리지 않는다.
        if self.document is None:
            return 0
        return self.document.height + 2 * VSTEP

    def max_scroll(self):
        return max(0, self.document_height() - self.height)

    def scrolldown(self):
        self.scroll = min(self.scroll + SCROLL_STEP, self.max_scroll())

    def scrollup(self):
        self.scroll = max(0, self.scroll - SCROLL_STEP)

    def mousewheel(self, delta):
        self.scroll = max(0, min(self.scroll - delta, self.max_scroll()))

    def draw(self, canvas, offset):
        # offset은 브라우저 크롬이 차지한 높이다. 페이지는 그 아래에 그려진다.
        for cmd in self.display_list:
            # 화면 밖 명령은 건너뛴다
            if cmd.rect.top > self.scroll + self.height:
                continue
            if cmd.rect.bottom < self.scroll:
                continue
            cmd.execute(self.scroll - offset, canvas)
        self.draw_scrollbar(canvas, offset)

    def draw_scrollbar(self, canvas, offset):
        doc_height = self.document_height()
        # 문서 전체가 화면에 들어오면 스크롤바를 그리지 않음
        if doc_height <= self.height:
            return
        # 보이는 비율만큼 스크롤바 손잡이(thumb) 크기/위치를 정함
        thumb_height = self.height * self.height / doc_height
        thumb_top = self.height * self.scroll / doc_height
        x1 = self.width - SCROLLBAR_WIDTH
        canvas.create_rectangle(
            x1,
            offset + thumb_top,
            self.width,
            offset + thumb_top + thumb_height,
            fill="blue",
            outline="blue",
        )


class Chrome:
    # 브라우저 UI(탭 막대, 주소창, 뒤로 가기). 페이지가 아니라 브라우저 전체의
    # 정보를 다루므로 Tab이 아니라 Browser 쪽에 속한다.
    def __init__(self, browser):
        self.browser = browser
        # 운영체제마다 글자가 그려지는 크기가 달라서, UI 치수를 픽셀로 못박지 않고
        # 폰트 높이에서 끌어낸다.
        self.font = get_font(20, "normal", "roman")
        self.font_height = self.font.metrics("linespace")
        self.padding = 5

        self.tabbar_top = 0
        self.tabbar_bottom = self.font_height + 2 * self.padding

        plus_width = self.font.measure("+") + 2 * self.padding
        self.newtab_rect = Rect(
            self.padding,
            self.padding,
            self.padding + plus_width,
            self.padding + self.font_height,
        )

        self.urlbar_top = self.tabbar_bottom
        self.urlbar_bottom = self.urlbar_top + self.font_height + 2 * self.padding
        self.bottom = self.urlbar_bottom

        back_width = self.font.measure("<") + 2 * self.padding
        self.back_rect = Rect(
            self.padding,
            self.urlbar_top + self.padding,
            self.padding + back_width,
            self.urlbar_bottom - self.padding,
        )

        # 주소창에 타이핑 중인지(focus), 무엇을 쳤는지(address_bar)를 URL과 따로
        # 둔다. 타이핑하는 동안에는 아직 그 주소로 이동하지 않기 때문이다.
        self.focus = None
        self.address_bar = ""

    def address_rect(self):
        # 창 폭에 따라 달라지므로 값으로 고정하지 않고 그때그때 계산한다
        return Rect(
            self.back_rect.right + self.padding,
            self.urlbar_top + self.padding,
            self.browser.width - self.padding,
            self.urlbar_bottom - self.padding,
        )

    def tab_rect(self, i):
        # 탭 개수가 바뀌므로 위치를 저장하지 않고 필요할 때 계산한다.
        # 폭은 "Tab X"를 기준으로 재는데, X가 대개 가장 넓은 숫자만큼 넓다.
        tabs_start = self.newtab_rect.right + self.padding
        tab_width = self.font.measure("Tab X") + 2 * self.padding
        return Rect(
            tabs_start + tab_width * i,
            self.tabbar_top,
            tabs_start + tab_width * (i + 1),
            self.tabbar_bottom,
        )

    def paint(self):
        cmds = []
        width = self.browser.width

        # 페이지 내용이 크롬 아래로 비쳐 보이지 않도록 흰 배경을 먼저 깐다
        cmds.append(DrawRect(Rect(0, 0, width, self.bottom), "white"))
        cmds.append(DrawLine(0, self.bottom, width, self.bottom, "black", 1))

        cmds.append(DrawOutline(self.newtab_rect, "black", 1))
        cmds.append(
            DrawText(
                self.newtab_rect.left + self.padding,
                self.newtab_rect.top,
                "+",
                self.font,
                "black",
            )
        )

        for i, tab in enumerate(self.browser.tabs):
            bounds = self.tab_rect(i)
            cmds.append(DrawLine(bounds.left, 0, bounds.left, bounds.bottom, "black", 1))
            cmds.append(
                DrawLine(bounds.right, 0, bounds.right, bounds.bottom, "black", 1)
            )
            cmds.append(
                DrawText(
                    bounds.left + self.padding,
                    bounds.top + self.padding,
                    "Tab {}".format(i),
                    self.font,
                    "black",
                )
            )
            if tab == self.browser.active_tab:
                # 활성 탭만 아래쪽 선을 끊어 파일 폴더처럼 튀어나와 보이게 한다
                cmds.append(
                    DrawLine(0, bounds.bottom, bounds.left, bounds.bottom, "black", 1)
                )
                cmds.append(
                    DrawLine(
                        bounds.right, bounds.bottom, width, bounds.bottom, "black", 1
                    )
                )

        cmds.append(DrawOutline(self.back_rect, "black", 1))
        cmds.append(
            DrawText(
                self.back_rect.left + self.padding,
                self.back_rect.top,
                "<",
                self.font,
                "black",
            )
        )

        address_rect = self.address_rect()
        cmds.append(DrawOutline(address_rect, "black", 1))
        if self.focus == "address bar":
            cmds.append(
                DrawText(
                    address_rect.left + self.padding,
                    address_rect.top,
                    self.address_bar,
                    self.font,
                    "black",
                )
            )
            # 커서를 그려서 "지금 여기에 타이핑 중"이라는 상태를 눈에 보이게 한다
            w = self.font.measure(self.address_bar)
            cmds.append(
                DrawLine(
                    address_rect.left + self.padding + w,
                    address_rect.top,
                    address_rect.left + self.padding + w,
                    address_rect.bottom,
                    "red",
                    1,
                )
            )
        elif self.browser.active_tab and self.browser.active_tab.url:
            cmds.append(
                DrawText(
                    address_rect.left + self.padding,
                    address_rect.top,
                    str(self.browser.active_tab.url),
                    self.font,
                    "black",
                )
            )
        return cmds

    def blur(self):
        self.focus = None

    def click(self, x, y):
        self.focus = None
        if self.newtab_rect.contains_point(x, y):
            self.browser.new_tab(URL("https://browser.engineering/"))
        elif self.back_rect.contains_point(x, y):
            self.browser.active_tab.go_back()
        elif self.address_rect().contains_point(x, y):
            self.focus = "address bar"
            # 실제 브라우저는 전체 선택을 하지만, 텍스트 선택 기능이 없으므로
            # 그냥 비운다. 결과는 비슷하다.
            self.address_bar = ""
        else:
            for i, tab in enumerate(self.browser.tabs):
                if self.tab_rect(i).contains_point(x, y):
                    self.browser.active_tab = tab
                    break

    def keypress(self, char):
        if self.focus == "address bar":
            self.address_bar += char

    def enter(self):
        if self.focus == "address bar":
            self.browser.active_tab.load(URL(self.address_bar))
            self.focus = None


class Browser:
    # 창과 캔버스를 소유하고 모든 이벤트를 받는다. 무엇을 할지 정해서 활성 탭이나
    # 크롬에 넘긴다. Browser가 능동적이고 Tab은 수동적이다.
    def __init__(self):
        self.window = tkinter.Tk()  # 창 생성
        self.width, self.height = WIDTH, HEIGHT
        self.canvas = tkinter.Canvas(
            self.window,
            width=self.width,
            height=self.height,
            bg="white",  # Tk 9는 다크 모드를 따라가므로 배경을 명시한다
            highlightthickness=0,
        )  # 창에 대한 캔버스 생성
        self.canvas.pack(fill=tkinter.BOTH, expand=1)  # 창 크기에 맞춰 캔버스도 늘어남

        self.tabs = []
        self.active_tab = None
        self.chrome = Chrome(self)

        self.window.bind("<Down>", self.handle_down)
        self.window.bind("<Up>", self.handle_up)
        self.window.bind("<MouseWheel>", self.handle_mousewheel)
        self.window.bind("<Button-1>", self.handle_click)
        self.window.bind("<Key>", self.handle_key)
        self.window.bind("<Return>", self.handle_enter)
        self.canvas.bind("<Configure>", self.handle_resize)

    def new_tab(self, url):
        new_tab = Tab(self.width, self.height - self.chrome.bottom)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)
        self.draw()

    def draw(self):
        # 화면을 지우는 것은 Browser의 일이다. 그다음 활성 탭만 그리고,
        # 크롬을 나중에 그려서 페이지 위에 덮이도록 한다.
        self.canvas.delete("all")
        if self.active_tab:
            self.active_tab.draw(self.canvas, self.chrome.bottom)
        for cmd in self.chrome.paint():
            # 크롬은 스크롤되지 않으므로 스크롤 보정값이 0이다
            cmd.execute(0, self.canvas)

    def handle_click(self, e):
        if e.y < self.chrome.bottom:
            self.chrome.click(e.x, e.y)
        else:
            # 페이지를 클릭하면 주소창 편집을 끝낸다
            self.chrome.blur()
            self.active_tab.click(e.x, e.y - self.chrome.bottom)
        self.draw()

    def handle_key(self, e):
        # <Key>는 모든 키에 반응하므로 걸러야 한다. 문자가 없는 경우(수식 키)와
        # ASCII 밖(화살표, 기능 키)을 버린다.
        if len(e.char) == 0:
            return
        if not (0x20 <= ord(e.char) < 0x7F):
            return
        self.chrome.keypress(e.char)
        self.draw()

    def handle_enter(self, e):
        self.chrome.enter()
        self.draw()

    def handle_down(self, e):
        self.active_tab.scrolldown()
        self.draw()

    def handle_up(self, e):
        self.active_tab.scrollup()
        self.draw()

    def handle_mousewheel(self, e):
        self.active_tab.mousewheel(e.delta)
        self.draw()

    def handle_resize(self, e):
        self.width, self.height = e.width, e.height
        for tab in self.tabs:
            tab.resize(self.width, self.height - self.chrome.bottom)
        self.draw()


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--tree" in args:
        # 창을 띄우지 않고 파싱된 HTML 트리만 출력한다(파서 디버깅용)
        args.remove("--tree")
        print_tree(HTMLParser(URL(args[0]).request()).parse())
    elif "--layout" in args:
        # 레이아웃 트리를 출력한다. 폰트 측정에 Tk가 필요하므로 창은 숨겨서 만든다.
        args.remove("--layout")
        root = tkinter.Tk()
        root.withdraw()
        nodes = HTMLParser(URL(args[0]).request()).parse()
        # 레이아웃이 node.style을 읽으므로 스타일을 먼저 계산해야 한다
        style(nodes, sorted(DEFAULT_STYLE_SHEET.copy(), key=cascade_priority))
        document = DocumentLayout(nodes, WIDTH)
        document.layout()
        print_tree(document)
    else:
        Browser().new_tab(URL(args[0]))
        tkinter.mainloop()
