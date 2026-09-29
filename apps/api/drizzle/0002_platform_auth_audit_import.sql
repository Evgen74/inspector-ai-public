CREATE TABLE "object_assignments" (
	"object_id" varchar(64) NOT NULL,
	"user_id" uuid NOT NULL,
	"assigned_by" uuid,
	"assigned_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "object_assignments_object_id_user_id_pk" PRIMARY KEY("object_id","user_id")
);
--> statement-breakpoint
CREATE TABLE "user_roles" (
	"user_id" uuid NOT NULL,
	"role_code" varchar(32) NOT NULL,
	"granted_by" uuid,
	"granted_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "user_roles_user_id_role_code_pk" PRIMARY KEY("user_id","role_code")
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" uuid PRIMARY KEY NOT NULL,
	"login" varchar(64) NOT NULL,
	"password_hash" text NOT NULL,
	"full_name" text NOT NULL,
	"position" text,
	"email" text,
	"is_active" boolean DEFAULT true NOT NULL,
	"must_change_password" boolean DEFAULT false NOT NULL,
	"failed_login_count" integer DEFAULT 0 NOT NULL,
	"locked_until" timestamp with time zone,
	"last_login_at" timestamp with time zone,
	"password_changed_at" timestamp with time zone,
	"password_history" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"is_demo" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"deactivated_at" timestamp with time zone,
	CONSTRAINT "users_login_unique" UNIQUE("login")
);
--> statement-breakpoint
CREATE TABLE "audit_log" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"user_id" uuid,
	"action" varchar(64) NOT NULL,
	"object_id" text,
	"details" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"timestamp" timestamp with time zone DEFAULT now() NOT NULL,
	"ip_address" "inet",
	"user_agent" text,
	"actor_type" varchar(16) NOT NULL,
	"actor_role" varchar(128),
	"actor_login" varchar(64),
	"category" varchar(16) NOT NULL,
	"result" varchar(8) NOT NULL,
	"object_type" varchar(32),
	"construction_object_id" varchar(64),
	"process_id" uuid,
	"protocol_version" integer,
	"request_id" varchar(128),
	"session_ref" char(16),
	"http_method" varchar(8),
	"route" text,
	"status_code" integer,
	"duration_ms" integer,
	"retention_class" varchar(12) NOT NULL
);
--> statement-breakpoint
CREATE TABLE "checks" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"process_id" uuid NOT NULL,
	"param_id" integer,
	"object_id" varchar(64) NOT NULL,
	"expected_value" jsonb,
	"actual_value" jsonb,
	"completeness_status" varchar(32),
	"finding_status" varchar(24),
	"review_priority" varchar(8),
	"evidence_group_id" varchar(96),
	"finding_id" varchar(96) NOT NULL,
	"kind" varchar(24) NOT NULL,
	"matrix_scope" varchar(16) NOT NULL,
	"param_code" varchar(32) NOT NULL,
	"sub_id" text,
	"rule_code" text,
	"rule_version" text,
	"parameter_mapping_status" varchar(40),
	"alt_param_codes" text[] DEFAULT '{}'::text[] NOT NULL,
	"hedge_of_finding_id" varchar(96),
	"hedge_kind" varchar(32),
	"location" text NOT NULL,
	"location_type" varchar(16) NOT NULL,
	"pd_value" jsonb,
	"rd_value" jsonb,
	"id_value" jsonb,
	"axis" varchar(8),
	"comparison_result" varchar(32),
	"discrepancy_type" varchar(32),
	"violation_type" varchar(32),
	"completeness_basis" varchar(48),
	"violation_label" varchar(24) NOT NULL,
	"protocol_status" varchar(24) NOT NULL,
	"criticality" text,
	"criticality_level" varchar(24),
	"risk_level" varchar(8),
	"document_status" varchar(32),
	"confidence" numeric(4, 3),
	"element_noun" text,
	"discovery_method" varchar(32),
	"evidence_bind_status" varchar(16),
	"recommendation" jsonb,
	"card_no" varchar(16),
	"delta" jsonb,
	"rationale" text,
	"decision_trace" jsonb,
	"source_suspicion_id" bigint,
	"finding_json" jsonb NOT NULL,
	"finding_sha256" char(64) NOT NULL,
	"lifecycle_state" varchar(16) DEFAULT 'ACTIVE' NOT NULL,
	"inspector_status" varchar(32),
	"decided_by" varchar(16),
	"decided_user_id" uuid,
	"decided_at" timestamp with time zone,
	"decision_reason_code" varchar(48),
	"decision_basis_code" varchar(48),
	"decision_comment" text,
	"current_decision_id" uuid,
	"review_required_reason" varchar(32),
	"new_evidence_available" boolean DEFAULT false NOT NULL,
	"first_protocol_version" integer,
	"last_protocol_version" integer,
	"run_id" uuid,
	"row_version" integer DEFAULT 1 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "checks_process_finding_uq" UNIQUE("process_id","finding_id")
);
--> statement-breakpoint
CREATE TABLE "evidence_fragments" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"process_id" uuid NOT NULL,
	"fragment_key" char(64) NOT NULL,
	"evidence_group_id" varchar(96),
	"file_id" varchar(512) NOT NULL,
	"stage" varchar(4) NOT NULL,
	"sheet_page" text NOT NULL,
	"bbox_polygon_norm" jsonb,
	"extracted_value" text,
	"role_expected_actual" varchar(24),
	"check_id" bigint,
	"finding_id" varchar(96),
	"suspicion_id" bigint,
	"location" text,
	"is_anchor" boolean DEFAULT false NOT NULL,
	"file_sha256" char(64),
	"page_no" integer NOT NULL,
	"sheet_no" text,
	"page_basis" varchar(24),
	"geometry_space" varchar(32),
	"localization" varchar(16),
	"document_code" text,
	"revision" text,
	"extracted_value_id" text,
	"note" text,
	"origin" varchar(16) DEFAULT 'SYSTEM' NOT NULL,
	"created_by" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "evidence_fragments_process_key_uq" UNIQUE("process_id","fragment_key")
);
--> statement-breakpoint
CREATE TABLE "evidence_groups" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"process_id" uuid NOT NULL,
	"evidence_group_id" varchar(96) NOT NULL,
	"object_id" varchar(64) NOT NULL,
	"matrix_scope" varchar(16) NOT NULL,
	"param_id" integer,
	"param_code" varchar(32) NOT NULL,
	"parameter_mapping_status" varchar(40),
	"alt_param_codes" text[] DEFAULT '{}'::text[] NOT NULL,
	"hedge_kind" varchar(32),
	"hedge_of_group_id" varchar(96),
	"title" text,
	"element_noun" text,
	"axis" varchar(8),
	"comparison_result" varchar(32) NOT NULL,
	"discrepancy_type" varchar(32),
	"location_type" varchar(16) NOT NULL,
	"locations" text[] NOT NULL,
	"pd_value" jsonb,
	"rd_value" jsonb,
	"id_value" jsonb,
	"violation_label" varchar(24) NOT NULL,
	"protocol_status" varchar(24) NOT NULL,
	"criticality" text,
	"criticality_level" varchar(24),
	"finding_status" varchar(24),
	"risk_level" varchar(8),
	"confidence" numeric(4, 3),
	"anchor_evidence" jsonb NOT NULL,
	"location_pages" jsonb,
	"finding_ids" text[] NOT NULL,
	"discovery_method" varchar(32),
	"evidence_bind_status" varchar(16),
	"rule_code" text,
	"rule_version" text,
	"rationale" text,
	"recommendation" jsonb,
	"card_no" varchar(16),
	"group_json" jsonb NOT NULL,
	"group_sha256" char(64) NOT NULL,
	"lifecycle_state" varchar(16) DEFAULT 'ACTIVE' NOT NULL,
	"first_protocol_version" integer,
	"last_protocol_version" integer,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "evidence_groups_process_group_uq" UNIQUE("process_id","evidence_group_id")
);
--> statement-breakpoint
CREATE TABLE "process_files" (
	"process_id" uuid NOT NULL,
	"file_id" varchar(512) NOT NULL,
	"included" boolean DEFAULT true NOT NULL,
	"added_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "process_files_process_id_file_id_pk" PRIMARY KEY("process_id","file_id")
);
--> statement-breakpoint
CREATE TABLE "processes" (
	"id" uuid PRIMARY KEY NOT NULL,
	"object_id" varchar(64) NOT NULL,
	"status" varchar(16) NOT NULL,
	"stage" varchar(24),
	"source" varchar(16) NOT NULL,
	"purpose" varchar(16) NOT NULL,
	"active_run_id" uuid NOT NULL,
	"batch_run_id" varchar(128) NOT NULL,
	"scenario" varchar(24),
	"scenario_base" varchar(24),
	"upload_status" jsonb,
	"input_manifest_hash" char(64),
	"matrix_version" text,
	"pipeline_version" text,
	"current_protocol_id" uuid,
	"assigned_inspector_id" uuid,
	"verification_started_at" timestamp with time zone,
	"completed_at" timestamp with time zone,
	"finalized_at" timestamp with time zone,
	"row_version" integer DEFAULT 1 NOT NULL,
	"created_by" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "processes_run_object_uq" UNIQUE("active_run_id","object_id")
);
--> statement-breakpoint
CREATE TABLE "protocol_exports" (
	"id" uuid PRIMARY KEY NOT NULL,
	"protocol_id" uuid NOT NULL,
	"format" varchar(16) NOT NULL,
	"storage_key" text NOT NULL,
	"sha256" char(64) NOT NULL,
	"size_bytes" bigint NOT NULL,
	"generated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "protocol_exports_protocol_format_uq" UNIQUE("protocol_id","format")
);
--> statement-breakpoint
CREATE TABLE "protocols" (
	"id" uuid PRIMARY KEY NOT NULL,
	"process_id" uuid NOT NULL,
	"object_id" varchar(64) NOT NULL,
	"version" integer NOT NULL,
	"protocol_no" text NOT NULL,
	"status" varchar(24) NOT NULL,
	"is_final" boolean NOT NULL,
	"version_reason" varchar(24) NOT NULL,
	"previous_version_id" uuid,
	"run_id" uuid,
	"matrix_version" text,
	"dataset_version" text,
	"model_version" text,
	"pipeline_version" text NOT NULL,
	"engine_versions" jsonb,
	"versions" jsonb NOT NULL,
	"input_manifest_hash" char(64) NOT NULL,
	"scenario" varchar(24),
	"scenario_base" varchar(24),
	"upload_status" jsonb,
	"summary" jsonb,
	"content_json" jsonb NOT NULL,
	"content_sha256" char(64) NOT NULL,
	"source_path" text,
	"source_sha256" char(64),
	"generated_at" timestamp with time zone NOT NULL,
	"finalized_at" timestamp with time zone,
	"finalized_by" uuid,
	"superseded_at" timestamp with time zone,
	"superseded_reason" text,
	"created_by" uuid,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "protocols_process_version_uq" UNIQUE("process_id","version")
);
--> statement-breakpoint
CREATE TABLE "run_artifacts" (
	"run_id" uuid NOT NULL,
	"path" text NOT NULL,
	"kind" varchar(32) NOT NULL,
	"format" varchar(8) NOT NULL,
	"schema_name" text,
	"object_id" varchar(64),
	"file_id" varchar(512),
	"sha256" char(64) NOT NULL,
	"size_bytes" bigint NOT NULL,
	"records" integer,
	"producer" jsonb,
	"modified_at" timestamp with time zone,
	"imported_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "run_artifacts_run_id_path_pk" PRIMARY KEY("run_id","path")
);
--> statement-breakpoint
CREATE TABLE "submission_exports" (
	"id" uuid PRIMARY KEY NOT NULL,
	"process_id" uuid NOT NULL,
	"run_id" uuid NOT NULL,
	"object_id" varchar(64) NOT NULL,
	"variant" varchar(8) NOT NULL,
	"path" text NOT NULL,
	"sha256" char(64) NOT NULL,
	"size_bytes" bigint NOT NULL,
	"rows_count" integer NOT NULL,
	"content" jsonb NOT NULL,
	"sidecar" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "submission_exports_process_variant_uq" UNIQUE("process_id","variant")
);
--> statement-breakpoint
CREATE TABLE "suspicions" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"object_id" varchar(64) NOT NULL,
	"discovery_method" varchar(32),
	"confidence" numeric(4, 3),
	"description" text NOT NULL,
	"inspector_status" varchar(32) NOT NULL,
	"process_id" uuid NOT NULL,
	"run_id" uuid,
	"suspicion_key" varchar(128) NOT NULL,
	"param_code" varchar(32),
	"finding_status" varchar(16) DEFAULT 'SUSPICION' NOT NULL,
	"evidence_status" varchar(16),
	"expected_value" jsonb,
	"actual_value" jsonb,
	"pd_reference" text,
	"rd_reference" text,
	"id_reference" text,
	"review_priority" varchar(8),
	"related_check_ids" bigint[] DEFAULT '{}'::bigint[] NOT NULL,
	"converted_check_id" bigint,
	"promoted_by" varchar(16),
	"explanation" jsonb,
	"is_stale" boolean DEFAULT false NOT NULL,
	"decided_by" uuid,
	"decided_at" timestamp with time zone,
	"reason_code" varchar(48),
	"inspector_comment" text,
	"row_version" integer DEFAULT 1 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "suspicions_process_key_uq" UNIQUE("process_id","suspicion_key")
);
--> statement-breakpoint
ALTER TABLE "object_assignments" ADD CONSTRAINT "object_assignments_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "user_roles" ADD CONSTRAINT "user_roles_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "checks" ADD CONSTRAINT "checks_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "checks" ADD CONSTRAINT "checks_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_fragments" ADD CONSTRAINT "evidence_fragments_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_fragments" ADD CONSTRAINT "evidence_fragments_check_id_checks_id_fk" FOREIGN KEY ("check_id") REFERENCES "public"."checks"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "evidence_groups" ADD CONSTRAINT "evidence_groups_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "process_files" ADD CONSTRAINT "process_files_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "process_files" ADD CONSTRAINT "process_files_file_id_files_id_fk" FOREIGN KEY ("file_id") REFERENCES "public"."files"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "processes" ADD CONSTRAINT "processes_object_id_objects_id_fk" FOREIGN KEY ("object_id") REFERENCES "public"."objects"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "processes" ADD CONSTRAINT "processes_active_run_id_runs_id_fk" FOREIGN KEY ("active_run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "protocol_exports" ADD CONSTRAINT "protocol_exports_protocol_id_protocols_id_fk" FOREIGN KEY ("protocol_id") REFERENCES "public"."protocols"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "protocols" ADD CONSTRAINT "protocols_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "protocols" ADD CONSTRAINT "protocols_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "run_artifacts" ADD CONSTRAINT "run_artifacts_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "submission_exports" ADD CONSTRAINT "submission_exports_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "submission_exports" ADD CONSTRAINT "submission_exports_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "suspicions" ADD CONSTRAINT "suspicions_process_id_processes_id_fk" FOREIGN KEY ("process_id") REFERENCES "public"."processes"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "suspicions" ADD CONSTRAINT "suspicions_run_id_runs_id_fk" FOREIGN KEY ("run_id") REFERENCES "public"."runs"("id") ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "object_assignments_user_idx" ON "object_assignments" USING btree ("user_id");--> statement-breakpoint
CREATE INDEX "audit_log_timestamp_idx" ON "audit_log" USING btree ("timestamp");--> statement-breakpoint
CREATE INDEX "audit_log_user_idx" ON "audit_log" USING btree ("user_id","timestamp");--> statement-breakpoint
CREATE INDEX "audit_log_object_idx" ON "audit_log" USING btree ("object_type","object_id");--> statement-breakpoint
CREATE INDEX "audit_log_process_idx" ON "audit_log" USING btree ("process_id","timestamp");--> statement-breakpoint
CREATE INDEX "audit_log_action_idx" ON "audit_log" USING btree ("action","timestamp");--> statement-breakpoint
CREATE INDEX "audit_log_construction_object_idx" ON "audit_log" USING btree ("construction_object_id","timestamp");--> statement-breakpoint
CREATE INDEX "audit_log_request_idx" ON "audit_log" USING btree ("request_id");--> statement-breakpoint
CREATE INDEX "checks_process_status_idx" ON "checks" USING btree ("process_id","protocol_status");--> statement-breakpoint
CREATE INDEX "checks_process_param_idx" ON "checks" USING btree ("process_id","param_code");--> statement-breakpoint
CREATE INDEX "checks_group_idx" ON "checks" USING btree ("process_id","evidence_group_id");--> statement-breakpoint
CREATE INDEX "evidence_fragments_check_idx" ON "evidence_fragments" USING btree ("check_id");--> statement-breakpoint
CREATE INDEX "evidence_fragments_group_idx" ON "evidence_fragments" USING btree ("process_id","evidence_group_id");--> statement-breakpoint
CREATE INDEX "evidence_fragments_page_idx" ON "evidence_fragments" USING btree ("file_id","page_no");--> statement-breakpoint
CREATE INDEX "processes_object_idx" ON "processes" USING btree ("object_id","created_at");--> statement-breakpoint
CREATE INDEX "run_artifacts_kind_idx" ON "run_artifacts" USING btree ("run_id","kind");--> statement-breakpoint
CREATE INDEX "run_artifacts_file_idx" ON "run_artifacts" USING btree ("file_id","kind");