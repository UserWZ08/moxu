<div align="center">

<img src="assets/moxu.png" alt="墨序 MoXu" width="110" />

# 墨序 · MoXu

**面向社区打印店 / 自助打印点的 Windows 桌面工作台**

把客户的 PDF、Word、图片排进对的纸张，算对价钱，再稳稳交到打印机。

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
| 文件导入 | 拖放或选择 PDF / DOC(X) / XLS(X) / PPT(X) / JPG / PNG / BMP / TIF，批量导入，支持把多张图片合成一个双面页组 |
| 排版 | 按纸张实际毫米尺寸布局；自动方向（按首张选中页判定）；完整留白 / 填充裁切；PDF 自适应 / 仅缩小 / 实际大小 |
| 打印 | 单面 / 双面长边 / 双面短边；逐份提交以保证奇数页双面文档不串页；驱动拒绝参数时直接阻止提交，而不是静默降级 |
| 质量档位 | 全店统一"标准打印 / 高质量打印"两个档位，在后台按设备分别绑定为 DPI（惠普 600/1200）或厂商原生预设（爱普生等，通过 DEVMODE 抓取） |
| 计价 | 标价 + 可选的量大优惠（分段累进 / 满量降价），按纸张 × 颜色 × 单双面分别配置，按"面"或"张"计费，全程 `Decimal` 计算 |
| 客户档案 | 姓名 / 小区 / 楼栋 / 房号 / 手机 / QQ / 微信，拼音与首字母搜索，Excel 导入导出，历史订单保存客户快照 |
| 照片证件 | 身份证、户口本、证件照排版，5 寸 / 6 寸相纸，按实际尺寸打印 |
| 单据 | 可自定义的订单 HTML（标题、抬头、页脚、自定义图片），订单记录存 SQLite 并保留最近 500 单 |
| 可靠性 | 单实例锁；订单状态机（已创建 → 正在提交 → 已提交 / 需核对）；进程异常退出后遗留的"正在提交"会被自动标记为需人工核对队列 |

### 为什么值得一看

打印类桌面软件最难的不是界面，而是**同一份内容在四个地方长得一样**：屏幕预览、覆盖率估算、导出检查用的 PDF、真正发往驱动器的位图。这份代码把四者收敛到 `page_raster.Document.sheet()` 一个入口：

- PDF 与透明 PNG 先合成到白底，再转灰度 —— 修掉了"透明背景被当成黑色"这个经典坑（旧版会整页黑块，覆盖率飙到 100%）；
- 页码、方向旋转、纸张方向、驱动边距都在同一条坐标链上算，避免"预览 A4、出纸 A3"；
- 打印前先把光栅算完，再开始提交，失败时能明确停在"已提交几份"而不是"不知道打了没"。

### 技术栈

- **Python 3.13** + **PySide6 / Qt 6.8.3**（QtWidgets、QtPrintSupport、QtPdf、QtGui）
- **PyInstaller 6.22** 打包，**Inno Setup** 生成安装包
- **SQLite**（订单、客户）+ **JSON**（设置，原子写入 + 迁移）
- **PowerShell COM 自动化**调用 Word / Excel / PowerPoint 导出 PDF，批内复用实例，按内容指纹缓存
- **Win32 DEVMODE**（通过 `ctypes`）读取并写回厂商质量预设

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

首次启动会在 `%LOCALAPPDATA%\NeighbourPrint` 建好 `settings.json`、`orders.sqlite` 和转换缓存。免安装版则在程序目录放一个 `portable.flag`，数据会写到同目录的 `data\`。

### 打包

```powershell
# 1) 生成程序目录（程序-0.6\MoXu\）
.\build.ps1
# 2) 用 Inno Setup 编译安装包
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

`build.ps1` 会把 `licenses\` 与 `THIRD_PARTY_NOTICES.md` 一并复制进发行目录——Qt 以 LGPLv3 动态链接方式分发，替换库文件的权利必须随包保留。

### 测试

```powershell
python -m unittest test_core test_rendering test_business test_photos test_modernization test_print_safety -v
python test_ui.py      # 界面交互检查（需要图形环境）
```

覆盖的重点是那些"看起来对、打出来错"的地方：透明 PDF/PNG 白底、A4 原稿按实际大小放到 A3、自适应缩放、自动方向与双面翻页分离、Qt 输出 PDF 的物理尺寸、模拟 GDI 的逐字节检查、转换缓存的命中与失效、计价与阶梯边界。**注意：测试不覆盖真实打印机出纸**，实体设备的背面翻转、边距和厂商质量仍需样张验收。

### 目录结构

| 文件 | 职责 |
| --- | --- |
| `app.py` | 主窗口、导入/预览/计价/提交的编排 |
| `core.py` | 领域模型：配置校验与迁移、页码解析、打印机路由、报价、订单账本 |
| `pricing.py` / `catalog.py` | 标价与优惠的展开、纸张/装订目录 |
| `page_raster.py` | 唯一的纸张光栅布局：白底合成、方向、边距、缩放、导出 PDF |
| `page_layout.py` / `photo_layout.py` | 内容在纸面上的落位计算；证件/相纸排版 |
| `printing.py` | QPrinter 构造与参数校验、GDI/Qt 两条打印路径 |
| `windows_driver.py` / `driver_capture.py` | DEVMODE 读写、厂商质量预设捕获 |
| `quality.py` | "标准 / 高质量"到具体 DPI 或厂商预设的解析 |
| `coverage.py` | 150 DPI 的着色面积与平均色调估算 |
| `office.py` | Word/Excel/PPT → PDF（PowerShell COM 会话复用 + 内容指纹缓存） |
| `settings_ui.py` / `business_settings.py` | 后台设置（价格、打印机、纸张、装订、模板） |
| `customers.py` / `customer_ui.py` | 客户表、拼音搜索、Excel 往返 |
| `photo_ui.py` | 照片/证件排版工作台 |
| `receipt.py` | 订单 HTML 单据 |
| `controls.py` / `theme.py` | 自绘控件与明暗主题 |
| `remote_contract.py` | 未来局域网接入的请求校验（本版不监听端口） |
| `PrintDiagnostics.ps1` | 只读打印诊断脚本 |

### 数据与隐私

- 全部数据在本地：`%LOCALAPPDATA%\NeighbourPrint\{settings.json, orders.sqlite, cache\}`，免安装版在程序目录 `data\`。
- 不发起任何网络请求，不上传文件；`remote_contract.py` 只是尚未启用的接入校验。
- 关掉软件再升级；切换安装版/免安装版前先备份数据目录。

### 已知限制

- 仅 Windows，且深度依赖驱动行为：不同驱动对 DEVMODE、纸张、双面的支持差异很大，所以代码选择"校验不过就拒绝提交"。
- Office 转换无法保证与 Word 的排版逐像素一致，复杂文档建议先出 PDF。
- 覆盖率是**着色面积估算**，不是耗墨量，也不是厂商标准测试页。
- 0.6 的两档质量、双面短边、证件排版在中国市场的具体机型上仍需现场验收。
- 代码密度很高（`app.py` 475 行里有 401 个分号，`receipt.py` 单行最长 1231 字符），可读性一般，欢迎 PR 拆行、补类型标注。

### 许可证

[MIT](LICENSE)。打包的 Qt / PySide6 以 LGPLv3 动态链接分发，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 `licenses/`。

---

## English

### What is this

MoXu (墨序) is an **offline, single-machine desktop workbench for small print shops**. A clerk drops customer files into the window, picks paper, colour, simplex/duplex and quality; the app then routes the job to a capable printer, lays the content out on the physical sheet, previews it, prices it, writes an order receipt, and finally submits each copy to the Windows print queue.

No network, no uploads, no listening ports — settings, customers and orders stay on the machine. The goal is not merely "it prints", but **you know exactly how it will look and what it will cost before paper moves**. That is the central thread of the codebase: preview, coverage estimate, exportable proof PDF and the actual print bitmap all go through one white-background raster pipeline (`page_raster.Document.sheet`).

### Features

- **Import**: PDF, DOC(X), XLS(X), PPT(X), JPG/PNG/BMP/TIF, drag-and-drop, batch import; merge several images into one duplex page group.
- **Layout**: real millimetre paper sizes, automatic orientation from the first selected page, fill/crop vs. contain, PDF adaptive / shrink-only / actual size.
- **Printing**: simplex / duplex long-edge / short-edge; per-copy submission so odd-page duplex documents never bleed into each other; if the driver rejects a setting the job is blocked instead of silently downgraded.
- **Quality**: two store-wide levels ("standard" / "high"), each bound per printer either to a DPI value or to a vendor-native preset captured as a DEVMODE blob.
- **Pricing**: base price plus optional volume discounts (progressive or threshold), per paper × colour × simplex/duplex, per side or per sheet, all in `Decimal`.
- **Customers**: name / community / building / room / phone / QQ / WeChat, pinyin and initials search, Excel import/export, order snapshots.
- **ID photos**: ID card, household register, passport-photo sheets, 5"/6" photo paper, printed at actual size.
- **Receipts**: customisable order HTML, SQLite order ledger with the last 500 orders.
- **Robustness**: single-instance lock, order state machine, and orphaned "submitting" rows are flagged for manual queue checking after a crash.

### Tech stack

Python 3.13 · PySide6 / Qt 6.8.3 · PyInstaller · Inno Setup · SQLite + JSON · PowerShell COM automation for Word/Excel/PowerPoint → PDF · Win32 DEVMODE via `ctypes`.

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
.\build.ps1                                                  # PyInstaller -> 程序-0.6\MoXu\
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss   # installer
```

### Tests

```powershell
python -m unittest test_core test_rendering test_business test_photos test_modernization test_print_safety -v
python test_ui.py
```

The suite targets the "looks right, prints wrong" cases: transparent PDF/PNG compositing, A4-actual-size on A3, adaptive scaling, automatic orientation vs. duplex flipping, physical page size of the exported PDF, byte-level checks of the simulated GDI output, conversion cache hit/invalidation, and pricing tier boundaries. **Real printers are not covered** — duplex flipping, margins and vendor quality still need a physical sample print.

### Limitations

Windows only; heavily driver-dependent; Office conversion is not pixel-identical to Word; the coverage figure is an estimate of inked area, not toner consumption; 0.6's quality levels and ID-photo layouts still need field validation on real hardware.

### License

[MIT](LICENSE). Bundled Qt / PySide6 is distributed under LGPLv3 as dynamic libraries — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and `licenses/`.
