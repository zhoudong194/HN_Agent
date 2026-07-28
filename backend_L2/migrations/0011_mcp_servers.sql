-- ============================================================
-- 0011_mcp_servers.sql — MCP Server & Tools management schema
-- ============================================================

CREATE TABLE IF NOT EXISTS rbac.mcp_servers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES rbac.tenants(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    identifier    TEXT NOT NULL,
    description   TEXT,
    config_json   JSONB NOT NULL DEFAULT '{}',
    is_enabled    BOOLEAN NOT NULL DEFAULT true,
    created_by    UUID REFERENCES rbac.users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, identifier)
);

CREATE TABLE IF NOT EXISTS rbac.mcp_tools (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id     UUID NOT NULL REFERENCES rbac.mcp_servers(id) ON DELETE CASCADE,
    tool_name     TEXT NOT NULL,
    description   TEXT,
    input_schema  JSONB NOT NULL DEFAULT '{}',
    is_enabled    BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(server_id, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_mcp_servers_tenant ON rbac.mcp_servers(tenant_id);
CREATE INDEX IF NOT EXISTS idx_mcp_tools_server ON rbac.mcp_tools(server_id);

-- MCP permissions
INSERT INTO rbac.permissions(key, description) VALUES
    ('mcp:manage', '管理 MCP Server 与工具'),
    ('mcp:use',   '调用 MCP 工具')
ON CONFLICT (key) DO NOTHING;

-- Bind MCP permissions to tenant_admin role
DO $$
DECLARE
    v_admin_role_id UUID;
BEGIN
    SELECT id INTO v_admin_role_id
    FROM rbac.roles
    WHERE name = 'tenant_admin'
    LIMIT 1;

    IF v_admin_role_id IS NOT NULL THEN
        INSERT INTO rbac.role_permissions(role_id, permission_key) VALUES
            (v_admin_role_id, 'mcp:manage'),
            (v_admin_role_id, 'mcp:use')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;
