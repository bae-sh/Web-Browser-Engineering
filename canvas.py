import tkinter
import tkinter.font

from broswer import URL, lex, Text, Tag

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
SCROLLBAR_WIDTH = 12
PRE_FAMILY = "Courier New"  # pre 안에서 쓰는 고정폭 폰트

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


class Layout:
    def __init__(self, tokens, width):
        self.width = width
        self.display_list = []
        self.cursor_x = HSTEP
        self.cursor_y = VSTEP
        self.weight = "normal"
        self.style = "roman"
        self.size = 12
        self.in_pre = False
        self.line = []  # 한 줄에 들어갈 단어 버퍼 (x, word, font)
        for tok in tokens:
            self.token(tok)
        self.flush()

    def token(self, tok):
        if isinstance(tok, Text):
            self.text(tok)
        elif tok.tag == "i":
            self.style = "italic"
        elif tok.tag == "/i":
            self.style = "roman"
        elif tok.tag == "b":
            self.weight = "bold"
        elif tok.tag == "/b":
            self.weight = "normal"
        elif tok.tag == "small":
            self.size -= 2
        elif tok.tag == "/small":
            self.size += 2
        elif tok.tag == "big":
            self.size += 4
        elif tok.tag == "/big":
            self.size -= 4
        elif tok.tag == "br":
            self.flush()
        elif tok.tag == "/p":
            self.flush()
            self.cursor_y += VSTEP
        elif tok.tag == "pre":
            # pre 진입 전까지 쌓인 일반 텍스트 줄을 먼저 확정하고, 이후 text()가
            # pre_text()로 분기하도록 in_pre를 켠다.
            self.flush()
            self.in_pre = True
        elif tok.tag == "/pre":
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
        # 빈 줄도 한 줄 높이만큼 내려가야 하므로 버퍼가 비어도 커서를 옮긴다
        font = get_font(self.size, self.weight, self.style, PRE_FAMILY)
        self.cursor_y += font.metrics("linespace") * 1.25
        self.cursor_x = HSTEP

    def word(self, word):
        font = get_font(self.size, self.weight, self.style)
        w = font.measure(word)
        if self.cursor_x + w > self.width - HSTEP:
            self.flush()
        self.line.append((self.cursor_x, word, font))
        self.cursor_x += w + font.measure(" ")

    def flush(self):
        if not self.line:
            return
        metrics = [font.metrics() for x, word, font in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])
        baseline = self.cursor_y + 1.25 * max_ascent
        for x, word, font in self.line:
            y = baseline - font.metrics("ascent")
            self.display_list.append((x, y, word, font))
        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + 1.25 * max_descent
        self.cursor_x = HSTEP
        self.line = []


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
        self.tokens = []
        self.display_list = []
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<MouseWheel>", self.mousewheel)
        self.canvas.bind("<Configure>", self.resize)

    def load(self, url):
        body = URL(url).request()
        self.tokens = lex(body)
        self.display_list = Layout(self.tokens, self.width).display_list
        self.draw()

    def resize(self, e):
        self.width, self.height = e.width, e.height
        self.display_list = Layout(self.tokens, self.width).display_list
        self.scroll = min(self.scroll, self.max_scroll())
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for x, y, word, font in self.display_list:
            if y > self.scroll + self.height:
                continue
            if y + font.metrics("linespace") < self.scroll:
                continue
            self.canvas.create_text(
                x, y - self.scroll, text=word, font=font, anchor="nw", fill="black"
            )
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
        if not self.display_list:
            return 0
        x, y, word, font = self.display_list[-1]
        return y + font.metrics("linespace")

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

    Browser().load(sys.argv[1])
    tkinter.mainloop()
