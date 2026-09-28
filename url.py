import gzip
import socket
import ssl
import time


class URL:
    # (scheme, host, port) -> (socket, makefile 객체)
    connections = {}
    # "scheme://host:port/path" -> (body, expiry). expiry가 None이면 무기한
    cache = {}

    def __init__(self, url):
        self.view_source = False
        if url.startswith("view-source:"):
            self.view_source = True
            url = url[len("view-source:") :]

        if url.startswith("data:"):
            self.scheme = "data"
            # data:text/html,Hello 이런 타입으로 들어오게 됨.
            self.mediatype, self.data = url[len("data:") :].split(",", 1)
            return

        self.scheme, url = url.split("://", 1)
        assert self.scheme in ["http", "https", "file"]

        if self.scheme == "file":
            self.path = url
            return

        if self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443

        if "/" not in url:
            url = url + "/"
        self.host, url = url.split("/", 1)
        self.path = "/" + url
        if ":" in self.host:
            self.host, self.port = self.host.split(":", 1)
            self.port = int(self.port)

    def request(self, max_redirects=10):
        if self.scheme == "data":
            return self.data

        if self.scheme == "file":
            return self.request_file()

        cache_key = "{}://{}:{}{}".format(self.scheme, self.host, self.port, self.path)
        now = time.time()
        if cache_key in URL.cache:
            cached_body, expiry = URL.cache[cache_key]
            if expiry is None or now < expiry:
                return cached_body
            del URL.cache[cache_key]

        key = (self.scheme, self.host, self.port)
        if key in URL.connections:
            s, response = URL.connections[key]
        else:
            s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            s.connect((self.host, self.port))
            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            response = s.makefile("rb")
            URL.connections[key] = (s, response)

        headers = {
            "Host": self.host,
            "Connection": "keep-alive",
            "Accept-Encoding": "gzip",
            #  Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 크롬은 매우 복잡
            "User-Agent": "baesh",
        }
        request = "GET {} HTTP/1.1\r\n".format(self.path)
        for header, value in headers.items():
            request += "{}: {}\r\n".format(header, value)
        request += "\r\n"
        s.send(request.encode("utf-8"))

        status_line = response.readline().decode("utf-8")
        version, status, explanation = status_line.split(" ", 2)
        response_headers = {}
        while True:
            line = response.readline().decode("utf-8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        if response_headers.get("transfer-encoding") == "chunked":
            body_bytes = self.read_chunked(response)
        elif "content-length" in response_headers:
            content_length = int(response_headers["content-length"])
            body_bytes = response.read(content_length)
        else:
            body_bytes = b""

        if response_headers.get("content-encoding") == "gzip":
            body_bytes = gzip.decompress(body_bytes)

        body = body_bytes.decode("utf-8")

        if status.startswith("3") and "location" in response_headers:
            if max_redirects <= 0:
                raise Exception("Too many redirects")
            location = response_headers["location"]
            if "://" not in location:
                location = "{}://{}:{}{}".format(
                    self.scheme, self.host, self.port, location
                )
            result_body = URL(location).request(max_redirects - 1)
        else:
            result_body = body

        if status in ["200", "301", "404"]:
            should_cache = True
            expiry = None
            if "cache-control" in response_headers:
                directives = response_headers["cache-control"].lower().split(",")
                for directive in directives:
                    directive = directive.strip()
                    if directive.startswith("max-age="):
                        expiry = now + int(directive[len("max-age=") :])
                    else:
                        # no-store를 포함해, max-age 외의 값이면 캐시하지 않음
                        should_cache = False
            if should_cache:
                URL.cache[cache_key] = (result_body, expiry)

        return result_body

    def read_chunked(self, response):
        data = b""
        while True:
            size_line = response.readline().decode("utf-8")
            # "1a; 확장자" 형태일 수 있어 세미콜론 앞부분만 사용
            size = int(size_line.split(";")[0].strip(), 16)
            if size == 0:
                response.readline()  # 마지막 청크 뒤의 빈 줄(\r\n)
                break
            data += response.read(size)
            response.readline()  # 각 청크 데이터 뒤의 \r\n
        return data

    def request_file(self):
        with open(self.path, "r", encoding="utf-8") as f:
            return f.read()

    def __str__(self):
        # 주소창에 URL을 표시하려면 URL 객체를 다시 문자열로 되돌려야 한다.
        # str(url)이 이 메서드를 부른다.
        if self.scheme == "data":
            body = "data:{},{}".format(self.mediatype, self.data)
        elif self.scheme == "file":
            body = "file://" + self.path
        else:
            # 기본 포트는 굳이 보여주지 않는 편이 주소가 깔끔하다
            port_part = ":" + str(self.port)
            if self.scheme == "https" and self.port == 443:
                port_part = ""
            elif self.scheme == "http" and self.port == 80:
                port_part = ""
            body = self.scheme + "://" + self.host + port_part + self.path
        if self.view_source:
            body = "view-source:" + body
        return body

    def resolve(self, url):
        # <link href="...">처럼 페이지 안에 적힌 상대 URL을 절대 URL로 바꾼다.
        # 기준점은 self, 즉 그 링크가 적혀 있던 페이지의 URL이다.
        if "://" in url:
            # 이미 스킴이 있는 완전한 URL
            return URL(url)
        if url.startswith("//"):
            # 스킴만 물려받는 형태(//example.com/main.css)
            return URL(self.scheme + ":" + url)
        if not url.startswith("/"):
            # 경로 상대 URL. 현재 경로에서 파일 이름을 떼어낸 디렉터리가 기준이 된다.
            # ".."를 풀어주는 것도 브라우저 몫이라 여기서 직접 처리한다.
            dir, _ = self.path.rsplit("/", 1)
            while url.startswith("../"):
                _, url = url.split("/", 1)
                if "/" in dir:
                    dir, _ = dir.rsplit("/", 1)
            url = dir + "/" + url
        if self.scheme == "file":
            # file 스킴은 host/port가 없으므로 경로만 붙인다
            return URL("file://" + url)
        return URL("{}://{}:{}{}".format(self.scheme, self.host, self.port, url))
