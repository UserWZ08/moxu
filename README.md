<div align="center">

<img src="assets/moxu.png" alt="墨序 MoXu" width="110" />

# 墨序 · MoXu

**面向社区打印店 / 自助打印点的 Windows 桌面工作台**

把客户的 PDF、Word、图片排进对的纸张，算对价钱，再稳稳交到打印机。

[![Version](https://img.shields.io/badge/version-0.8.2-e77826)](#)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](#技术栈)
[![Qt](https://img.shields.io/badge/Qt%20%2F%20PySide6-6.8.3-41CD52?logo=qt&logoColor=white)](#技术栈)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011%20x64-0078D4?logo=windows&logoColor=white)](#系统要求)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[简体中文](#简体中文) · [English](#english)

</div>

---

## 简体中文

### 这是什么

墨序是一个**单机、离线**的打印店工作台。店员把客户发来的文件拖进窗口，选好纸张、颜色、单双面和质量，软件负责：自动匹配能打的打印机、按纸张布局排版、实时预览与报价、生成订单单据，最后逐份提交到 Windows 打印队列。

它不联网、不上传文件、不监听端口，客户档案与订单都存在本机。设计目标不是"能打出来"，而是**打之前就知道会打成什么样、收多少钱**——这也是整个代码库最核心的一条主线：预览、覆盖率估算、导出排版 PDF、实际打印，全部共用同一套白底纸张光栅逻辑。

### 功能

| 模块 | 能力 |
| --- | --- |
| 文件导入 | 拖放或选择 PDF / DOC(X) / XLS(X) / PPT(X) / JPG / PNG / BMP / TIF，批量导入；多页 TIFF 逐帧解析；多张图片可合成一个双面页组 |
| 排版 | 按纸张实际毫米尺寸布局；自动方向（按首张选中页判定）；完整留白 / 填充裁切；PDF 自适应 / 仅缩小 / 实际大小 |
| 打印 | 单面 / 双面长边 / 双面短边；逐份提交保证奇数页双面不串页；驱动拒绝参数时直接阻止提交，而不是静默降级；**按设备实际 X/Y 分辨率分块渲染，A4/A3 的 600 与 1200 DPI 都保持完整输出网格** |
| 质量档位 | 全店统一"标准打印 / 高质量打印"，按设备分别绑定为 DPI（惠普 600/1200）或厂商原生预设（爱普生等，通过 DEVMODE 抓取并回读校验） |
| 计价 | 标价 + 可选的量大优惠（分段累进 / 满量降价），按纸张 × 颜色 × 单双面分别配置，按"面"或"张"计费，全程 `Decimal`；未配置的价格视为"未提供该服务"，只拦截当次选择 |
| 客户档案 | 姓名 / 小区 / 楼栋 / 房号 / 手机 / QQ / 微信，拼音与首字母搜索，Excel 导入导出（合并更新、不回填空字段、拒绝公式），历史订单保存客户快照 |
| 照片证件 | 身份证、户口本、证件照排版，5 寸 / 6 寸相纸，按实际尺寸打印 |
| 单据 | 可自定义的订单 HTML 与 PDF 单据，订单记录存 SQLite |
| 桌面 | 关闭时可选"退到后台"，托盘图标唤回；开机自启动（当前用户级，免管理员）；再次启动会唤回已运行窗口 |
| 可靠性 | 单实例锁；提交状态与提示文字分离（改设置不会洗掉"已提交"证据）；崩溃遗留的"正在提交"自动标为需人工核对队列；滚动日志 + 全局异常钩子 |
| 诊断 | 后台"关于"可复制诊断信息；`PrintDiagnostics.ps1` 只读打印诊断 |

### 为什么值得一看

打印类桌面软件最难的不是界面，而是**同一份内容在四个地方长得一样**：屏幕预览、覆盖率估算、导出检查用的 PDF、真正发往驱动器的位图。这份代码把四者收敛到 `page_raster.Document.sheet()` 一个入口：

- PDF 与透明 PNG 先合成到白底，再转灰度 —— 修掉了"透明背景被当成黑色"这个经典坑（旧版会整页黑块，覆盖率飙到 100%）；
- 0.8 起实体打印不再整页限像素，而是按纸张最终尺寸、按设备分辨率**分块、1:1 像素**渲染，取消了旧版"1200 DPI 实际只有 498 DPI"的人为降采样；
- 页码、方向旋转、纸张方向、驱动边距都在同一条坐标链上算，避免"预览 A4、出纸 A3"；
- 打印前先把光栅算完，再开始提交，失败时能明确停在"已提交几份"而不是"不知道打了没"。

### 技术栈

- **Python 3.13** + **PySide6 / Qt 6.8.3**（QtWidgets、QtPrintSupport、QtPdf、QtGui）
- **PyInstaller 6.22** 打包，**Inno Setup** 生成安装包
- **SQLite**（订单、客户）+ **JSON**（设置，原子写入 + 迁移 + 损坏恢复）
- **PowerShell COM 自动化**调用 Word / Excel / PowerPoint 导出 PDF，批内复用实例，按内容指纹缓存
- **Win32 DEVMODE**（通过 `ctypes`）读取并写回厂商质量预设
- 开发：`black`、`ruff`（见 `requirements-dev.txt`、`pyproject.toml`）

### 系统要求

- Windows 10 / 11 x64
- 打印功能需要已安装的打印机驱动（虚拟打印机也能跑通流程）
- 转换 Office 文档需要本机安装 Microsoft Office 或 LibreOffice；没有的话先导出 PDF

### 快速开始（源码运行）

```powershell
git clone https://github.com/UserWZ08/moxu.git
cd moxu
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

首次启动会在 `%LOCALAPPDATA%\NeighbourPrint` 建好 `settings.json`、`orders.sqlite`、`logs\` 和转换缓存。免安装版则在程序目录放一个 `portable.flag`，数据写到同目录的 `data\`。

### 打包

```powershell
.\build.ps1                                                  # PyInstaller -> 程序-0.8.2\MoXu\
python package_release.py                                    # 生成安装包 / 免安装包（见 release.ini）
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

`build.ps1` 会把 `licenses\` 与 `THIRD_PARTY_NOTICES.md` 一并复制进发行目录——Qt 以 LGPLv3 动态链接方式分发，替换库文件的权利必须随包保留。

### 测试

```powershell
python -m unittest discover -p "test_*.py" -v
python test_ui.py      # 界面交互检查（需要图形环境）
```

0.8.2 通过 104 项自动回归。重点覆盖那些"看起来对、打出来错"的地方：透明 PDF/PNG 白底、A4 原稿按实际大小放到 A3、分块渲染与整页渲染逐像素一致、600/1200 DPI 的完整尺寸、非等向 X/Y DPI、模拟 GDI 的逐字节检查、多页 TIFF 帧数校验、转换缓存命中与失效、配置损坏恢复、计价与阶梯边界、提交状态与重复打印确认。

**注意：测试不覆盖真实打印机出纸**，实体设备的背面翻转、边距、厂商质量和纸面清晰度仍需样张验收。

### 目录结构

| 文件 | 职责 |
| --- | --- |
| `app.py` | 程序入口、主窗口接线、命令行（`--diagnostic` / `--feature-check` / `--capture-driver`） |
| `workbench_ui.py` / `queue_model.py` | 工作台界面与队列模型（表格、选择、实时设置回显） |
| `print_models.py` / `print_jobs.py` | 队列项与提交状态的 dataclass / 提交服务（质量解析、逐份提交、取消） |
| `core.py` | 领域模型：配置校验与迁移、页码解析、打印机路由、报价、订单账本 |
| `settings_repository.py` | 配置读写、原子保存、损坏检测与备份恢复 |
| `pricing.py` / `catalog.py` | 标价与优惠展开、纸张/装订目录 |
| `page_raster.py` | 纸张光栅布局：白底合成、方向、边距、缩放、分块渲染 |
| `page_layout.py` / `photo_layout.py` | 内容落位计算；证件/相纸排版 |
| `printing.py` | QPrinter 构造与参数校验、Qt 打印路径、TIFF 处理 |
| `windows_driver.py` / `driver_capture.py` | DEVMODE 读写、GDI 分块输出、厂商质量预设捕获 |
| `quality.py` | "标准 / 高质量"到 DPI 或厂商预设的解析与交叉校验 |
| `coverage.py` | 150 DPI 的着色面积与平均色调估算 |
| `office.py` / `office_processes.py` | Word/Excel/PPT → PDF（COM 会话复用、进程清理、内容指纹缓存） |
| `settings_ui.py` / `business_settings.py` | 后台设置（价格、打印机、纸张、装订、模板、启动与关闭） |
| `customers.py` / `customer_ui.py` | 客户表、拼音搜索、Excel 往返 |
| `photo_ui.py` | 照片/证件排版工作台 |
| `receipt.py` / `order_pdf.py` | 订单 HTML / PDF 单据 |
| `desktop_lifecycle.py` / `desktop_settings.py` / `autostart.py` | 托盘、单实例唤回、开机自启 |
| `diagnostics.py` | 日志、异常钩子、诊断信息 |
| `controls.py` / `theme.py` | 自绘控件与明暗主题 |
| `remote_contract.py` | 未来局域网接入的请求校验（本版不监听端口） |
| `PrintDiagnostics.ps1` | 只读打印诊断脚本 |

### 数据与隐私

- 全部数据在本地：`%LOCALAPPDATA%\NeighbourPrint\{settings.json, orders.sqlite, logs\, cache\}`，免安装版在程序目录 `data\`。
- 不发起任何网络请求，不上传文件；`remote_contract.py` 只是尚未启用的接入校验。
- 关掉软件再升级；切换安装版/免安装版前先备份数据目录。

### 已知限制

- 仅 Windows，且深度依赖驱动行为：不同驱动对 DEVMODE、纸张、双面的支持差异很大，所以代码选择"校验不过就拒绝提交"。
- 打印仍是"PDF 渲染成位图再交给驱动"，**不是矢量 PDF 直通**；原图或扫描件本身分辨率低时，提高输出 DPI 也补不回细节。
- 高分辨率输出会增加渲染时间与打印队列数据量（A3 1200 DPI 尤其明显）。
- Office 转换无法保证与 Word 的排版逐像素一致，复杂文档建议先出 PDF。
- 覆盖率是**着色面积估算**，不是耗墨量，也不是厂商标准测试页。
- 实体设备的双面翻转、边距、厂商质量、纸面清晰度仍需现场样张验收；自动启动与托盘只做了模拟注册表与集成验证。

### 许可证

[MIT](LICENSE)。打包的 Qt / PySide6 以 LGPLv3 动态链接分发，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 `licenses/`。

---

## English

### What is this

MoXu (墨序) is an **offline, single-machine desktop workbench for small print shops**. A clerk drops customer files into the window, picks paper, colour, simplex/duplex and quality; the app then routes the job to a capable printer, lays the content out on the physical sheet, previews it, prices it, writes an order receipt, and finally submits each copy to the Windows print queue.

No network, no uploads, no listening ports — settings, customers and orders stay on the machine. The goal is not merely "it prints", but **you know exactly how it will look and what it will cost before paper moves**. That is the central thread of the codebase: preview, coverage estimate, exportable proof PDF and the actual print bitmap all go through one white-background raster pipeline (`page_raster.Document.sheet`).

### Features

- **Import**: PDF, DOC(X), XLS(X), PPT(X), JPG/PNG/BMP/TIF, drag-and-drop, batch import; multi-page TIFF is split frame by frame; several images can be merged into one duplex page group.
- **Layout**: real millimetre paper sizes, automatic orientation from the first selected page, fill/crop vs. contain, PDF adaptive / shrink-only / actual size.
- **Printing**: simplex / duplex long-edge / short-edge; per-copy submission so odd-page duplex documents never bleed into each other; if the driver rejects a setting the job is blocked instead of silently downgraded. Since 0.8 the raster is rendered **tiled at the device's real X/Y resolution**, so 600 and 1200 DPI keep a full output grid on A4/A3.
- **Quality**: two store-wide levels ("standard" / "high"), each bound per printer either to a DPI value or to a vendor-native preset captured as a DEVMODE blob and verified by read-back.
- **Pricing**: base price plus optional volume discounts (progressive or threshold), per paper × colour × simplex/duplex, per side or per sheet, all in `Decimal`. An unconfigured combination means "service not offered" and only blocks that selection.
- **Customers**: name / community / building / room / phone / QQ / WeChat, pinyin and initials search, Excel import/export (merge-update, no blank overwrite, formulas rejected), order snapshots.
- **ID photos**: ID card, household register, passport-photo sheets, 5"/6" photo paper, printed at actual size.
- **Receipts**: customisable order HTML and PDF documents, SQLite order ledger.
- **Desktop**: close-to-tray with a tray icon, per-user autostart, and a second launch brings the running window back.
- **Reliability**: single-instance lock, submission state kept separate from UI text, orphaned "submitting" rows flagged after a crash, rolling logs and global exception hooks.
- **Diagnostics**: copyable diagnostics from the About page; read-only `PrintDiagnostics.ps1`.

### Tech stack

Python 3.13 · PySide6 / Qt 6.8.3 · PyInstaller · Inno Setup · SQLite + JSON · PowerShell COM automation for Word/Excel/PowerPoint → PDF · Win32 DEVMODE via `ctypes` · `black` / `ruff` for development.

### Quick start

```powershell
git clone https://github.com/UserWZ08/moxu.git
cd moxu
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Data lives in `%LOCALAPPDATA%\NeighbourPrint` (or `data\` next to the executable in portable mode).

### Build

```powershell
.\build.ps1                                                  # PyInstaller -> 程序-0.8.2\MoXu\
python package_release.py                                    # installer / portable packages
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

### Tests

```powershell
python -m unittest discover -p "test_*.py" -v
python test_ui.py
```

0.8.2 passes 104 automated tests. The suite targets the "looks right, prints wrong" cases: transparent PDF/PNG compositing, A4-actual-size on A3, tiled vs. full-page pixel equality, full 600/1200 DPI grids, anisotropic X/Y DPI, byte-level checks of the simulated GDI output, multi-page TIFF frame counts, conversion cache hit/invalidation, configuration recovery, pricing tier boundaries, and submission-state handling. **Real printers are not covered** — duplex flipping, margins, vendor quality and actual sharpness still need a physical sample print.

### Limitations

Windows only; heavily driver-dependent; printing is raster-then-driver, not vector pass-through; Office conversion is not pixel-identical to Word; the coverage figure is an estimate of inked area, not toner consumption.

### License

[MIT](LICENSE). Bundled Qt / PySide6 is distributed under LGPLv3 as dynamic libraries — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`.
