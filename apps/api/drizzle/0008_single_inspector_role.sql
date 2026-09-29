-- Product owner decision 29.09: the product has ONE role, INSPECTOR (super-role). Every existing user is moved to it;
-- users are never deleted (decisions and audit rows reference them).
DELETE FROM "user_roles" WHERE "role_code" <> 'INSPECTOR';
--> statement-breakpoint
INSERT INTO "user_roles" ("user_id", "role_code")
SELECT "id", 'INSPECTOR' FROM "users"
ON CONFLICT DO NOTHING;
