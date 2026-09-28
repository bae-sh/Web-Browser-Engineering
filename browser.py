import tkinter

from draw import DrawLine, DrawOutline, DrawRect, DrawText, Rect, get_font
from tab import Tab
from url import URL

WIDTH, HEIGHT = 800, 600


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
            cmds.append(
                DrawLine(bounds.left, 0, bounds.left, bounds.bottom, "black", 1)
            )
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
            # 현재 주소를 그대로 채워 두고 이어서 고칠 수 있게 한다
            self.address_bar = str(self.browser.active_tab.url)
        else:
            for i, tab in enumerate(self.browser.tabs):
                if self.tab_rect(i).contains_point(x, y):
                    self.browser.active_tab = tab
                    break

    def keypress(self, char):
        if self.focus == "address bar":
            if char == "\b":
                self.address_bar = self.address_bar[:-1]
            else:
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
        self.window.bind("<Button-3>", self.handle_middle_click)
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

    def handle_middle_click(self, e):
        if e.y < self.chrome.bottom:
            self.chrome.click(e.x, e.y)
        else:
            self.chrome.blur()
            url = self.active_tab.middle_click(e.x, e.y - self.chrome.bottom)
            if url:
                self.new_tab(url)
        self.draw()

    def handle_key(self, e):
        # <Key>는 모든 키에 반응하므로 걸러야 한다. 문자가 없는 경우(수식 키)와
        # ASCII 밖(화살표, 기능 키)을 버린다.
        if e.keysym == "BackSpace":
            self.chrome.keypress("\b")
            self.draw()
            return
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
