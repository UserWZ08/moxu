"""Build source/portable archives from the current release; never package user data."""

import json
import sys
import zipfile
from pathlib import Path

from release_info import VERSION

ROOT = Path(__file__).resolve().parent
DOCUMENTS = [
    "使用说明.md",
    "0.8.2更新说明.md",
    "P0-P1修复记录.md",
    "维护说明.md",
    "验证记录.md",
    "本次更新与打印原理.md",
    "打印首选项故障说明.md",
    "打印机配置示例.json",
    "只读打印诊断.ps1",
    "运行只读诊断.cmd",
    "Run-Diagnostics.cmd",
    "PrintDiagnostics.ps1",
]


def example_configuration() -> str:
    config = json.loads((ROOT / "打印机配置示例.json").read_text("utf-8-sig"))
    for index, printer in enumerate(config["printers"]):
        printer["name"] = "示例黑白打印机" if index == 0 else "示例彩色打印机"
        printer.pop("quality_profiles", None)
        printer.pop("quality_bindings", None)
        printer.pop("active_quality", None)
    return json.dumps(config, ensure_ascii=False, indent=2)


def build_source() -> Path:
    target = ROOT.parent / f"墨序-源码-{VERSION}.zip"
    extra = {
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "release.ini",
        "installer.iss",
        "ChineseSimplified.isl",
        ".gitignore",
        "打印机配置示例.json",
    }
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.iterdir()):
            if not path.is_file() or not (
                path.suffix in {".py", ".md", ".ps1", ".cmd"} or path.name in extra
            ):
                continue
            if path.name == "打印机配置示例.json":
                archive.writestr("MoXu/" + path.name, example_configuration())
            else:
                archive.write(path, "MoXu/" + path.name)
        for folder in ("assets", "licenses"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_file():
                    archive.write(path, "MoXu/" + path.relative_to(ROOT).as_posix())
    return target


def build_portable() -> Path:
    program = ROOT / f"程序-{VERSION}" / "MoXu"
    if not (program / "MoXu.exe").is_file():
        raise FileNotFoundError("先运行 build.ps1 构建当前版本")
    target = ROOT.parent / f"墨序-免安装-{VERSION}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(program.rglob("*")):
            relative = path.relative_to(program)
            if path.is_file() and not (
                {"data", "logs", "__pycache__"} & set(relative.parts)
            ):
                archive.write(path, "MoXu/" + relative.as_posix())
        for name in DOCUMENTS:
            if name == "打印机配置示例.json":
                archive.writestr("MoXu/" + name, example_configuration())
            else:
                archive.write(ROOT / name, "MoXu/" + name)
        archive.writestr("MoXu/portable.flag", "Portable mode. Keep beside MoXu.exe.\n")
        archive.writestr(
            "MoXu/免安装说明.txt",
            "完整解压后运行 MoXu.exe。设置、客户、订单和日志位于同目录 data；升级前关闭旧程序并备份 data，移到新版同目录即可。请放在可写位置。\n",
        )
    return target


def write_windows_version(path: Path) -> None:
    """Generate PyInstaller's Windows resource from the same release.ini version."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = tuple(int(part) for part in VERSION.split(".")) + (0,)
    resource = VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "080404b0",
                        [
                            StringStruct("FileDescription", "墨序打印工作台"),
                            StringStruct("FileVersion", VERSION),
                            StringStruct("ProductName", "墨序"),
                            StringStruct("ProductVersion", VERSION),
                            StringStruct("OriginalFilename", "MoXu.exe"),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [2052, 1200])]),
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(resource), "utf-8")


if __name__ == "__main__":
    if "--version-info" in sys.argv:
        write_windows_version(Path(sys.argv[sys.argv.index("--version-info") + 1]))
    else:
        print(build_source())
        if "--source-only" not in sys.argv:
            print(build_portable())
