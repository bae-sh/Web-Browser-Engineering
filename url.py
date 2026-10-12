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

    def request(self, payload=None, max_redirects=10):
        if self.scheme == "data":
            return self.data

        if self.scheme == "file":
            return self.request_file()

        # 빈 폼도 제출은 제출이므로 payload가 ""여도 POST로 본다
        method = "POST" if payload is not None else "GET"

        cache_key = "{}://{}:{}{}".format(self.scheme, self.host, self.port, self.path)
        now = time.time()
        # POST는 서버 상태를 바꾸는 요청이라 캐시에서 꺼내 주면 안 된다
        if method == "GET" and cache_key in URL.cache:
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
        if payload is not None:
            # POST에는 Content-Length가 필수다. 글자 수가 아니라 바이트 수라서
            # 한글처럼 여러 바이트인 문자가 있으면 len(payload)와 다르다.
            headers["Content-Length"] = len(payload.encode("utf-8"))
        request = "{} {} HTTP/1.1\r\n".format(method, self.path)
        for header, value in headers.items():
            request += "{}: {}\r\n".format(header, value)
        request += "\r\n"
        if payload is not None:
            request += payload
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

        # 서버가 응답 후 연결을 끊겠다고 하면 소켓을 재사용 목록에서 뺀다.
        # HTTP/1.0 응답은 keep-alive를 명시하지 않는 한 끊는 것이 기본이다.
        # 그대로 두면 다음 요청이 이미 닫힌 소켓으로 나가 응답이 비어 버린다.
        connection = response_headers.get("connection", "").lower()
        keep_alive = (
            connection == "keep-alive"
            if version == "HTTP/1.0"
            else connection != "close"
        )

        if response_headers.get("transfer-encoding") == "chunked":
            body_bytes = self.read_chunked(response)
        elif "content-length" in response_headers:
            content_length = int(response_headers["content-length"])
            body_bytes = response.read(content_length)
        elif not keep_alive:
            # 길이를 안 알려 주고 연결을 끊는 서버는 끊길 때까지가 본문이다
            body_bytes = response.read()
        else:
            body_bytes = b""

        if not keep_alive:
            s.close()
            del URL.connections[key]

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
            # POST 뒤의 리다이렉트는 GET으로 따라간다. 서버가 폼 처리 후 결과
            # 페이지로 보내는 흔한 패턴이 이것이다.
            result_body = URL(location).request(max_redirects=max_redirects - 1)
        else:
            result_body = body

        # Cache-Control이 없는 응답은 캐시하지 않는다. 예전에는 무기한 캐시했는데,
        # 그러면 폼 제출로 서버 내용이 바뀌어도 옛 페이지가 계속 나온다.
        if (
            method == "GET"
            and status in ["200", "301", "404"]
            and "cache-control" in response_headers
        ):
            should_cache = True
            expiry = None
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
