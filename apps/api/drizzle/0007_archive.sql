-- Archiving of fixture / stale objects and runs (M2 backlog item 6): hidden from lists and the dashboard by default.
ALTER TABLE "objects" ADD COLUMN IF NOT EXISTS "archived_at" timestamp with time zone;
--> statement-breakpoint
ALTER TABLE "runs" ADD COLUMN IF NOT EXISTS "archived_at" timestamp with time zone;
