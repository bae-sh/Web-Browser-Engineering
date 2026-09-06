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

# 세로로 쌓이는 블록을 만드는 태그들. 어떤 요소를 블록 모드로 다룰지 판단하는 기준이다.
BLOCK_ELEMENTS = [
    "html",
    "body",
    "article",
    "section",
    "nav",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hgroup",
    "header",
    "footer",
    "address",
    "p",
    "hr",
    "pre",
    "blockquote",
    "ol",
    "ul",
    "menu",
    "li",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "main",
    "div",
    "table",
    "form",
    "fieldset",
    "legend",
    "details",
    "summary",
]


def is_block_level(node):
    # 블록급인지 인라인급인지 판정한다. 태그 없는 맨 텍스트도 인라인급이다.
    return isinstance(node, Element) and node.tag in BLOCK_ELEMENTS


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


class DrawText:
    def __init__(self, x1, y1, text, font, color):
        self.left = x1
        self.top = y1
        self.text = text
        self.font = font
        self.color = color  # CSS color 속성에서 온 글자색
        # 화면 밖 명령을 건너뛸 때 쓰려고 아래쪽 경계도 미리 계산해 둔다
        self.bottom = y1 + font.metrics("linespace")

    def execute(self, scroll, canvas):
        # 스크롤 보정을 각 그리기 명령이 스스로 한다
        canvas.create_text(
            self.left,
            self.top - scroll,
            text=self.text,
            font=self.font,
            anchor="nw",
            fill=self.color,
        )


class DrawRect:
    def __init__(self, x1, y1, x2, y2, color):
        self.left = x1
        self.top = y1
        self.right = x2
        self.bottom = y2
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.left,
            self.top - scroll,
            self.right,
            self.bottom - scroll,
            width=0,  # 기본값이면 1픽셀 검은 테두리가 생기므로 없앤다
            fill=self.color,
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
        self.parent = parent
        # 이전 형제. 세로 위치를 정할 때 "형제 바로 아래"를 계산하는 데 쓴다.
        self.previous = previous
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None
        self.display_list = []

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
            # cursor는 페이지 절대 좌표가 아니라 이 블록 안의 상대 좌표다.
            # weight/style/size는 이제 각 노드의 style에서 읽으므로 여기 없다.
            self.cursor_x = 0
            self.cursor_y = 0
            self.in_pre = False
            self.line = []  # 한 줄에 들어갈 단어 버퍼 (상대 x, word, font, color)
            for node in self.nodes:
                self.recurse(node)
            self.flush()

        for child in self.children:
            child.layout()

        if mode == "block":
            self.height = sum(child.height for child in self.children)
        else:
            self.height = self.cursor_y

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
            self.flush()
        elif node.tag == "pre":
            # pre 진입 전까지 쌓인 일반 텍스트 줄을 먼저 확정하고, 이후 text()가
            # pre_text()로 분기하도록 in_pre를 켠다.
            self.flush()
            self.in_pre = True

    def close_tag(self, node):
        if node.tag == "p":
            # 문단 아래 여백. margin 속성이 아직 없어서 코드로 남겨둔다.
            self.flush()
            self.cursor_y += VSTEP
        elif node.tag == "pre":
            # pre 안에서 쌓인 마지막 줄을 확정하고 일반 텍스트 처리로 되돌린다.
            self.flush()
            self.in_pre = False

    def font(self, node, family=None):
        # 노드의 계산된 스타일을 Tk가 이해하는 폰트로 옮긴다.
        weight = node.style["font-weight"]
        style = node.style["font-style"]
        if style == "normal":
            style = "roman"  # CSS의 normal을 Tk는 roman이라고 부른다
        # CSS 픽셀을 Tk 포인트로 환산한다(CSS는 1인치를 96픽셀 72포인트로 본다)
        size = int(float(node.style["font-size"][:-2]) * 0.75)
        return get_font(size, weight, style, family)

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
                self.flush()

    def pre_text(self, node):
        # pre 요구사항: 공백/들여쓰기를 그대로 보존하고, 줄 안에서 자동 줄바꿈을
        # 하지 않는다. 그래서 word()처럼 line.split()으로 단어를 쪼개지 않고
        # 한 줄 전체를 하나의 "단어"처럼 통째로 버퍼에 넣는다. 줄바꿈은 오직
        # 원문에 있는 \n에서만 일어난다.
        #
        # pre 안은 항상 고정폭 폰트를 강제한다(PRE_FAMILY). font-family 속성은
        # 아직 없으므로 family를 직접 넘겨서 폭이 일정하게 유지되도록 한다.
        font = self.font(node, PRE_FAMILY)
        color = node.style["color"]
        lines = node.text.split("\n")
        for i, line in enumerate(lines):
            if line:
                self.line.append((self.cursor_x, line, font, color))
                self.cursor_x += font.measure(line)
            if i < len(lines) - 1:
                self.flush_pre_line(font)

    def flush_pre_line(self, font):
        # flush()는 버퍼가 비어 있으면 아무 것도 하지 않고 리턴하므로, 빈 줄
        # (예: 코드 블록 중간의 공백 줄)을 그대로 flush()에 넘기면 커서가
        # 내려가지 않고 다음 줄과 겹쳐버린다. 그래서 "이 줄에 내용이 있든 없든
        # 반드시 한 줄만큼 내려간다"를 보장하는 래퍼를 따로 둔다.
        if self.line:
            self.flush()
            return
        self.cursor_y += font.metrics("linespace") * 1.25
        self.cursor_x = 0

    def word(self, node, word):
        font = self.font(node)
        color = node.style["color"]
        w = font.measure(word)
        # width에는 이미 좌우 여백이 빠져 있으므로 그대로 비교하면 된다
        if self.cursor_x + w > self.width:
            self.flush()
        self.line.append((self.cursor_x, word, font, color))
        self.cursor_x += w + font.measure(" ")

    def flush(self):
        if not self.line:
            return
        metrics = [font.metrics() for x, word, font, color in self.line]
        max_ascent = max(metric["ascent"] for metric in metrics)
        baseline = self.cursor_y + 1.25 * max_ascent
        for rel_x, word, font, color in self.line:
            # 버퍼에는 블록 기준 상대 좌표가 들어 있으므로 블록 위치를 더해 준다
            x = self.x + rel_x
            y = self.y + baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font, color))
        max_descent = max(metric["descent"] for metric in metrics)
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = 0
        self.line = []

    def paint(self):
        cmds = []
        # 배경색을 CSS에서 읽는다. 배경은 상속되지 않으므로 이 블록에 대응하는
        # 요소가 직접 가진 값만 본다. 익명 블록(5-5)은 대응하는 요소가 없으니
        # 건너뛴다. 익명 블록의 노드는 전부 인라인급이라 이 조건으로 걸러진다.
        node = self.nodes[0]
        if is_block_level(node):
            bgcolor = node.style.get("background-color", "transparent")
            if bgcolor != "transparent":
                # 배경을 글자보다 먼저 넣어야 글자 아래에 깔린다
                x2, y2 = self.x + self.width, self.y + self.height
                cmds.append(DrawRect(self.x, self.y, x2, y2, bgcolor))
        if self.layout_mode() == "inline":
            for x, y, word, font, color in self.display_list:
                cmds.append(DrawText(x, y, word, font, color))
        return cmds

    def __repr__(self):
        # 익명 블록은 노드가 여럿이므로 담고 있는 것을 모두 나열한다
        names = ",".join(
            node.tag if isinstance(node, Element) else "text" for node in self.nodes
        )
        return "BlockLayout[{}](<{}>, x={}, y={}, width={}, height={})".format(
            self.layout_mode(), names, self.x, self.y, self.width, self.height
        )


class Browser:
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
        self.scroll = 0
        self.nodes = None
        self.document = None
        self.display_list = []
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<MouseWheel>", self.mousewheel)
        self.canvas.bind("<Configure>", self.resize)

    def load(self, url):
        base_url = url if isinstance(url, URL) else URL(url)
        body = base_url.request()
        self.nodes = HTMLParser(body).parse()

        # 브라우저 기본 스타일 시트를 깔고, 그 위에 페이지가 링크한 것들을 얹는다.
        # copy()를 하는 이유는 DEFAULT_STYLE_SHEET가 모듈 전역이라 페이지마다
        # extend하면 규칙이 계속 누적되기 때문이다.
        rules = DEFAULT_STYLE_SHEET.copy()
        for link in self.stylesheet_links(base_url):
            try:
                body = link.request()
            except Exception:
                # 못 받아온 스타일 시트는 무시하고 페이지는 계속 그린다
                continue
            rules.extend(CSSParser(body).parse())

        # 우선순위 순으로 정렬해 넘긴다. 같은 순위끼리는 파일 순서가 유지된다.
        style(self.nodes, sorted(rules, key=cascade_priority))

        self.build_document()
        self.draw()

    def stylesheet_links(self, base_url):
        # <link rel="stylesheet" href="..."> 를 모두 찾아 절대 URL로 바꿔 준다
        return [
            base_url.resolve(node.attributes["href"])
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

    def resize(self, e):
        self.width, self.height = e.width, e.height
        # 창 폭이 바뀌면 줄바꿈이 달라지므로 레이아웃을 다시 계산한다(2-3)
        if self.nodes is not None:
            self.build_document()
        self.scroll = min(self.scroll, self.max_scroll())
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for cmd in self.display_list:
            # 화면 밖 명령은 건너뛴다
            if cmd.top > self.scroll + self.height:
                continue
            if cmd.bottom < self.scroll:
                continue
            cmd.execute(self.scroll, self.canvas)
        self.draw_scrollbar()

    def draw_scrollbar(self):
        doc_height = self.document_height()
        # 문서 전체가 화면에 들어오면 스크롤바를 그리지 않음
        if doc_height <= self.height:
            return
        # 보이는 비율만큼 스크롤바 손잡이(thumb) 크기/위치를 정함
        thumb_height = self.height * self.height / doc_height
        thumb_top = self.height * self.scroll / doc_height
        x1 = self.width - SCROLLBAR_WIDTH
        self.canvas.create_rectangle(
            x1,
            thumb_top,
            self.width,
            thumb_top + thumb_height,
            fill="blue",
            outline="blue",
        )

    def document_height(self):
        # 트리 기반 레이아웃 덕분에 문서 전체 높이를 바로 알 수 있다.
        # 위아래 VSTEP 여백까지 포함해야 마지막 줄이 잘리지 않는다.
        if self.document is None:
            return 0
        return self.document.height + 2 * VSTEP

    def max_scroll(self):
        return max(0, self.document_height() - self.height)

    def scrolldown(self, e):
        self.scroll = min(self.scroll + SCROLL_STEP, self.max_scroll())
        self.draw()

    def scrollup(self, e):
        self.scroll = max(0, self.scroll - SCROLL_STEP)
        self.draw()

    def mousewheel(self, e):
        self.scroll = max(0, min(self.scroll - e.delta, self.max_scroll()))
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
        Browser().load(args[0])
        tkinter.mainloop()
