-- checks.document_status (DocumentStatus enum, packages/contracts/enums.yaml) grew past 32 chars in M1
-- (e.g. PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK, 51 chars). Widen the column to fit the enum
-- with headroom (AG-00, integration fix found while importing the M1 Тюменская run end to end).
ALTER TABLE "checks" ALTER COLUMN "document_status" TYPE varchar(64);
