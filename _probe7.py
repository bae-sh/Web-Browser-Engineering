"""7장 구현 확인용. 창을 띄우지 않고 클릭/히스토리/크롬을 검사한다."""

import os
import tkinter

root = tkinter.Tk()
root.withdraw()

from broswer import URL, Element, Text, tree_to_list
from canvas import HEIGHT, WIDTH, Chrome, DrawText, Tab, TextLayout


def local(name):
    return URL("file://" + os.path.abspath(name))


def find_word(tab, needle):
    for obj in tree_to_list(tab.document, []):
        if isinstance(obj, TextLayout) and needle in obj.word:
            return obj
    return None


class FakeBrowser:
    """Chrome이 기대하는 최소한의 인터페이스만 흉내 낸다."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.tabs = []
        self.active_tab = None

    def new_tab(self, url):
        tab = Tab(self.width, self.height - self.chrome.bottom)
        tab.load(url)
        self.active_tab = tab
        self.tabs.append(tab)


print("=== 1. 링크 클릭 ===")
tab = Tab(WIDTH, HEIGHT - 60)
tab.load(local("test7.html"))
print("   최초 URL:", tab.url)

link = find_word(tab, "상대")
print("   링크 단어의 위치:", link)
# 단어 중앙을 클릭한다. 화면 좌표이므로 스크롤을 빼 준다.
tab.click(link.x + link.width // 2, link.y - tab.scroll + link.height // 2)
print("   클릭 후 URL:", tab.url)
print("   history 길이:", len(tab.history))

print()
print("=== 2. 뒤로 가기 ===")
tab.go_back()
print("   go_back 후 URL:", tab.url)
print("   history 길이:", len(tab.history))
tab.go_back()
print("   더 갈 곳 없을 때 한 번 더:", tab.url, "(그대로여야 함)")

print()
print("=== 3. 링크가 아닌 곳 클릭 ===")
before = str(tab.url)
bold = find_word(tab, "굵은")
tab.click(bold.x + 2, bold.y - tab.scroll + 2)
print("   굵은 글씨 클릭 후:", tab.url, "→ 변화 없음:", str(tab.url) == before)
tab.click(5, 5)  # 아무것도 없는 여백
print("   빈 여백 클릭 후:", tab.url, "→ 변화 없음:", str(tab.url) == before)

print()
print("=== 4. 크롬 그리기와 클릭 판정 ===")
browser = FakeBrowser(WIDTH, HEIGHT)
chrome = Chrome(browser)
browser.chrome = chrome
browser.new_tab(local("test7.html"))
cmds = chrome.paint()
print("   크롬 그리기 명령 수:", len(cmds))
print("   크롬 높이:", chrome.bottom)
print("   주소창에 그려지는 글자:")
for c in cmds:
    if isinstance(c, DrawText):
        print("      {!r}".format(c.text))

print("   뒤로가기 버튼 안의 점 포함?", chrome.back_rect.contains_point(10, 40))
print("   주소창 밖의 점(0,0) 포함?", chrome.address_rect().contains_point(0, 0))

print()
print("=== 5. 주소창 편집 ===")
chrome.click(chrome.address_rect().left + 5, chrome.address_rect().top + 5)
print("   주소창 클릭 후 focus:", repr(chrome.focus), "/ 내용:", repr(chrome.address_bar))
for ch in "file://" + os.path.abspath("test7b.html"):
    chrome.keypress(ch)
print("   타이핑 후 내용:", repr(chrome.address_bar))
chrome.enter()
print("   엔터 후 탭 URL:", browser.active_tab.url)
print("   엔터 후 focus:", repr(chrome.focus))

print()
print("=== 6. pre 안 빈 줄이 살아 있는지 ===")
pre_tab = Tab(WIDTH, HEIGHT - 60)
pre_tab.load(local("test.html"))
from canvas import BlockLayout, LineLayout

for obj in tree_to_list(pre_tab.document, []):
    if isinstance(obj, BlockLayout) and obj.node and getattr(obj.node, "tag", None) == "pre":
        for i, line in enumerate(obj.children):
            words = " ".join(w.word for w in line.children)
            print("   줄 {}: height={:<6} {!r}".format(i, line.height, words[:40]))
