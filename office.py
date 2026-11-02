"""Prefer the document's native Microsoft engine; only missing engines may fall back."""

import base64
import json
import logging
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

from office_processes import OwnedOfficeProcesses

logger = logging.getLogger(__name__)

POLICIES = ["Microsoft Office 优先", "仅 Microsoft Office", "仅 LibreOffice"]


def engine_signature():
    """Invalidate compatibility caches when an Office engine is installed/registered."""
    try:
        import winreg

        result = []
        for name in ["Word.Application", "Excel.Application", "PowerPoint.Application"]:
            try:
                with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, name + "\\CLSID") as k:
                    clsid = winreg.QueryValue(k, None)
                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + "\\LocalServer32"
                ) as k:
                    server = winreg.QueryValue(k, None)
                result.append(name + clsid + server)
            except OSError:
                result.append(name + ":missing")
        return "|".join(result)
    except ImportError:
        return "non-windows"


SESSION_SCRIPT = (Path(__file__).parent / "assets" / "office_helper.ps1").read_text(
    "utf-8"
)


class ConversionSession:
    """Reuse Office within a batch; discard an unhealthy helper before the next file."""

    def __init__(self, timeout: float = 180):
        self.process = None
        self.responses = queue.Queue()
        self.timeout = timeout
        self.owned = None
        self.reader = None
        self._request_failed = False

    def __enter__(self):
        return self

    def _start(self) -> None:
        encoded = base64.b64encode(SESSION_SCRIPT.encode("utf-16le")).decode("ascii")
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            creationflags=0x08000000,
        )
        responses = queue.Queue()
        owned = OwnedOfficeProcesses()
        self.process, self.responses, self.owned = process, responses, owned

        # Capture this generation; an old reader must never write into the new queue.
        def read():
            try:
                for line in process.stdout:
                    try:
                        message = json.loads(line)
                    except ValueError:
                        logger.warning("Office helper emitted a non-JSON response")
                        continue
                    if message.get("event") == "office_process":
                        owned.register(int(message["pid"]), int(message["created"]))
                    else:
                        responses.put(message)
            except (OSError, ValueError):
                logger.exception("Office response stream failed")
            finally:
                responses.put({"code": 1, "error": "Office 转换进程意外退出"})

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def native(self, source: Path, output: Path, kind: str) -> dict:
        if self._request_failed:
            self.close()
            self._request_failed = False
        if self.process is None:
            self._start()
        try:
            self.process.stdin.write(
                json.dumps(
                    {
                        "source": str(source.resolve()),
                        "dest": str(output.resolve()),
                        "kind": kind,
                    }
                )
                + "\n"
            )
            self.process.stdin.flush()
            result = self.responses.get(timeout=self.timeout)
        except queue.Empty as error:
            logger.error("Office conversion timed out: engine=%s", kind)
            self.close(force=True)
            raise RuntimeError(
                "Office 转换超时；会话已重置，后续文件将重新启动转换引擎"
            ) from error
        except (OSError, ValueError) as error:
            logger.exception("Office helper pipe failed")
            self.close(force=True)
            raise RuntimeError(
                "Office 转换会话已退出，后续文件将重新建立会话"
            ) from error
        # A reported conversion error can also leave COM state unusable.
        self._request_failed = result.get("code") not in (0, 15)
        return result

    def close(self, force: bool = False) -> None:
        process, owned, reader = self.process, self.owned, self.reader
        self.process = self.owned = self.reader = None
        if process is None:
            return
        try:
            try:
                process.stdin.close()  # Healthy helper reaches finally -> Quit + COM release.
            except (OSError, ValueError):
                pass
            try:
                if force:
                    process.kill()
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if reader:
                reader.join(timeout=5)
        finally:
            if owned:
                owned.close()
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass

    def __exit__(self, *args):
        self.close()


def libreoffice_path():
    found = shutil.which("soffice")
    if found:
        return found
    for base in [
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
    ]:
        p = Path(base) / "LibreOffice/program/soffice.exe"
        if p.exists():
            return str(p)
    return None


def convert(source, folder, output, policy="Microsoft Office 优先", session=None):
    source = Path(source)
    folder = Path(folder)
    output = Path(output)
    if policy not in POLICIES:
        raise ValueError("Office 转换引擎设置无效")
    kind = (
        "word"
        if source.suffix.lower() in [".doc", ".docx"]
        else "excel" if source.suffix.lower() in [".xls", ".xlsx"] else "ppt"
    )
    label = {
        "word": "Microsoft Word",
        "excel": "Microsoft Excel",
        "ppt": "Microsoft PowerPoint",
    }[kind]
    if policy != "仅 LibreOffice":
        if session is not None:
            result = session.native(source, output, kind)
        else:
            with ConversionSession() as temporary_session:
                result = temporary_session.native(source, output, kind)
        if result["code"] == 0 and output.exists():
            return label
        output.unlink(missing_ok=True)
        missing = result["code"] == 15
        if not missing:
            raise RuntimeError(
                label
                + " 转换失败；为避免静默改变排版，没有切换其他引擎。\n"
                + result.get("error", "")[-650:]
            )
        if policy == "仅 Microsoft Office":
            raise RuntimeError(
                "没有安装对应的 " + label + "，请安装它或提交已确认的 PDF"
            )
    executable = libreoffice_path()
    if not executable:
        raise RuntimeError(
            "没有可用的 Office 转换引擎。请安装对应 Microsoft Office/LibreOffice，或先导出 PDF。"
        )
    proc = subprocess.run(
        [
            executable,
            "-env:UserInstallation=" + (folder / "profile").resolve().as_uri(),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(folder),
            str(source.resolve()),
        ],
        capture_output=True,
        timeout=180,
        creationflags=0x08000000,
    )
    converted = folder / (source.stem + ".pdf")
    if proc.returncode or not converted.exists():
        raise RuntimeError(
            "LibreOffice 转换失败：" + proc.stderr.decode(errors="replace")[-650:]
        )
    if converted.resolve() != output.resolve():
        converted.replace(output)
    return "LibreOffice（兼容转换，请核对排版）"


def engine_label(source, prepared):
    suffix = Path(source).suffix.lower()
    if suffix == ".pdf":
        return "Qt PDF / PDFium"
    if suffix in [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]:
        p = Path(prepared).parent / "engine.txt"
        return p.read_text("utf-8") if p.exists() else "Office 转换"
    return "Qt 图像模块"
