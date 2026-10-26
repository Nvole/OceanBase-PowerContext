# 高德 MCP 工具名核对

核对日期：2026-10-26。只读文档和开源实现中的工具定义，没有调用高德 API，没有把他人仓库当作提交物。参赛文件是本目录的 `SKILL.md`。

## 官方能力

[MCP Server 概述](https://developer.amap.com/api/mcp-server/summary)（页面所标最后更新：2026-03-17）给出的相关能力：

| 官方能力 | 输入 | 输出 |
| --- | --- | --- |
| 周边搜索 | keywords、location、radius | pois |
| 关键词搜索 | keywords、city（非必须） | suggestion、pois |
| 步行路径规划 | origin、destination | origin、destination、paths |
| 详情搜索 | id | location、address、business_area、city、type 等 |

[快速接入](https://lbs.amap.com/api/mcp-server/gettingstarted) 使用 `@amap/amap-maps-mcp-server`，或 Streamable HTTP `https://mcp.amap.com/mcp`。密钥由平台配置。Skill 不写 Key，也不写接入配置。

## 官方包中的工具名

`@amap/amap-maps-mcp-server@0.0.8` 的 `build/index.js` 与魔搭上的官方 `@amap/amap-maps` 使用同一组工具名。本题实际调用：

| 工具名 | 参数 | 本题用法 |
| --- | --- | --- |
| `maps_around_search` | `location` 必填；`keywords`、`radius` 选填。`radius` 缺省按 1000 米处理 | 按起点坐标和地点类型召回附近 POI |
| `maps_text_search` | `keywords` 必填；schema 另有 `city`、`types` | 仅当周边搜索成功但结果为空时补充一次 |
| `maps_search_detail` | `id` 必填 | 搜索结果不含坐标时取得 `location` |
| `maps_direction_walking` | `origin`、`destination`，格式均为“经度,纬度” | 唯一允许作为步行距离和时间来源的工具 |

该版本周边搜索和关键词搜索返回的 POI 字段是 `id`、`name`、`address`、`typecode`，不带 `location`。详情返回 `location`。步行结果在 `route.paths[]`：`distance` 为米，`duration` 为秒。托管端若已经在 POI 中返回坐标，可以跳过详情，但仍必须查步行路线。

`maps_distance` 的 `type`：`0` 直线，`1` 驾车，`3` 步行测距。它不是步行路径规划，本题禁止用它或直线距离填报到达时间。

同包其余工具（`maps_geo`、`maps_regeocode`、`maps_ip_location`、`maps_weather`、`maps_bicycling`、`maps_direction_driving`、`maps_direction_transit_integrated`）不作为默认流程。`maps_geo` 只在用户完全没给坐标、只给起点地名时使用。禁止用 `maps_ip_location` 做设备定位。

## 不能照搬的开源命名

下列仓库只用于确认“名字不一致”，没有复制进提交目录：

| 仓库 | 不一致的工具名 | 处理 |
| --- | --- | --- |
| `sugarforever/amap-mcp-server` | `maps_direction_walking_by_coordinates`、`maps_direction_walking_by_address` | 不使用。评测环境的步行工具是 `maps_direction_walking` |
| `zengzeruidd-a11y/amap-mcp-server` | `amap_poi_around`、`amap_direction_walking` | 不使用 |
| `luodora/mcp-amap` | `search_around`、`walking_route` | 不使用 |

Skill 中的调用名固定为官方 MCP 的 `maps_around_search`、`maps_text_search`、`maps_search_detail` 和 `maps_direction_walking`。
