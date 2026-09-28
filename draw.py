import tkinter
import tkinter.font


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


COLORS = {}
_color_probe = None


def resolve_color(color, default="black"):
    # CSS 색 이름 중에는 Tk가 모르는 것이 있다(rebeccapurple, transparent,
    # #rrggbbaa 등). 그대로 넘기면 그리는 순간 TclError가 나서 페이지 전체가
    # 죽으므로, Tk에게 미리 물어보고 모르는 색이면 기본값으로 떨어뜨린다.
    #
    # 폰트와 달리 색은 style() 단계에서 걸러낼 수 없다. 어떤 이름을 아는지는
    # Tk만 알고, css.py는 Tk에 의존하지 않기 때문이다.
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
