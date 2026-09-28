from css import DEFAULT_STYLE_SHEET, CSSParser, cascade_priority, style
from html_parser import Element, HTMLParser, Text, tree_to_list
from layout import VSTEP, DocumentLayout, paint_tree
from url import URL

SCROLL_STEP = 100
SCROLLBAR_WIDTH = 12


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

    def middle_click(self, x, y):
        y += self.scroll  # 화면 좌표 → 페이지 좌표
        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width and obj.y <= y < obj.y + obj.height
        ]
        if not objs:
            return
        elt = objs[-1].node

        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                return self.url.resolve(elt.attributes["href"])
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
