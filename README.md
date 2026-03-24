# ERA5 → CESM 大气强迫数据制备工具

将 ECMWF ERA5 再分析资料下载、预处理并转换为 CESM/CLM 大气强迫场（datm）所需的 NetCDF 格式。

## 产出文件

每个月生成 3 个文件：

| 文件 | 包含变量 | 说明 |
|---|---|---|
| `clmforc.0.1x0.1.prec-YYYY-MM.nc` | PRECTmms | 总降水率 (mm/s) |
| `clmforc.0.1x0.1.solar-YYYY-MM.nc` | FSDS | 入射短波辐射 (W/m²) |
| `clmforc.0.1x0.1.TPQWL-YYYY-MM.nc` | TBOT, PSRF, QBOT, WIND, FLDS | 温度、气压、比湿、风速、长波辐射 |

时间分辨率 3 小时，空间分辨率 0.1°，noleap 日历。

---

## 快速开始

### 1. 环境准备

```bash
# 安装 uv（如果还没有）
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux/Mac: curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装项目依赖
cd /path/to/download_ERA5
uv sync
```

### 2. 配置 CDS API 密钥

访问 https://cds.climate.copernicus.eu 注册账号，获取 API Key。

创建文件 `~/.cdsapirc`（Linux/Mac）或 `%USERPROFILE%\.cdsapirc`（Windows）：

```
url: https://cds.climate.copernicus.eu/api
key: <你的UID>:<你的API-Key>
```

### 3. 修改配置

编辑 `config.py`，根据你的需求修改以下参数：

```python
# 时间范围
START_YEAR = 2019
END_YEAR = 2023

# 空间范围（CDS API 格式：[北, 西, 南, 东]）
DOWNLOAD_AREA = [55, 114, 45, 124]

# CESM 目标网格范围和分辨率
TARGET_LAT = (45.1, 54.9)    # (南界, 北界)
TARGET_LON = (115.5, 124.0)  # (西界, 东界)
TARGET_RES = 0.1              # 度

# 输出路径
ERA5_RAW_DIR = r"G:\ERA5"                      # 原始下载
ERA5_PROCESSED_DIR = r"G:\ERA5_3h\processed"   # 预处理后
CESM_OUTPUT_DIR = r"G:\cesm_forc_data"         # 最终产出
```

### 4. 三步运行

```bash
python download.py      # Step 1: 从 CDS 下载 ERA5 数据
python preprocess.py    # Step 2: 小时 → 3小时重采样
python convert.py       # Step 3: 转换为 CESM 格式
```

每一步都支持 `--years` 参数指定年份，不指定则处理 config 中的全部年份：

```bash
python download.py --years 2020 2021
python preprocess.py --years 2020 --vars precipitation solar_radiation
python convert.py --years 2020
```

---

## 详细说明

### Step 1: 下载 (`download.py`)

从 Copernicus Climate Data Store 下载 8 个 ERA5 变量的逐小时数据。

**下载的变量：**

| 变量 | ERA5 名称 | 数据集 | 说明 |
|---|---|---|---|
| precipitation | total_precipitation | ERA5-Land | 总降水量 (m) |
| solar_radiation | surface_solar_radiation_downwards | ERA5-Land | 地表下行短波辐射 (J/m²) |
| longwave_flux | surface_thermal_radiation_downwards | ERA5 single-levels | 地表下行长波辐射 (J/m²) |
| surface_pressure | surface_pressure | ERA5 single-levels | 地表气压 (Pa) |
| 2m_temperature | 2m_temperature | ERA5 single-levels | 2米温度 (K) |
| 10m_u_wind | 10m_u_component_of_wind | ERA5 single-levels | 10米纬向风 (m/s) |
| 10m_v_wind | 10m_v_component_of_wind | ERA5 single-levels | 10米经向风 (m/s) |
| specific_humidity | specific_humidity @1000hPa | ERA5 pressure-levels | 比湿 (kg/kg) |

**输出文件**：`{ERA5_RAW_DIR}/{变量名}_{年份}.nc`

**特性**：
- 已存在的文件自动跳过，支持断点续下
- 每个变量每年一个文件，包含全年逐小时数据

**注意**：CDS 下载速度受限于服务器排队，8个变量 × 1年 可能需要数小时。建议后台运行或分批下载。

---

### Step 2: 预处理 (`preprocess.py`)

将逐小时 ERA5 数据重采样为 3 小时分辨率。

**处理逻辑因变量类型而异：**

#### 累积变量（降水、短波辐射、长波辐射）

这三个变量在 ERA5 中是累积量（J/m² 或 m），需要转换为 3 小时总量。

**关键特性——自动格式检测**：不同时期从 CDS 下载的数据格式可能不同：

| 数据格式 | 特征 | 处理方式 |
|---|---|---|
| **累积型**（旧版 CDS） | 值从预报初始时刻单调递增 | 先做差分得到每小时增量，再求 3h 总和 |
| **已反累积型**（新版 CDS） | 每小时值独立，不单调 | 直接求 3h 总和 |

脚本会自动检测并打印结果：
```
    detected: CUMULATIVE (from forecast init)
    detected: PER-HOUR (already de-accumulated)
```

运行时请关注此输出，确认检测结果与你的数据一致。

#### 瞬时变量（温度、气压、风、比湿）

直接每 3 小时取一个值（降采样），不做聚合。

**输出文件**：`{ERA5_PROCESSED_DIR}/{变量名}_{年份}_processed_3h.nc`

**其他特性**：
- 自动合并分月文件（如 `precipitation_2024.nc` + `precipitation_2024_12.nc`）
- 自动补齐到 12 月 31 日 21:00
- 已存在的输出文件自动跳过

---

### Step 3: 格式转换 (`convert.py`)

读取预处理后的 3 小时 ERA5 数据，插值到目标网格并转换为 CESM/CLM 可读格式。

**处理流程：**

1. 加载当年所有预处理文件
2. 逐月处理：
   - 双线性插值到目标网格（0.1°）
   - 单位转换（见下表）
   - 值域裁剪（如降水不允许负值）
   - NaN 填充为 -32767
   - 从 u10 和 v10 计算风速（√(u²+v²)）
3. 按变量分组写入 CESM 格式 NetCDF

**单位转换：**

| 变量 | ERA5 → CESM | 转换公式 |
|---|---|---|
| PRECTmms | m/3h → mm/s | × 1000 ÷ 10800 |
| FSDS | J·m⁻²/3h → W/m² | ÷ 10800 |
| FLDS | J·m⁻²/3h → W/m² | ÷ 10800 |
| TBOT | K → K | 不变 |
| PSRF | Pa → Pa | 不变 |
| QBOT | kg/kg → kg/kg | 不变 |
| WIND | m/s → m/s | 不变（但需从 u/v 合成） |

**输出 NetCDF 结构：**

```
维度:
    time    = 天数 × 8（如 1月 = 248, 2月 = 224）
    lat     = 目标网格纬度点数
    lon     = 目标网格经度点数

坐标变量:
    time    float32  "days since YYYY-MM-01 00:00:00", calendar="noleap"
    LONGXY  float32  (lat, lon)  二维经度网格
    LATIXY  float32  (lat, lon)  二维纬度网格
    EDGEN/EDGES/EDGEE/EDGEW     网格边界

数据变量:
    各变量  float32  (time, lat, lon)  _FillValue = -32767.0

全局属性:
    case_title   = "{组名} atmospheric forcing data for CESM"
    source_file  = "Converted from ERA5 for YYYY-MM"
```

**日历说明**：使用 noleap 日历（365 天/年），二月固定 28 天，即使原始 ERA5 数据中该年是闰年。

---

### 检查工具 (`inspect_nc.py`)

快速查看任意 NetCDF 文件的结构和内容。

```bash
# 查看单个文件
python inspect_nc.py G:\cesm_forc_data\clmforc.0.1x0.1.TPQWL-2020-01.nc

# 查看目录下所有 .nc 文件
python inspect_nc.py G:\cesm_forc_data

# 包含数据统计（min/max/mean/std/NaN%）
python inspect_nc.py G:\cesm_forc_data --detail
```

---

## CESM 端配置参考

生成的强迫数据需要在 CESM 的 datm 中配置三个 stream：

| Stream | 文件 | 插值方式 (tintalgo) | 时间偏移 |
|---|---|---|---|
| Solar | `*.solar-*.nc` | `coszen`（太阳天顶角加权） | -10800 s |
| Precip | `*.prec-*.nc` | `nearest`（最近邻） | -5400 s |
| TPQW | `*.TPQWL-*.nc` | `linear`（线性插值） | -5400 s |

时间偏移量假设数据时间戳标记的是时段末尾；`coszen` 用于太阳辐射的日变化订正。

---

## 文件结构

```
download_ERA5/
├── config.py          # 配置文件（修改这里）
├── download.py        # Step 1: 下载
├── preprocess.py      # Step 2: 预处理
├── convert.py         # Step 3: 格式转换
├── inspect_nc.py      # 工具: 检查 NetCDF
├── pyproject.toml     # Python 依赖
├── README.md          # 本文档
└── _archive/          # 旧版代码（可删除）
```

## 依赖

- Python >= 3.10
- cdsapi（CDS API 客户端）
- netcdf4（NetCDF 读写）
- numpy
- pandas
- xarray（NetCDF 高级操作）

使用 `uv sync` 一键安装。

---

## 常见问题

### Q: CDS 下载报错 / API 连不上？

确认 `~/.cdsapirc` 文件内容正确，且账号已接受 CDS 的数据许可协议。新版 CDS（2024 年后）的 URL 可能需要改为 `https://cds-beta.climate.copernicus.eu/api`。

### Q: 预处理时打印的 detected 结果不对？

如果你确定数据是累积型但检测为 PER-HOUR（或反之），可以在 `config.py` 的变量定义中将 `"cumulative"` 字段改为 `False`（跳过差分，直接求和）或 `True`（强制做差分）。但一般来说自动检测是可靠的。

### Q: 如何更换研究区域？

修改 `config.py` 中的 3 组空间参数：
1. `DOWNLOAD_AREA` — 下载范围（应比目标网格稍大）
2. `TARGET_LAT` / `TARGET_LON` — CESM 目标网格范围
3. 确保下载范围完全覆盖目标网格

### Q: 如何增减变量？

在 `config.py` 的 `VARIABLES` 字典中增删条目即可。每个条目需要指定 CDS 下载参数和 CESM 映射参数。风速（WIND）的配置在单独的 `WIND` 字典中。

### Q: 二月数据天数不对？

`convert.py` 使用 noleap 日历，二月固定生成 28 × 8 = 224 个时间步。这是 CESM 标准行为，不需要手动修正。
