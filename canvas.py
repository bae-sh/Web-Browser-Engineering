import tkinter
import tkinter.font

from broswer import URL, lex, Text, Tag

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100
SCROLLBAR_WIDTH = 12

FONTS = {}


def get_font(size, weight, style):
    key = (size, weight, style)
    if key not in FONTS:
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

    def text(self, tok):
        # 개행(\n)을 만나면 줄을 바꿔 원문 문단 구조를 유지한다(2장 연습문제 이식)
        lines = tok.text.split("\n")
        for i, line in enumerate(lines):
            for word in line.split():
                self.word(word)
            if i < len(lines) - 1:
                self.flush()

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
            self.window, width=self.width, height=self.height
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
                x, y - self.scroll, text=word, font=font, anchor="nw"
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
