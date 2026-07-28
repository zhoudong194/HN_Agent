"""
biz_mcp/init_data.py — Register built-in MCP Servers (e.g., Amap).
Called on app startup via main.py.
"""

import logging

log = logging.getLogger(__name__)


def register_builtin_mcp() -> None:
    """Register all built-in MCP Servers with the registry."""
    from biz_mcp.registry import MCPRegistry, ToolDef

    amap_tools = [
        ToolDef(
            name="maps_weather",
            description="根据城市名称或者标准adcode查询指定城市的天气",
            input_schema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称或者adcode",
                    }
                },
                "required": ["city"],
            },
        ),
        ToolDef(
            name="maps_text_search",
            description="关键字搜索 API 根据用户输入的关键字进行 POI 搜索",
            input_schema={
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "查询关键字"},
                    "city": {"type": "string", "description": "查询城市"},
                    "citylimit": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否限制城市范围内搜索",
                    },
                },
                "required": ["keywords"],
            },
        ),
        ToolDef(
            name="maps_around_search",
            description="周边搜，根据用户传入关键词以及坐标搜索出半径范围的POI",
            input_schema={
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "搜索关键词"},
                    "location": {"type": "string", "description": "中心点经度纬度"},
                    "radius": {"type": "string", "description": "搜索半径"},
                    "strategy": {
                        "type": "integer",
                        "default": 0,
                        "description": "召回策略",
                    },
                },
                "required": ["keywords", "location"],
            },
        ),
        ToolDef(
            name="maps_search_detail",
            description="查询关键词搜或者周边搜获取到的POI ID的详细信息",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "关键词搜或者周边搜获取到的POI ID",
                    }
                },
                "required": ["id"],
            },
        ),
        ToolDef(
            name="maps_geo",
            description="将详细的结构化地址转换为经纬度坐标",
            input_schema={
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "待解析的结构化地址信息",
                    },
                    "city": {"type": "string", "description": "指定查询的城市"},
                },
                "required": ["address"],
            },
        ),
        ToolDef(
            name="maps_direction_driving",
            description="驾车路径规划，根据起终点经纬度坐标规划出行方案",
            input_schema={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "出发点经纬度，格式为：经度，纬度",
                    },
                    "destination": {
                        "type": "string",
                        "description": "目的地经纬度，格式为：经度，纬度",
                    },
                },
                "required": ["origin", "destination"],
            },
        ),
        ToolDef(
            name="maps_direction_walking",
            description="根据输入起点终点经纬度坐标规划100km以内的步行通勤方案",
            input_schema={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "出发点经纬度，格式为：经度，纬度",
                    },
                    "destination": {
                        "type": "string",
                        "description": "目的地经纬度，格式为：经度，纬度",
                    },
                },
                "required": ["origin", "destination"],
            },
        ),
        ToolDef(
            name="maps_direction_bicycling",
            description="骑行路线规划",
            input_schema={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "出发点经纬度，格式为：经度，纬度",
                    },
                    "destination": {
                        "type": "string",
                        "description": "目的地经纬度，格式为：经度，纬度",
                    },
                },
                "required": ["origin", "destination"],
            },
        ),
        ToolDef(
            name="maps_direction_transit_integrated",
            description="公共交通综合规划（火车、公交、地铁），跨城场景需传城市",
            input_schema={
                "type": "object",
                "properties": {
                    "origin": {
                        "type": "string",
                        "description": "出发点经纬度，格式为：经度，纬度",
                    },
                    "destination": {
                        "type": "string",
                        "description": "目的地经纬度，格式为：经度，纬度",
                    },
                    "city": {"type": "string", "description": "公共交通规划起点城市"},
                    "cityd": {
                        "type": "string",
                        "description": "公共交通规划终点城市",
                    },
                },
                "required": ["origin", "destination", "city", "cityd"],
            },
        ),
        ToolDef(
            name="maps_distance",
            description="测量两个经纬度坐标之间的距离，支持驾车、步行以及球面距离测量",
            input_schema={
                "type": "object",
                "properties": {
                    "origins": {
                        "type": "string",
                        "description": "起点经纬度，可传多个，使用竖线隔离",
                    },
                    "destination": {
                        "type": "string",
                        "description": "终点经纬度",
                    },
                    "type": {
                        "type": "string",
                        "description": "距离测量类型：1=驾车，0=直线，3=步行",
                    },
                },
                "required": ["origins", "destination"],
            },
        ),
        ToolDef(
            name="maps_ip_location",
            description="IP 定位，根据用户输入的 IP 地址定位其所在位置",
            input_schema={
                "type": "object",
                "properties": {
                    "ip": {"type": "string", "description": "IP地址"}
                },
                "required": ["ip"],
            },
        ),
        ToolDef(
            name="maps_regeocode",
            description="逆地理编码，根据经纬度获取结构化地址",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "经纬度坐标，格式为：经度，纬度",
                    },
                    "poitype": {
                        "type": "string",
                        "description": "POI类型，多个用逗号分隔",
                    },
                },
                "required": ["location"],
            },
        ),
    ]

    MCPRegistry.register(
        identifier="amap-maps-streamableHTTP",
        name="高德地图",
        description="集成高德地图服务，包含搜索、路线规划、天气查询等功能",
        tools=amap_tools,
        config_schema={
            "type": "object",
            "properties": {
                "amap_key": {
                    "type": "string",
                    "description": "高德地图 API Key",
                    "secret": True,
                },
                "base_url": {
                    "type": "string",
                    "description": "MCP Server 地址，默认使用本地",
                },
            },
        },
    )

    log.info(
        "[MCP] Registered Amap MCP with %d tools",
        len(amap_tools),
    )


def seed_builtin_servers() -> None:
    """Ensure built-in MCP Servers exist in the DB (idempotent)."""
    from biz_mcp.server import repository as repo
    from biz_mcp.server import service as svc
    from biz_mcp.registry import MCPRegistry

    try:
        with repo._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, tenant_id FROM rbac.users WHERE email='admin@example.com' LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                log.warning("[MCP] Cannot seed servers: admin user not found")
                return
            admin_id = str(row[0])
            tenant_id = str(row[1])

        existing = repo.list_by_tenant(tenant_id)
        if any(s["identifier"] == "amap-maps-streamableHTTP" for s in existing):
            log.info("[MCP] Amap server already seeded, skipping")
            return

        server_def = MCPRegistry.get("amap-maps-streamableHTTP")
        if server_def is None:
            log.warning("[MCP] Amap not in registry, skipping DB seed")
            return

        server = repo.create(
            tenant_id=tenant_id,
            name=server_def.name,
            identifier=server_def.identifier,
            description=server_def.description or "",
            config_json={"amap_key": ""},
            created_by=admin_id,
        )

        tools = [
            {
                "tool_name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in server_def.tools
        ]
        repo.upsert_tools(str(server["id"]), tools)
        log.info(
            "[MCP] Seeded Amap server (id=%s) with %d tools",
            server["id"], len(tools),
        )
    except Exception as e:
        log.warning("[MCP] Seed builtin servers failed: %s", e)
