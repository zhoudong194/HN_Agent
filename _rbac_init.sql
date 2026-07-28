-- ============================================================
-- _rbac_init.sql — RBAC schema + seed data for HN_Agent
-- ============================================================
-- Creates schema `rbac` with tenants/users/roles/permissions and
-- a default tenant + admin user + two roles on first run.
-- Idempotent: safe to run multiple times.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS rbac;

-- ------------------------------------------------------------
-- Tables
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rbac.tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rbac.users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES rbac.tenants(id) ON DELETE CASCADE,
    email         TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    pw_hash       TEXT NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rbac.roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES rbac.tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    is_system   BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS rbac.permissions (
    key          TEXT PRIMARY KEY,
    description  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rbac.role_permissions (
    role_id        UUID NOT NULL REFERENCES rbac.roles(id) ON DELETE CASCADE,
    permission_key TEXT NOT NULL REFERENCES rbac.permissions(key) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_key)
);

CREATE TABLE IF NOT EXISTS rbac.user_roles (
    user_id  UUID NOT NULL REFERENCES rbac.users(id) ON DELETE CASCADE,
    role_id  UUID NOT NULL REFERENCES rbac.roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_rbac_users_tenant ON rbac.users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rbac_roles_tenant ON rbac.roles(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rbac_user_roles_user ON rbac.user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_rbac_role_permissions_role ON rbac.role_permissions(role_id);

-- ------------------------------------------------------------
-- Permission catalog (global, not per-tenant)
-- ------------------------------------------------------------
INSERT INTO rbac.permissions(key, description) VALUES
    ('policy:read',  '查询制度文档'),
    ('doc:write',    '上传/删除文档'),
    ('rbac:manage',  '管理本租户用户与角色')
ON CONFLICT (key) DO NOTHING;

-- ------------------------------------------------------------
-- Seed: default tenant + admin user + two roles
--   admin@example.com / admin123   (tenant_admin)
--   alice@example.com / alice123   (member) -- optional convenience
-- ------------------------------------------------------------
DO $$
DECLARE
    v_tenant_id UUID;
    v_admin_role_id UUID;
    v_member_role_id UUID;
    v_admin_user_id UUID;
BEGIN
    -- Pick or create the default tenant
    SELECT id INTO v_tenant_id FROM rbac.tenants WHERE name = 'Default Tenant' LIMIT 1;
    IF v_tenant_id IS NULL THEN
        INSERT INTO rbac.tenants(name) VALUES ('Default Tenant') RETURNING id INTO v_tenant_id;
    END IF;

    -- Create system roles for that tenant if missing
    INSERT INTO rbac.roles(tenant_id, name, is_system) VALUES (v_tenant_id, 'tenant_admin', true)
        ON CONFLICT (tenant_id, name) DO NOTHING;
    INSERT INTO rbac.roles(tenant_id, name, is_system) VALUES (v_tenant_id, 'member', true)
        ON CONFLICT (tenant_id, name) DO NOTHING;

    SELECT id INTO v_admin_role_id FROM rbac.roles WHERE tenant_id = v_tenant_id AND name = 'tenant_admin';
    SELECT id INTO v_member_role_id FROM rbac.roles WHERE tenant_id = v_tenant_id AND name = 'member';

    -- Bind permissions to roles
    INSERT INTO rbac.role_permissions(role_id, permission_key)
        SELECT v_admin_role_id, key FROM rbac.permissions
        ON CONFLICT DO NOTHING;
    INSERT INTO rbac.role_permissions(role_id, permission_key) VALUES
        (v_member_role_id, 'policy:read')
        ON CONFLICT DO NOTHING;

    -- Seed admin user (placeholder pw_hash; will be rewritten by Python with bcrypt)
    INSERT INTO rbac.users(tenant_id, email, display_name, pw_hash)
        VALUES (v_tenant_id, 'admin@example.com', 'Default Admin', '__SEED__PLACEHOLDER__')
        ON CONFLICT (email) DO NOTHING
        RETURNING id INTO v_admin_user_id;

    IF v_admin_user_id IS NULL THEN
        SELECT id INTO v_admin_user_id FROM rbac.users WHERE email = 'admin@example.com';
    END IF;

    INSERT INTO rbac.user_roles(user_id, role_id)
        VALUES (v_admin_user_id, v_admin_role_id)
        ON CONFLICT DO NOTHING;
END $$;