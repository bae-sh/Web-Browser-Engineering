from draw import DrawRect, DrawText, Rect, get_font, resolve_color
from html_parser import Element, Text

HSTEP, VSTEP = 13, 18
PRE_FAMILY = "Courier New"  # pre 안에서 쓰는 고정폭 폰트


def is_block_level(node):

    return node.style.get("display", "inline") == "block"


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


def paint_tree(layout_object, display_list):
    # 부모를 먼저 칠하고 자식으로 내려가므로, 자식이 부모 배경 위에 그려진다
    for cmd in layout_object.paint():
        # 클릭된 그리기 명령에서 HTML 요소까지 거슬러 가려면 명령이 자기를
        # 만든 레이아웃 객체를 알아야 한다(7-11)
        cmd.layout_object = layout_object
        display_list.append(cmd)
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
