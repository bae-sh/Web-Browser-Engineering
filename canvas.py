import tkinter
import tkinter.font

from broswer import URL, Element, HTMLParser, Text, print_tree

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
    def __init__(self, x1, y1, text, font):
        self.left = x1
        self.top = y1
        self.text = text
        self.font = font
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
            fill="black",  # Tk 9의 다크 모드에서도 보이도록 색을 명시한다
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
        child = BlockLayout(self.node, self, None)
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
    def __init__(self, node, parent, previous):
        self.node = node
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
        if isinstance(self.node, Text):
            return "inline"
        elif any(
            isinstance(child, Element) and child.tag in BLOCK_ELEMENTS
            for child in self.node.children
        ):
            # 블록과 텍스트가 섞여 있으면 작성자의 실수로 보고 블록 모드로 복구한다
            return "block"
        elif self.node.children:
            return "inline"
        else:
            return "block"

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
            # HTML 트리(node.children)를 읽어 레이아웃 트리(self.children)를 만든다
            previous = None
            for child in self.node.children:
                block = BlockLayout(child, self, previous)
                self.children.append(block)
                previous = block
        else:
            # cursor는 페이지 절대 좌표가 아니라 이 블록 안의 상대 좌표다
            self.cursor_x = 0
            self.cursor_y = 0
            self.weight = "normal"
            self.style = "roman"
            self.size = 12
            self.in_pre = False
            self.line = []  # 한 줄에 들어갈 단어 버퍼 (상대 x, word, font)
            self.recurse(self.node)
            self.flush()

        for child in self.children:
            child.layout()

        if mode == "block":
            self.height = sum(child.height for child in self.children)
        else:
            self.height = self.cursor_y

    def recurse(self, tree):
        # 자식을 방문하기 전후로 open_tag/close_tag를 부르므로 여닫는 순서가 유지된다
        if isinstance(tree, Text):
            self.text(tree)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "small":
            self.size -= 2
        elif tag == "big":
            self.size += 4
        elif tag == "br":
            self.flush()
        elif tag == "pre":
            # pre 진입 전까지 쌓인 일반 텍스트 줄을 먼저 확정하고, 이후 text()가
            # pre_text()로 분기하도록 in_pre를 켠다.
            self.flush()
            self.in_pre = True

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        elif tag == "small":
            self.size += 2
        elif tag == "big":
            self.size -= 4
        elif tag == "p":
            self.flush()
            self.cursor_y += VSTEP
        elif tag == "pre":
            # pre 안에서 쌓인 마지막 줄을 확정하고 일반 텍스트 처리로 되돌린다.
            self.flush()
            self.in_pre = False

    def text(self, tok):
        if self.in_pre:
            self.pre_text(tok)
            return
        # 개행(\n)을 만나면 줄을 바꿔 원문 문단 구조를 유지한다(2장 연습문제 이식)
        lines = tok.text.split("\n")
        for i, line in enumerate(lines):
            for word in line.split():
                self.word(word)
            if i < len(lines) - 1:
                self.flush()

    def pre_text(self, tok):
        # pre 요구사항: 공백/들여쓰기를 그대로 보존하고, 줄 안에서 자동 줄바꿈을
        # 하지 않는다. 그래서 word()처럼 line.split()으로 단어를 쪼개지 않고
        # 한 줄 전체를 하나의 "단어"처럼 통째로 버퍼에 넣는다. 줄바꿈은 오직
        # 원문에 있는 \n에서만 일어난다.
        lines = tok.text.split("\n")
        for i, line in enumerate(lines):
            if line:
                # pre 안은 항상 고정폭 폰트를 강제한다(PRE_FAMILY). <b>/<i> 태그로
                # weight/style이 바뀌어도 family는 유지되므로 폭이 일정하게 유지된다.
                font = get_font(self.size, self.weight, self.style, PRE_FAMILY)
                self.line.append((self.cursor_x, line, font))
                self.cursor_x += font.measure(line)
            if i < len(lines) - 1:
                self.flush_pre_line()

    def flush_pre_line(self):
        # flush()는 버퍼가 비어 있으면 아무 것도 하지 않고 리턴하므로, 빈 줄
        # (예: 코드 블록 중간의 공백 줄)을 그대로 flush()에 넘기면 커서가
        # 내려가지 않고 다음 줄과 겹쳐버린다. 그래서 "이 줄에 내용이 있든 없든
        # 반드시 한 줄만큼 내려간다"를 보장하는 래퍼를 따로 둔다.
        if self.line:
            self.flush()
            return
        font = get_font(self.size, self.weight, self.style, PRE_FAMILY)
        self.cursor_y += font.metrics("linespace") * 1.25
        self.cursor_x = 0

    def word(self, word):
        font = get_font(self.size, self.weight, self.style)
        w = font.measure(word)
        # width에는 이미 좌우 여백이 빠져 있으므로 그대로 비교하면 된다
        if self.cursor_x + w > self.width:
            self.flush()
        self.line.append((self.cursor_x, word, font))
        self.cursor_x += w + font.measure(" ")

    def flush(self):
        if not self.line:
            return
        metrics = [font.metrics() for x, word, font in self.line]
        max_ascent = max(metric["ascent"] for metric in metrics)
        baseline = self.cursor_y + 1.25 * max_ascent
        for rel_x, word, font in self.line:
            # 버퍼에는 블록 기준 상대 좌표가 들어 있으므로 블록 위치를 더해 준다
            x = self.x + rel_x
            y = self.y + baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))
        max_descent = max(metric["descent"] for metric in metrics)
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = 0
        self.line = []

    def paint(self):
        cmds = []
        # 배경을 글자보다 먼저 넣어야 글자 아래에 깔린다
        if isinstance(self.node, Element) and self.node.tag == "pre":
            x2, y2 = self.x + self.width, self.y + self.height
            cmds.append(DrawRect(self.x, self.y, x2, y2, "gray"))
        if self.layout_mode() == "inline":
            for x, y, word, font in self.display_list:
                cmds.append(DrawText(x, y, word, font))
        return cmds

    def __repr__(self):
        name = self.node.tag if isinstance(self.node, Element) else "text"
        return "BlockLayout[{}](<{}>, x={}, y={}, width={}, height={})".format(
            self.layout_mode(), name, self.x, self.y, self.width, self.height
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
        body = URL(url).request()
        self.nodes = HTMLParser(body).parse()
        self.build_document()
        self.draw()

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
        document = DocumentLayout(HTMLParser(URL(args[0]).request()).parse(), WIDTH)
        document.layout()
        print_tree(document)
    else:
        Browser().load(args[0])
        tkinter.mainloop()
