-- Platform invariants (AG-00, M1): owner tags (90 §3.3.1 W5), append-only Audit_Log (09 §3.4.3, 90 W4),
-- immutable protocol versions (09 §3.4.5, 90 §3.2.3).
COMMENT ON TABLE "users" IS 'owner=B09 (AG-00); accounts, argon2id password hashes';--> statement-breakpoint
COMMENT ON TABLE "user_roles" IS 'owner=B09 (AG-00); Role codes per user; permissions live in packages/contracts/rbac.yaml';--> statement-breakpoint
COMMENT ON TABLE "object_assignments" IS 'owner=B09 (AG-00); inspector visibility for ASSIGNED-scoped permissions';--> statement-breakpoint
COMMENT ON TABLE "audit_log" IS 'owner=B09 (AG-00); ТЗ §10 table 12, append-only (UPDATE/DELETE/TRUNCATE raise; purge only via audit_purge_expired)';--> statement-breakpoint
COMMENT ON TABLE "processes" IS 'owner=B00; one per imported run × object (source BATCH_IMPORT)';--> statement-breakpoint
COMMENT ON TABLE "process_files" IS 'owner=B00; files of a process';--> statement-breakpoint
COMMENT ON TABLE "protocols" IS 'owner=B04; ТЗ §10 table 5, immutable versions (content_json = Protocol contract)';--> statement-breakpoint
COMMENT ON TABLE "protocol_exports" IS 'owner=B04; protocol artifacts (json/docx/pdf) as claim checks';--> statement-breakpoint
COMMENT ON TABLE "evidence_groups" IS 'owner=B04; FindingGroup rows (evidence_group_id = finding_group_id)';--> statement-breakpoint
COMMENT ON TABLE "checks" IS 'owner=B04 (machine columns, import) / B05 (inspector columns); ТЗ §10 table 2';--> statement-breakpoint
COMMENT ON TABLE "evidence_fragments" IS 'owner=B04; ТЗ §10 table 14; SYSTEM rows from the import, INSPECTOR rows from verification';--> statement-breakpoint
COMMENT ON TABLE "suspicions" IS 'owner=B07; ТЗ §10 table 8; FREE_SEARCH finding groups';--> statement-breakpoint
COMMENT ON TABLE "submission_exports" IS 'owner=B04; 97 §2.8; imported submission (full, strict) with sidecar; never written from decisions';--> statement-breakpoint
COMMENT ON TABLE "run_artifacts" IS 'owner=B00; artifacts.json of an imported run (claim-check references)';--> statement-breakpoint

-- Audit_Log is append-only. The only way out is audit_purge_expired(), which sets a transaction-local flag.
CREATE OR REPLACE FUNCTION audit_log_block_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('inspector.audit_purge', true) = 'on' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'AUDIT_LOG_APPEND_ONLY: % on audit_log is not allowed', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$;--> statement-breakpoint
CREATE TRIGGER audit_log_block_update_delete
  BEFORE UPDATE OR DELETE ON "audit_log"
  FOR EACH ROW EXECUTE FUNCTION audit_log_block_mutation();--> statement-breakpoint
CREATE TRIGGER audit_log_block_truncate
  BEFORE TRUNCATE ON "audit_log"
  FOR EACH STATEMENT EXECUTE FUNCTION audit_log_block_mutation();--> statement-breakpoint

-- Retention (09 §3.4.3): STANDARD 90 days, SECURITY 365 days, PERMANENT never. Writes RETENTION_PURGE_EXECUTED.
CREATE OR REPLACE FUNCTION audit_purge_expired(standard_days integer DEFAULT 90, security_days integer DEFAULT 365)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
  purged integer;
BEGIN
  PERFORM set_config('inspector.audit_purge', 'on', true);
  DELETE FROM "audit_log"
   WHERE ("retention_class" = 'STANDARD' AND "timestamp" < now() - make_interval(days => standard_days))
      OR ("retention_class" = 'SECURITY' AND "timestamp" < now() - make_interval(days => security_days));
  GET DIAGNOSTICS purged = ROW_COUNT;
  PERFORM set_config('inspector.audit_purge', 'off', true);
  INSERT INTO "audit_log" ("action", "actor_type", "category", "result", "retention_class", "details")
  VALUES ('RETENTION_PURGE_EXECUTED', 'SYSTEM', 'SYSTEM', 'SUCCESS', 'PERMANENT',
          jsonb_build_object('purged', purged, 'standard_days', standard_days, 'security_days', security_days));
  RETURN purged;
END;
$$;--> statement-breakpoint

-- A protocol version is a snapshot: content, version and process never change; a finalized version may only be
-- superseded; versions are never deleted.
CREATE OR REPLACE FUNCTION protocols_version_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'PROTOCOL_VERSION_IMMUTABLE: protocol version % cannot be deleted', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.process_id IS DISTINCT FROM OLD.process_id
     OR NEW.version IS DISTINCT FROM OLD.version
     OR NEW.content_json IS DISTINCT FROM OLD.content_json
     OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256 THEN
    RAISE EXCEPTION 'PROTOCOL_VERSION_IMMUTABLE: content of protocol version % cannot change', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status = 'PROTOCOL_FINALIZED'
     AND (NEW.status NOT IN ('PROTOCOL_FINALIZED', 'SUPERSEDED')
          OR NEW.finalized_at IS DISTINCT FROM OLD.finalized_at
          OR NEW.finalized_by IS DISTINCT FROM OLD.finalized_by) THEN
    RAISE EXCEPTION 'PROTOCOL_FINALIZED: finalized protocol version % can only be superseded', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;--> statement-breakpoint
CREATE TRIGGER protocols_version_immutable
  BEFORE UPDATE OR DELETE ON "protocols"
  FOR EACH ROW EXECUTE FUNCTION protocols_version_immutable();
