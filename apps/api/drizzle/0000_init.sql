CREATE TABLE "files" (
	"id" varchar(512) PRIMARY KEY NOT NULL,
	"object_id" varchar(64) NOT NULL,
	"doc_stage" varchar(8),
	"discipline" varchar(32),
	"document_code" text,
	"revision" text,
	"approval_status" varchar(24),
	"approval_date" date,
	"predecessor_id" varchar(512),
	"file_hash" char(64) NOT NULL,
	"file_path" text,
	"uploaded_at" timestamp with time zone DEFAULT now() NOT NULL,
	"file_name" text NOT NULL,
	"ext" varchar(16),
	"size_bytes" bigint,
	"manifest_stage" varchar(16) NOT NULL,
	"manifest_section" varchar(32),
	"dataset_role" varchar(32),
	"split" varchar(16),
	"duplicate_group" text,
	"annotation_status" varchar(32),
	"pdf_pages" integer,
	"local_status" varchar(16) NOT NULL,
	"sha256_verified" boolean,
	"last_run_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "objects" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"name" text,
	"address" text,
	"customer" text,
	"contractor" text,
	"permit_number" text,
	"split" varchar(16),
	"object_group_id" varchar(64),
	"input_manifest_hash" char(64),
	"scenario" varchar(24),
	"indicator_color" varchar(8) DEFAULT 'NONE' NOT NULL,
	"indicator_reasons" jsonb,
	"indicator_updated_at" timestamp with time zone,
	"last_run_id" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "runs" (
	"id" uuid PRIMARY KEY NOT NULL,
	"batch_run_id" varchar(128) NOT NULL,
	"process_id" uuid,
	"mode" varchar(16),
	"producer" varchar(32) NOT NULL,
	"command" text,
	"status" varchar(16) NOT NULL,
	"config_hash" char(64) NOT NULL,
	"freeze_tag" text,
	"pipeline_version" text NOT NULL,
	"matrix_version" text,
	"dataset_version" text,
	"model_version" text,
	"engine_versions" jsonb,
	"versions" jsonb NOT NULL,
	"inputs" jsonb NOT NULL,
	"host" jsonb,
	"manifest_ref" text NOT NULL,
	"manifest_sha256" char(64) NOT NULL,
	"manifest" jsonb NOT NULL,
	"timings" jsonb,
	"import_warnings" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"objects_count" integer NOT NULL,
	"files_count" integer NOT NULL,
	"started_at" timestamp with time zone NOT NULL,
	"finished_at" timestamp with time zone,
	"imported_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "runs_batch_run_id_unique" UNIQUE("batch_run_id")
);
--> statement-breakpoint
ALTER TABLE "files" ADD CONSTRAINT "files_object_id_objects_id_fk" FOREIGN KEY ("object_id") REFERENCES "public"."objects"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "files" ADD CONSTRAINT "files_last_run_id_runs_id_fk" FOREIGN KEY ("last_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "objects" ADD CONSTRAINT "objects_last_run_id_runs_id_fk" FOREIGN KEY ("last_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "files_object_stage_idx" ON "files" USING btree ("object_id","manifest_stage");--> statement-breakpoint
CREATE INDEX "files_file_hash_idx" ON "files" USING btree ("file_hash");--> statement-breakpoint
CREATE INDEX "runs_imported_at_idx" ON "runs" USING btree ("imported_at");