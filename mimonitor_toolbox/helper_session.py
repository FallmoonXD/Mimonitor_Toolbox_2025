"""Reuse a native helper through an authenticated ADB loopback forward.

The forward is private to one Adb instance. A connection may be recreated before
sending a request; a request with an uncertain outcome is never sent again.
"""
import socket
import struct
import uuid


class SessionRejected(RuntimeError):
    pass


class HelperSession:
    def __init__(self, adb):
        self.adb = adb
        self.port = None
        self.directory = "/sdcard/Download/Mimonitor_Toolbox/.session_" + uuid.uuid4().hex
        self.token = self.directory.rsplit("_", 1)[1]
        self.identity = None

    def start(self):
        from . import adb as runtime
        self.adb._verified_jars.pop("MtkDirectTool.jar", None)
        self.adb._verified_jars.pop("ColorfulLedTool.jar", None)
        self.adb.check_and_heal_jar()
        self.adb.check_and_heal_colorful_led_tool(check=True)
        self.identity = (self.adb.serial, self.adb._jar_fingerprint(runtime.get_mtk_direct_tool_path()),
                         self.adb._jar_fingerprint(runtime.get_colorful_led_tool_path()))
        command = runtime.build_tvservice_app_process_command(
            "/data/data/mitv.service/cache/MtkDirectTool.jar:/data/data/mitv.service/cache/ColorfulLedTool.jar",
            ["ToolboxSession", self.directory])
        # TvService starts Runtime.exec; background the worker inside its sh -c.
        command = command[:-1] + r'\${IFS}\>/dev/null\${IFS}2\>\&1\${IFS}\&"'
        ready = self.directory + "/ready"
        output = self.adb.shell(
            f"mkdir -p {self.directory}; {command} >/dev/null; "
            f"i=0; while [ $i -lt 100 ] && [ ! -f {ready} ]; do sleep 0.03; i=$((i+1)); done; "
            f"cat {ready} 2>/dev/null", check=True)
        lines = output.strip().splitlines()
        if len(lines) != 3 or lines[:2] != ["1", self.token]:
            raise RuntimeError("显示器辅助会话启动失败，未发送调节命令")
        remote_port = int(lines[2])
        if not 0 < remote_port < 65536:
            raise RuntimeError("无效的辅助会话端口")
        forwarded = runtime.adb_run(["-s", self.adb.serial, "forward", "tcp:0", f"tcp:{remote_port}"], check=True)
        self.port = int(forwarded.strip())
        if not 0 < self.port < 65536:
            raise RuntimeError("无效的本地辅助会话端口")
        self.adb._confirm_remote_jar("MtkDirectTool.jar", runtime.get_mtk_direct_tool_path())
        return self

    def matches(self):
        from . import adb as runtime
        return self.identity == (
            self.adb.serial, self.adb._jar_fingerprint(runtime.get_mtk_direct_tool_path()),
            self.adb._jar_fingerprint(runtime.get_colorful_led_tool_path()))

    @staticmethod
    def _receive(connection, size):
        data = bytearray()
        while len(data) < size:
            part = connection.recv(size - len(data))
            if not part:
                raise ConnectionError("辅助会话已断开")
            data.extend(part)
        return bytes(data)

    def call(self, tool, arguments):
        parts = [self.token, tool] + [str(arg) for arg in arguments]
        if len(parts) < 3 or any("\n" in part or "\r" in part for part in parts):
            raise ValueError("无效的辅助会话参数")
        payload = "\n".join(parts).encode("utf-8")
        if len(payload) > 1024 * 1024:
            raise ValueError("辅助会话请求过长")
        # No automatic reconnect/replay after sendall: a setter may have run.
        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as connection:
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            connection.settimeout(10)
            try:
                connection.sendall(struct.pack(">I", len(payload)) + payload)
                ready_length = struct.unpack(">I", self._receive(connection, 4))[0]
                if not 0 < ready_length <= 1024 * 1024:
                    raise RuntimeError("辅助会话握手长度无效")
                ready = self._receive(connection, ready_length).decode("utf-8")
                if ready.startswith("ERROR\n"):
                    raise SessionRejected("辅助会话拒绝请求：" + ready.partition("\n")[2])
                if ready != "READY":
                    raise RuntimeError(ready)
                connection.sendall(struct.pack(">I", 2) + b"GO")
                length = struct.unpack(">I", self._receive(connection, 4))[0]
                if not 0 < length <= 1024 * 1024:
                    raise RuntimeError("辅助会话响应长度无效")
                response = self._receive(connection, length).decode("utf-8")
            except SessionRejected:
                raise
            except Exception as error:
                raise RuntimeError("辅助会话通讯中断，结果未确认；命令未自动重发，请刷新核对") from error
        status, _, result = response.partition("\n")
        if status != "OK":
            raise RuntimeError(f"辅助会话执行失败：{result}")
        return result

    def close(self, stop=False):
        from . import adb as runtime
        if self.port:
            if stop:
                try:
                    self.call("close", [""])
                except (OSError, RuntimeError):
                    pass
            runtime.adb_run(["-s", self.identity[0], "forward", "--remove", f"tcp:{self.port}"])
        self.port = None
