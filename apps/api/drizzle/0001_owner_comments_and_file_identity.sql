-- Owner tags (90 §3.3.1 W5) and the file-identity invariant (90 §3.3.2: same file_id + another hash → 409).
COMMENT ON TABLE "runs" IS 'owner=B00; M0: one row per imported inspector-batch run directory (AG-08 import)';--> statement-breakpoint
COMMENT ON TABLE "objects" IS 'owner=B01; ТЗ §10 table 3 + extensions (90 §3.3.3)';--> statement-breakpoint
COMMENT ON TABLE "files" IS 'owner=B01; ТЗ §10 table 4 + 97 §2.8 manifest fields';--> statement-breakpoint
COMMENT ON COLUMN "files"."file_hash" IS 'SHA-256 of the file bytes; immutable per file_id';--> statement-breakpoint
COMMENT ON COLUMN "files"."local_status" IS 'LocalFileStatus: PRESENT | RECOVERED | MISSING_ON_DISK (never MISSING_DOCUMENT)';--> statement-breakpoint
CREATE OR REPLACE FUNCTION files_identity_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.object_id IS DISTINCT FROM OLD.object_id
     OR NEW.file_hash IS DISTINCT FROM OLD.file_hash THEN
    RAISE EXCEPTION 'FILE_ID_IMMUTABLE: file % cannot change id, object_id or file_hash', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;--> statement-breakpoint
CREATE TRIGGER files_identity_immutable
  BEFORE UPDATE ON "files"
  FOR EACH ROW EXECUTE FUNCTION files_identity_immutable();
