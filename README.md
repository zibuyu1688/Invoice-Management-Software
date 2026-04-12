# 蜀丞票管

一个可离线运行、数据私有化的本地发票管理系统。

## 功能

- 多销售方（多纳税主体）管理
- 购买方客户信息管理
- 商品信息库管理
- 录入发票（电普/电专）
- 自动计算不含税、税额、价税合计
- 关联 PDF/OFD 文件并按年月归档
- 按日期/主体/类型/关键词筛选
- 导出筛选结果为 Excel

## 本地开发运行

1. 创建并激活环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 启动开发模式

```bash
python run_dev.py
```

4. 打开浏览器

- http://127.0.0.1:8765

## 快捷启动（macOS）

- 双击项目根目录下的 `启动发票管理.command`
- 首次运行会自动创建 `.venv` 并安装依赖
- 之后会自动启动服务并打开浏览器

说明：

- `run_dev.py`：开发调试入口（带热更新）
- `launcher.py`：应用启动入口（自动打开浏览器）

## 数据存储

程序数据默认保存在用户目录：

- `~/.invoice_manager/data/invoice.db`
- `~/.invoice_manager/files/`
- `~/.invoice_manager/exports/`

可通过环境变量 `INVOICE_APP_HOME` 自定义。

## 打包与交付（给客户）

目标：客户电脑无需安装 Python、插件或其它依赖，双击图标即可自动打开浏览器进入系统。

说明：构建脚本会自动生成应用图标，并绑定到 Windows EXE 和 macOS APP。

数据隔离说明：

- 打包产物只包含程序代码与静态资源，不包含当前机器的运行数据
- 数据库、附件和导出文件均在运行时写入用户目录（默认 `~/.invoice_manager`）
- 构建脚本已增加净包校验，若检测到 `invoice.db`、导出文件或附件被打入包内会直接失败

### Windows EXE

```bat
scripts\build_windows.bat
```

生成文件：

- `dist\蜀丞票管\蜀丞票管.exe`
- `dist\蜀丞票管-windows.zip`（建议发给 Windows 客户）

交付给 Windows 客户：

1. 发送 `dist\蜀丞票管-windows.zip`
2. 客户解压后双击 `蜀丞票管.exe`
3. 程序会自动启动并打开默认浏览器
4. 桌面/文件夹中会显示蜀丞票管图标

### macOS APP

```bash
chmod +x scripts/build_macos.sh scripts/create_dmg.sh
./scripts/build_macos.sh
```

生成文件：

- `dist/蜀丞票管.app`
- `dist/蜀丞票管-macos.zip`（建议发给 macOS 客户）

### macOS DMG

```bash
./scripts/create_dmg.sh
```

生成文件：`dist/蜀丞票管.dmg`

交付给 macOS 客户：

1. 推荐发送 `dist/蜀丞票管.dmg` 或 `dist/蜀丞票管-macos.zip`
2. 客户拖入应用程序后双击 `蜀丞票管.app`
3. 程序会自动启动并打开默认浏览器
4. 应用图标会显示为蜀丞票管品牌图标

## 双击启动行为

打包后的应用双击即会：

1. 在本机启动服务（默认从端口 `8765` 开始，若占用自动切换）
2. 自动打开默认浏览器访问系统首页

## 局域网跨设备访问

如果希望同事在同一局域网访问：

1. 在运行本程序的电脑上，允许防火墙放行端口 `8765`
2. 其他设备访问：`http://主机IP:8765`

示例：`http://192.168.1.100:8765`
