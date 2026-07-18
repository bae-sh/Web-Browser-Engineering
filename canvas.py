import tkinter

from broswer import URL, lex

WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()  # 창 생성
        self.width, self.height = WIDTH, HEIGHT
        self.canvas = tkinter.Canvas(
            self.window, width=self.width, height=self.height
        )  # 창에 대한 캔버스 생성
        self.canvas.pack(fill=tkinter.BOTH, expand=1)  # 창 크기에 맞춰 캔버스도 늘어남
        self.scroll = 0
        self.text = ""
        self.display_list = []
        self.window.bind("<Down>", self.scrolldown)
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<MouseWheel>", self.mousewheel)
        self.canvas.bind("<Configure>", self.resize)

    def layout(self, text):
        display_list = []
        cursor_x, cursor_y = HSTEP, VSTEP
        for c in text:
            if c == "\n":
                cursor_y += VSTEP * 1.5
                cursor_x = HSTEP
                continue
            display_list.append((cursor_x, cursor_y, c))
            cursor_x += HSTEP
            if cursor_x >= self.width - HSTEP:
                cursor_y += VSTEP
                cursor_x = HSTEP
        return display_list

    def load(self, url):
        body = URL(url).request()
        self.text = lex(body)
        self.display_list = self.layout(self.text)
        self.draw()

    def resize(self, e):
        self.width, self.height = e.width, e.height
        self.display_list = self.layout(self.text)
        self.scroll = min(self.scroll, self.max_scroll())
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for x, y, c in self.display_list:
            if y > self.scroll + self.height:
                continue
            if y + VSTEP < self.scroll:
                continue
            self.canvas.create_text(x, y - self.scroll, text=c)

    def max_scroll(self):
        if not self.display_list:
            return 0
        return max(0, self.display_list[-1][1] + VSTEP - self.height)

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
