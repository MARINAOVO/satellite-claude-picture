# 卫星云图自主读取小程序

这是一个 Windows 桌面小程序，用 NASA GIBS/Worldview 公共影像读取全球卫星云图，并自动估算云量和最近几天变化趋势。结果是“影像估算”，适合辅助判读云图，不等同于气象站或数值预报产品。

## 运行方式

1. 安装 Python 3.12：https://www.python.org/downloads/
2. 在当前文件夹打开 PowerShell。
3. 双击 `run.bat`，或在当前文件夹打开 PowerShell 后运行：

```powershell
.\run.ps1
```

脚本会自动创建 `.venv` 环境并安装依赖。

如果 PowerShell 提示禁止运行脚本，可以改用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

如果只想安装环境，不启动程序，可以运行：

```powershell
.\install.ps1
```

## 使用方式

- 左侧地图默认使用 NASA Blue Marble 真实底图；配置 Google Maps API Key 后可切换为 Google 地图。
- 在地图上拖动框选区域；鼠标滚轮缩放，左键双击放大，右键或中键拖动平移。
- 点击“放大”“缩小”“缩放到选区”“复位”可以更精细地选择小区域。
- 也可以点击“中国/东亚、欧洲、北美、南美、全球”等快捷区域。
- 也可以直接输入经纬度范围，作为精确选择或极区备用方式。
- 点击“获取最新”，程序会从所选日期开始向前查找最近可用 NASA 云图。
- 点击“导出报告”，会在 `reports/` 中保存图片和文字报告。

界面会显示云图预览、估算云量、趋势、可信度、实用天气分析、使用图层、有效覆盖率和最近有效影像记录。
实用天气分析包括天空状况、降水可能、短时变化、出行建议、户外建议和晾晒建议。

## Google 地图

Google 地图需要你自己的 Google Maps JavaScript API Key。程序不会自带 Key，也不会绕过 Google 的用量和结算要求。

配置方式任选一种：

1. 在界面里的 `Google Maps API Key` 输入框填入 Key，然后点击“应用地图”。
2. 或在 `config.json` 中填写：

```json
"google_maps_api_key": "你的 Key"
```

3. 或设置环境变量：

```powershell
$env:GOOGLE_MAPS_API_KEY="你的 Key"
.\run.bat
```

如果 Key 为空、Key 无效、网络访问 Google 失败，程序会继续使用 NASA Blue Marble 底图框选，不影响 NASA 云图下载和分析。

## 数据源

使用 NASA GIBS WMS 公共服务，无需 API Key：

- 服务入口：https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi
- 文档：https://nasa-gibs.github.io/gibs-api-docs/

默认图层顺序：

- `MODIS_Aqua_Cloud_Fraction_Day`
- `MODIS_Terra_Cloud_Fraction_Day`
- `MODIS_Aqua_CorrectedReflectance_TrueColor`
- `MODIS_Terra_CorrectedReflectance_TrueColor`

## 本地目录

- `cache/`：NASA 图片和请求元数据缓存。
- `reports/`：导出的云图和文字报告。
- `config.json`：默认区域、图层顺序和趋势阈值。

## 打包 exe

安装好 Python 后运行：

```powershell
.\build_exe.bat
```

打包结果会生成在 `dist/` 目录。
