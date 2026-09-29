"""GENERATED from packages/contracts/enums.yaml and errors.yaml by `inspector-contracts gen`. Do not edit."""

from __future__ import annotations

from enum import StrEnum

CONTRACT_VERSION = "0.1.0"


class ViolationLabel(StrEnum):
    """Owner: AG-04."""

    VIOLATION_PRESENT = "VIOLATION_PRESENT"  # Нарушение выявлено
    NO_VIOLATION = "NO_VIOLATION"  # Нарушений нет
    MISSING_DOCUMENT = "MISSING_DOCUMENT"  # Отсутствует документ
    COMPARISON_IMPOSSIBLE = "COMPARISON_IMPOSSIBLE"  # Сравнение невозможно


class ProtocolParamStatus(StrEnum):
    """Owner: AG-04."""

    OK = "OK"  # Нарушений нет
    WARNING = "WARNING"  # Существенное нарушение
    CRITICAL = "CRITICAL"  # Критическое нарушение
    ID_MISSING = "ID_MISSING"  # Отсутствует ИД
    RD_MISSING = "RD_MISSING"  # Отсутствует РД
    PD_MISSING = "PD_MISSING"  # Отсутствует ПД
    PARTIALLY_LOADED = "PARTIALLY_LOADED"  # ИД загружена частично
    COMPARISON_IMPOSSIBLE = "COMPARISON_IMPOSSIBLE"  # Проверка невозможна


class CriticalityLevel(StrEnum):
    """Owner: AG-03."""

    CRITICAL_SUSPEND = "CRITICAL_SUSPEND"  # Критическое
    SUBSTANTIAL_ORDER = "SUBSTANTIAL_ORDER"  # Существенное
    INFORMATIONAL = "INFORMATIONAL"  # Информационное


class ParameterMappingStatus(StrEnum):
    """Owner: AG-03."""

    SOURCE_MATRIX = "SOURCE_MATRIX"  # Параметр матрицы
    PROVISIONAL_DOMAIN_MAPPING = "PROVISIONAL_DOMAIN_MAPPING"  # Предварительное отнесение по инженерной системе
    MATRIX_GAP_CONFIRMED = "MATRIX_GAP_CONFIRMED"  # Пробел матрицы (свободный поиск)


class ComparisonResult(StrEnum):
    """Owner: AG-04."""

    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"  # Изменена конфигурация
    MISSING_DESIGN_ELEMENT = "MISSING_DESIGN_ELEMENT"  # Отсутствует предусмотренный элемент
    VALUE_MISMATCH = "VALUE_MISMATCH"  # Расхождение значений
    MATERIAL_SUBSTITUTION = "MATERIAL_SUBSTITUTION"  # Замена материала или класса
    EXTRA_ELEMENT = "EXTRA_ELEMENT"  # Непредусмотренный элемент
    TOLERANCE_EXCEEDED = "TOLERANCE_EXCEEDED"  # Превышен допуск


class LocationType(StrEnum):
    """Owner: AG-04."""

    ROOM = "ROOM"  # Помещение
    FLOOR = "FLOOR"  # Этаж
    BUILDING = "BUILDING"  # Корпус (здание)
    AXES = "AXES"  # Оси
    ELEMENT = "ELEMENT"  # Конструктивный элемент
    OBJECT = "OBJECT"  # Объект в целом


class MatrixScope(StrEnum):
    """Owner: AG-04."""

    MATRIX = "MATRIX"  # Матрица 132 параметров
    FREE_SEARCH = "FREE_SEARCH"  # Свободный поиск


class DocumentStatus(StrEnum):
    """Owner: AG-04. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK = "PD_RD_AVAILABLE_ID_NOT_REQUIRED_FOR_PAIRWISE_CHECK"  # ПД и РД доступны; ИД не требуется для попарной проверки
    PD_ID_AVAILABLE_RD_NOT_REQUIRED_FOR_PAIRWISE_CHECK = "PD_ID_AVAILABLE_RD_NOT_REQUIRED_FOR_PAIRWISE_CHECK"  # ПД и ИД доступны; РД не требуется для попарной проверки
    RD_ID_AVAILABLE_PD_NOT_REQUIRED_FOR_PAIRWISE_CHECK = "RD_ID_AVAILABLE_PD_NOT_REQUIRED_FOR_PAIRWISE_CHECK"  # РД и ИД доступны; ПД не требуется для попарной проверки
    PD_RD_ID_AVAILABLE = "PD_RD_ID_AVAILABLE"  # ПД, РД и ИД доступны
    PD_RD_AVAILABLE_ID_MISSING = "PD_RD_AVAILABLE_ID_MISSING"  # ПД и РД доступны; ИД отсутствует
    PD_ID_AVAILABLE_RD_MISSING = "PD_ID_AVAILABLE_RD_MISSING"  # ПД и ИД доступны; РД отсутствует
    RD_ID_AVAILABLE_PD_MISSING = "RD_ID_AVAILABLE_PD_MISSING"  # РД и ИД доступны; ПД отсутствует
    PD_AVAILABLE_RD_ID_MISSING = "PD_AVAILABLE_RD_ID_MISSING"  # Доступна только ПД
    RD_AVAILABLE_PD_ID_MISSING = "RD_AVAILABLE_PD_ID_MISSING"  # Доступна только РД
    ID_AVAILABLE_PD_RD_MISSING = "ID_AVAILABLE_PD_RD_MISSING"  # Доступна только ИД
    PD_RD_ID_MISSING = "PD_RD_ID_MISSING"  # Документы отсутствуют


class FreeTopic(StrEnum):
    """Owner: AG-07."""

    HEATING = "HEATING"  # Отопление
    VENTILATION = "VENTILATION"  # Вентиляция
    WATER = "WATER"  # Водоснабжение
    SEWER = "SEWER"  # Водоотведение
    ELECTRICAL = "ELECTRICAL"  # Электроснабжение
    LIGHTING = "LIGHTING"  # Освещение
    FIRE = "FIRE"  # Пожарная безопасность
    EVACUATION = "EVACUATION"  # Эвакуация
    ACCESSIBILITY = "ACCESSIBILITY"  # Доступность для МГН
    ARCHITECTURE = "ARCHITECTURE"  # Архитектурные решения
    STRUCTURE = "STRUCTURE"  # Конструктивные решения
    SITE = "SITE"  # Земельный участок и благоустройство
    ROOF = "ROOF"  # Кровля
    FACADE = "FACADE"  # Фасады
    LIFT = "LIFT"  # Лифты
    ENERGY = "ENERGY"  # Энергоэффективность
    OTHER = "OTHER"  # Прочее


class SubmissionVariant(StrEnum):
    """Owner: AG-04."""

    FULL = "full"  # Полный ответ (с дополнительными полями из gold)
    STRICT = "strict"  # Строгий ответ (только поля схемы организаторов)


class ManifestStage(StrEnum):
    """Owner: AG-01."""

    PD = "PD"  # ПД
    RD = "RD"  # РД
    ID = "ID"  # ИД
    RD_ID_MIXED = "RD_ID_MIXED"  # РД и ИД вперемешку (стадия определяется по файлу)
    UNKNOWN = "UNKNOWN"  # Стадия не указана


class ManifestSplit(StrEnum):
    """Owner: AG-10."""

    TRAIN_PUBLIC = "TRAIN_PUBLIC"  # Публичная обучающая выборка
    TEST_HIDDEN = "TEST_HIDDEN"  # Скрытая тестовая выборка


class ManifestSection(StrEnum):
    """Owner: AG-01. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    OTHER = "OTHER"  # Прочее
    AR = "AR"  # АР
    KR = "KR"  # КР
    POS = "POS"  # ПОС
    GP = "GP"  # ГП
    EOM = "EOM"  # ЭОМ
    VK = "VK"  # ВК
    OV = "OV"  # ОВ
    SS = "SS"  # СС
    PB = "PB"  # ПБ


class DatasetRole(StrEnum):
    """Owner: AG-10. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    GOLD_SEED = "GOLD_SEED"
    UNLABELED_POOL = "UNLABELED_POOL"


class AnnotationStatus(StrEnum):
    """Owner: AG-01. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    UNLABELED = "UNLABELED"
    POSITIVE_EVIDENCE_SOURCE = "POSITIVE_EVIDENCE_SOURCE"
    GROUND_TRUTH_INDEX = "GROUND_TRUTH_INDEX"


class DistributionStatus(StrEnum):
    """Owner: AG-01. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    INCLUDE = "INCLUDE"


class LabelVisibility(StrEnum):
    """Owner: AG-10. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    PUBLIC_TRAIN = "PUBLIC_TRAIN"
    ORGANIZER_ONLY = "ORGANIZER_ONLY"


class GoldStatus(StrEnum):
    """Owner: AG-10. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    FINAL_GOLD_EXISTENCE = "FINAL_GOLD_EXISTENCE"  # Эталон организаторов
    TEAM_LABEL_FROZEN = "TEAM_LABEL_FROZEN"  # Разметка команды (зафиксирована)


class EvidenceLocalization(StrEnum):
    """Owner: AG-10. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    PAGE_LEVEL_VISUALLY_VERIFIED = "PAGE_LEVEL_VISUALLY_VERIFIED"


class LocalFileStatus(StrEnum):
    """Owner: AG-01."""

    PRESENT = "PRESENT"  # Файл на диске
    RECOVERED = "RECOVERED"  # Восстановлен из исходного архива организаторов
    MISSING_ON_DISK = "MISSING_ON_DISK"  # Отсутствует на диске


class ArchiveMemberRole(StrEnum):
    """Owner: AG-01."""

    PDF_TWIN_SOURCE = "PDF_TWIN_SOURCE"  # Исходник PDF-двойника (DWG)
    CONTEXT_ONLY = "CONTEXT_ONLY"  # Только контекст
    FOREIGN_OBJECT = "FOREIGN_OBJECT"  # Относится к другому объекту
    DUPLICATE = "DUPLICATE"  # Дубликат
    IGNORED = "IGNORED"  # Не используется


class PageBasis(StrEnum):
    """Owner: AG-02A."""

    PDF_NATIVE = "PDF_NATIVE"  # Страница исходного PDF
    RENDERED_LIBREOFFICE = "RENDERED_LIBREOFFICE"  # Страница DOCX, отрисованного LibreOffice


class TextSource(StrEnum):
    """Owner: AG-02A."""

    TEXT_LAYER = "TEXT_LAYER"  # Текстовый слой PDF
    TEXT_LAYER_REPAIRED = "TEXT_LAYER_REPAIRED"  # Восстановленный текстовый слой
    OCR = "OCR"  # Распознавание (OCR)
    OCR_LAYER_ISOLATED = "OCR_LAYER_ISOLATED"  # OCR по изолированному слою САПР


class ProcessStatus(StrEnum):
    """Owner: AG-00."""

    PENDING = "PENDING"  # Документы загружены, проверка не начата
    PARSING = "PARSING"  # Парсинг документов
    READY = "READY"  # Протокол сформирован
    VERIFYING = "VERIFYING"  # Верификация
    COMPLETED = "COMPLETED"  # Верификация завершена
    FINALIZED = "FINALIZED"  # Протокол финализирован
    FAILED = "FAILED"  # Обработка завершилась ошибкой


class ProcessStage(StrEnum):
    """Owner: AG-00."""

    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    META = "META"
    PARSING = "PARSING"
    OCR = "OCR"
    EXTRACTING = "EXTRACTING"
    COMPARING = "COMPARING"
    HYPOTHESIS = "HYPOTHESIS"
    PROTOCOL_BUILDING = "PROTOCOL_BUILDING"
    RENDERING = "RENDERING"
    DONE = "DONE"
    FAILED = "FAILED"


class RecheckState(StrEnum):
    """Owner: AG-00."""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


class ProcessPurpose(StrEnum):
    """Owner: AG-10."""

    INSPECTION = "INSPECTION"
    EVALUATION = "EVALUATION"
    SELFTEST = "SELFTEST"


class ProcessSource(StrEnum):
    """Owner: AG-01."""

    UI = "UI"  # Интерфейс
    API = "API"  # API
    RIN = "RIN"  # ИАИС «РиН»
    BATCH_IMPORT = "BATCH_IMPORT"  # Импорт пакетного прогона


class FileSource(StrEnum):
    """Owner: AG-01."""

    UI = "UI"  # Загружен через интерфейс
    API = "API"  # Загружен через API
    RIN = "RIN"  # Получен из РиН
    BATCH_IMPORT = "BATCH_IMPORT"  # Импортирован из пакетного прогона


class ProtocolStatus(StrEnum):
    """Owner: AG-04."""

    IN_VERIFICATION = "IN_VERIFICATION"  # На верификации
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"  # Верификация завершена
    PROTOCOL_FINALIZED = "PROTOCOL_FINALIZED"  # Протокол финализирован
    SUPERSEDED = "SUPERSEDED"  # Заменён новой версией


class ProtocolVersionReason(StrEnum):
    """Owner: AG-04."""

    INITIAL = "INITIAL"
    INCREMENTAL_UPDATE = "INCREMENTAL_UPDATE"
    RECHECK = "RECHECK"
    FINALIZATION = "FINALIZATION"
    UNFINALIZATION = "UNFINALIZATION"


class RecheckReason(StrEnum):
    """Owner: AG-04."""

    REVISION_RESOLVED = "REVISION_RESOLVED"
    FACT_OVERRIDE = "FACT_OVERRIDE"
    COMPLETENESS_OVERRIDE = "COMPLETENESS_OVERRIDE"
    MATRIX_RECHECK = "MATRIX_RECHECK"
    MANUAL = "MANUAL"


class IncrementalTrigger(StrEnum):
    """Owner: AG-01."""

    UPLOAD = "UPLOAD"
    REUPLOAD = "REUPLOAD"
    REGISTRY_UPDATE = "REGISTRY_UPDATE"
    RIN_PULL = "RIN_PULL"


class StageUploadStatus(StrEnum):
    """Owner: AG-01."""

    PD_UPLOADED = "PD_UPLOADED"  # ПД загружена полностью
    PD_PARTIAL = "PD_PARTIAL"  # ПД загружена частично
    PD_MISSING = "PD_MISSING"  # ПД отсутствует
    RD_UPLOADED = "RD_UPLOADED"  # РД загружена полностью
    RD_PARTIAL = "RD_PARTIAL"  # РД загружена частично
    RD_MISSING = "RD_MISSING"  # РД отсутствует
    ID_UPLOADED = "ID_UPLOADED"  # ИД загружена полностью
    ID_PARTIAL = "ID_PARTIAL"  # ИД загружена частично
    ID_MISSING = "ID_MISSING"  # ИД отсутствует


class LoadScenario(StrEnum):
    """Owner: AG-01."""

    FULL = "FULL"  # Полный комплект (ПД, РД, ИД)
    PD_RD_ONLY = "PD_RD_ONLY"  # Только ПД и РД
    PD_ID_ONLY = "PD_ID_ONLY"  # Только ПД и ИД
    RD_ID_ONLY = "RD_ID_ONLY"  # Только РД и ИД
    SINGLE_ONLY = "SINGLE_ONLY"  # Только один вид документации
    PARTIALLY_LOADED = "PARTIALLY_LOADED"  # Частичная загрузка


class ScenarioBase(StrEnum):
    """Owner: AG-01."""

    FULL = "FULL"
    PD_RD_ONLY = "PD_RD_ONLY"
    PD_ID_ONLY = "PD_ID_ONLY"
    RD_ID_ONLY = "RD_ID_ONLY"
    SINGLE_ONLY = "SINGLE_ONLY"
    NONE = "NONE"


class JobStatus(StrEnum):
    """Owner: AG-00."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"
    CANCELLED = "CANCELLED"


class RunMode(StrEnum):
    """Owner: AG-00."""

    INITIAL = "INITIAL"
    INCREMENTAL = "INCREMENTAL"
    RECHECK = "RECHECK"


class RunStatus(StrEnum):
    """Owner: AG-00."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class EngineStatus(StrEnum):
    """Owner: AG-00."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    OK = "OK"
    PARTIAL = "PARTIAL"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class DocStage(StrEnum):
    """Owner: AG-01."""

    PD = "PD"  # ПД
    RD = "RD"  # РД
    ID = "ID"  # ИД


class ApprovalStatus(StrEnum):
    """Owner: AG-01."""

    DRAFT = "DRAFT"  # Черновик
    APPROVED = "APPROVED"  # Утверждено
    FOR_CONSTRUCTION = "FOR_CONSTRUCTION"  # В производство работ
    SUPERSEDED = "SUPERSEDED"  # Заменено
    CANCELLED = "CANCELLED"  # Аннулировано
    UNKNOWN = "UNKNOWN"  # Статус не определён


class SignatureStatus(StrEnum):
    """Owner: AG-01."""

    UKEP = "UKEP"
    UNEP = "UNEP"
    WET_SCAN = "WET_SCAN"
    ABSENT = "ABSENT"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class RegistryStatus(StrEnum):
    """Owner: AG-01."""

    MISSING = "MISSING"
    INVALID = "INVALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    VALID = "VALID"
    DRAFT_UNCONFIRMED = "DRAFT_UNCONFIRMED"


class PackageStatus(StrEnum):
    """Owner: AG-01."""

    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_REJECTIONS = "ACCEPTED_WITH_REJECTIONS"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    REJECTED_PACKAGE_LIMIT = "REJECTED_PACKAGE_LIMIT"


class FileIntakeStatus(StrEnum):
    """Owner: AG-01."""

    RECEIVED = "RECEIVED"
    STORED = "STORED"
    VALIDATED = "VALIDATED"
    META_EXTRACTED = "META_EXTRACTED"
    PARSE_QUEUED = "PARSE_QUEUED"
    PARSED = "PARSED"
    REJECTED_FORMAT = "REJECTED_FORMAT"
    REJECTED_SIZE = "REJECTED_SIZE"
    REJECTED_EMPTY = "REJECTED_EMPTY"
    REJECTED_CORRUPTED = "REJECTED_CORRUPTED"
    REJECTED_ENCRYPTED = "REJECTED_ENCRYPTED"
    REJECTED_INFECTED = "REJECTED_INFECTED"
    REJECTED_MISMATCH = "REJECTED_MISMATCH"
    FAILED_TIMEOUT = "FAILED_TIMEOUT"


class FileIntegrityStatus(StrEnum):
    """Owner: AG-00."""

    OK = "OK"
    CORRUPTED = "CORRUPTED"
    MISSING = "MISSING"


class MetaSource(StrEnum):
    """Owner: AG-01."""

    REGISTRY = "REGISTRY"
    DRAFT_CONFIRMED = "DRAFT_CONFIRMED"
    EXTRACTED_UNCONFIRMED = "EXTRACTED_UNCONFIRMED"


class MetaStatus(StrEnum):
    """Owner: AG-01."""

    OK = "OK"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class SelectionBasis(StrEnum):
    """Owner: AG-01."""

    SINGLE_APPROVED = "SINGLE_APPROVED"
    EXPLICIT_CHAIN = "EXPLICIT_CHAIN"
    SUPERSEDED_STATUS = "SUPERSEDED_STATUS"
    INSPECTOR_DECISION = "INSPECTOR_DECISION"
    INFERRED_ORDER = "INFERRED_ORDER"


class CompletenessItemStatus(StrEnum):
    """Owner: AG-01."""

    PRESENT = "PRESENT"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    DECLARED_NOT_RECEIVED = "DECLARED_NOT_RECEIVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    NOT_COMPARABLE = "NOT_COMPARABLE"


class ChecklistLevel(StrEnum):
    """Owner: AG-01."""

    CORE = "CORE"
    EXPECTED = "EXPECTED"
    OPTIONAL = "OPTIONAL"


class PageClass(StrEnum):
    """Owner: AG-02A."""

    VECTOR = "VECTOR"  # Векторная страница с текстовым слоем
    HYBRID = "HYBRID"  # Векторная страница с растровыми вставками
    RASTER_SCAN = "RASTER_SCAN"  # Скан без текстового слоя
    RASTER_HIDDEN_OCR = "RASTER_HIDDEN_OCR"  # Скан со скрытым OCR-слоем
    VECTOR_OUTLINED_TEXT = "VECTOR_OUTLINED_TEXT"  # Текст в кривых
    BROKEN_ENCODING = "BROKEN_ENCODING"  # Искажённая кодировка текстового слоя
    STAMP_PAGE = "STAMP_PAGE"  # Служебная страница (штамп, обложка)
    EMPTY = "EMPTY"  # Пустая страница


class QualityFlag(StrEnum):
    """Owner: AG-02A."""

    OK = "OK"  # Качество достаточное
    LOW_QUALITY = "LOW_QUALITY"  # Низкое качество
    ABSTAIN = "ABSTAIN"  # Исключено из анализа


class ZoneSource(StrEnum):
    """Owner: AG-02A."""

    AUTO = "AUTO"
    PREMARKED = "PREMARKED"
    INSPECTOR = "INSPECTOR"


class ZoneKind(StrEnum):
    """Owner: AG-02A. OPEN vocabulary: unknown values may occur in data; keep them raw."""

    TITLE_BLOCK = "TITLE_BLOCK"
    STAMP = "STAMP"
    SEAL = "SEAL"
    QR = "QR"
    HANDWRITING = "HANDWRITING"
    TABLE = "TABLE"
    REVISION_CLOUD = "REVISION_CLOUD"
    PREMARKED_UNREADABLE = "PREMARKED_UNREADABLE"
    OTHER = "OTHER"


class ExtractionMethod(StrEnum):
    """Owner: AG-02C."""

    TEXT_LAYER = "TEXT_LAYER"
    OCR = "OCR"
    TABLE = "TABLE"
    REGEX = "REGEX"
    TOKEN_GRAMMAR = "TOKEN_GRAMMAR"
    SEMANTIC = "SEMANTIC"
    CV_MEASURE = "CV_MEASURE"
    XML_XPATH = "XML_XPATH"
    DOCX = "DOCX"
    MANUAL = "MANUAL"
    VLM_ASSIST = "VLM_ASSIST"


class ParamExtractionStatus(StrEnum):
    """Owner: AG-02C."""

    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    LOW_QUALITY_ONLY = "LOW_QUALITY_ONLY"
    AMBIGUOUS = "AMBIGUOUS"


class ExtractionRunStatus(StrEnum):
    """Owner: AG-02A."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CACHE_HIT = "CACHE_HIT"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


class DataType(StrEnum):
    """Owner: AG-03."""

    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"
    COORDINATE = "coordinate"
    ENUM = "enum"


class ReviewPriority(StrEnum):
    """Owner: AG-03."""

    HIGH = "HIGH"  # Высокий
    MEDIUM = "MEDIUM"  # Средний
    LOW = "LOW"  # Низкий


class RiskLevel(StrEnum):
    """Owner: AG-04."""

    HIGH = "HIGH"  # Высокий
    MEDIUM = "MEDIUM"  # Средний
    LOW = "LOW"  # Низкий


class RuleType(StrEnum):
    """Owner: AG-03."""

    PAIRWISE_DELTA = "PAIRWISE_DELTA"
    NORMATIVE_BOUND = "NORMATIVE_BOUND"
    ORDINAL_COMPARE = "ORDINAL_COMPARE"
    ENUM_CHANGE = "ENUM_CHANGE"
    SET_DIFF = "SET_DIFF"
    LAYER_STACK = "LAYER_STACK"
    PRESENCE = "PRESENCE"
    TOLERANCE_CHECK = "TOLERANCE_CHECK"
    GEOMETRY_OFFSET = "GEOMETRY_OFFSET"
    GEOMETRY_CONTAINMENT = "GEOMETRY_CONTAINMENT"
    RATIO_BOUND = "RATIO_BOUND"
    EXTERNAL_STATUS = "EXTERNAL_STATUS"
    SEMANTIC_DIFF = "SEMANTIC_DIFF"


class CandidatePolicy(StrEnum):
    """Owner: AG-03."""

    TRIGGER = "TRIGGER"
    DEVIATION = "DEVIATION"


class ViolationType(StrEnum):
    """Owner: AG-03."""

    NUMERIC_DECREASE = "NUMERIC_DECREASE"
    NORM_BOUND_VIOLATION = "NORM_BOUND_VIOLATION"
    NUMERIC_DEVIATION = "NUMERIC_DEVIATION"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    ELEMENT_REMOVED = "ELEMENT_REMOVED"
    NUMERIC_INCREASE = "NUMERIC_INCREASE"
    CLASS_DOWNGRADE = "CLASS_DOWNGRADE"
    COUNT_DECREASE = "COUNT_DECREASE"
    MATERIAL_SUBSTITUTION = "MATERIAL_SUBSTITUTION"
    ZONE_INTRUSION = "ZONE_INTRUSION"
    EXTERNAL_NONCOMPLIANCE = "EXTERNAL_NONCOMPLIANCE"
    TOLERANCE_EXCEEDED = "TOLERANCE_EXCEEDED"
    INTERNAL_INCONSISTENCY = "INTERNAL_INCONSISTENCY"
    LAYER_CHANGE = "LAYER_CHANGE"
    GEOMETRY_OFFSET = "GEOMETRY_OFFSET"
    RATIO_VIOLATION = "RATIO_VIOLATION"


class RuleDirection(StrEnum):
    """Owner: AG-03."""

    ANY = "ANY"  # Любое изменение
    DECREASE = "DECREASE"  # Уменьшение
    INCREASE = "INCREASE"  # Увеличение
    DOWNGRADE = "DOWNGRADE"  # Понижение класса


class RuleOperator(StrEnum):
    """Owner: AG-03."""

    ABS_DELTA_GT = "ABS_DELTA_GT"
    REL_DELTA_GT = "REL_DELTA_GT"
    OUTSIDE_BOUNDS = "OUTSIDE_BOUNDS"
    ORDINAL_LOWER = "ORDINAL_LOWER"
    ORDINAL_NE = "ORDINAL_NE"
    NE = "NE"
    SET_DIFF = "SET_DIFF"
    LAYER_DIFF = "LAYER_DIFF"
    PRESENT_IN_EXPECTED_ABSENT_IN_ACTUAL = "PRESENT_IN_EXPECTED_ABSENT_IN_ACTUAL"
    ABS_DEVIATION_GT_TOLERANCE = "ABS_DEVIATION_GT_TOLERANCE"
    DIST_GT = "DIST_GT"
    INTERSECTS_FORBIDDEN_ZONE = "INTERSECTS_FORBIDDEN_ZONE"
    RATIO_LT = "RATIO_LT"
    STATUS_NOT_OK = "STATUS_NOT_OK"
    SEMANTIC_CONTRADICTION = "SEMANTIC_CONTRADICTION"


class DetectKind(StrEnum):
    """Owner: AG-03."""

    MISSING = "MISSING"
    ADDED = "ADDED"
    CHANGED = "CHANGED"
    LAYER_REMOVED = "LAYER_REMOVED"
    THICKNESS_DECREASED = "THICKNESS_DECREASED"
    MATERIAL_CHANGED = "MATERIAL_CHANGED"
    LAYER_ADDED = "LAYER_ADDED"


class AbstainReason(StrEnum):
    """Owner: AG-03."""

    UNIT_MISMATCH = "UNIT_MISMATCH"
    VALUE_NOT_FOUND = "VALUE_NOT_FOUND"
    AMBIGUOUS_VALUE = "AMBIGUOUS_VALUE"
    UNKNOWN_SCALE_VALUE = "UNKNOWN_SCALE_VALUE"
    ELEMENT_KEY_UNRESOLVED = "ELEMENT_KEY_UNRESOLVED"
    SHEETS_NOT_MATCHED = "SHEETS_NOT_MATCHED"
    ASSEMBLY_NOT_MATCHED = "ASSEMBLY_NOT_MATCHED"
    TOLERANCE_NOT_FOUND = "TOLERANCE_NOT_FOUND"
    CRS_MISMATCH = "CRS_MISMATCH"
    HEIGHT_SYSTEM_MISMATCH = "HEIGHT_SYSTEM_MISMATCH"
    PRICE_LEVEL_MISMATCH = "PRICE_LEVEL_MISMATCH"
    VAT_BASIS_MISMATCH = "VAT_BASIS_MISMATCH"
    METHOD_MISMATCH = "METHOD_MISMATCH"
    GEOMETRY_NOT_EXTRACTED = "GEOMETRY_NOT_EXTRACTED"
    EXTERNAL_DATA_UNAVAILABLE = "EXTERNAL_DATA_UNAVAILABLE"
    TEXT_NOT_FOUND = "TEXT_NOT_FOUND"


class OrdinalScale(StrEnum):
    """Owner: AG-03."""

    CONCRETE_B = "CONCRETE_B"
    STEEL_GRADE = "STEEL_GRADE"
    REBAR_CLASS = "REBAR_CLASS"
    FIRE_RESISTANCE_DEGREE = "FIRE_RESISTANCE_DEGREE"
    CONSTRUCTIVE_FIRE_HAZARD_CLASS = "CONSTRUCTIVE_FIRE_HAZARD_CLASS"
    KM_CLASS = "KM_CLASS"
    ENERGY_CLASS = "ENERGY_CLASS"
    RELIABILITY_CATEGORY = "RELIABILITY_CATEGORY"
    EI_LIMIT = "EI_LIMIT"
    FIRE_RESISTANCE_LIMIT_R = "FIRE_RESISTANCE_LIMIT_R"
    CABLE_FIRE_INDEX = "CABLE_FIRE_INDEX"
    WASTE_HAZARD_CLASS = "WASTE_HAZARD_CLASS"


class ParamExtractionStrategy(StrEnum):
    """Owner: AG-03."""

    TABLE_TEXT = "TABLE_TEXT"
    FREE_TEXT_REGEX = "FREE_TEXT_REGEX"
    SPEC_TABLE = "SPEC_TABLE"
    DRAWING_GEOMETRY = "DRAWING_GEOMETRY"
    SEMANTIC = "SEMANTIC"
    EXTERNAL_SYSTEM = "EXTERNAL_SYSTEM"
    MANUAL = "MANUAL"


class ThresholdSource(StrEnum):
    """Owner: AG-03."""

    MATRIX_TRIGGER = "MATRIX_TRIGGER"
    NONE = "NONE"
    NORMATIVE = "NORMATIVE"
    PD_VALUE = "PD_VALUE"
    OBJECT_GPZU = "OBJECT_GPZU"
    ADMIN_REQUIRED = "ADMIN_REQUIRED"
    SHEET_OR_NORMATIVE = "SHEET_OR_NORMATIVE"
    NORMATIVE_OVERRIDE = "NORMATIVE_OVERRIDE"


class FeasibilityTier(StrEnum):
    """Owner: AG-03."""

    A = "A"  # A — таблицы и текст
    B = "B"  # B — умеренная автоматизация
    C = "C"  # C — чертежи и семантика
    D = "D"  # D — внешние системы


class HedgeKind(StrEnum):
    """Owner: AG-03."""

    SAME_SYSTEM = "SAME_SYSTEM"  # Одна инженерная система
    DUPLICATE = "DUPLICATE"  # Дублирующие параметры
    PARTIAL_DUPLICATE = "PARTIAL_DUPLICATE"  # Частично дублирующие параметры


class TextOrigin(StrEnum):
    """Owner: AG-03."""

    APPENDIX2 = "APPENDIX2"  # Из Приложения 2
    AG03_DRAFT = "AG03_DRAFT"  # Черновик, требует проверки экспертом


class ObjectPhase(StrEnum):
    """Owner: AG-03."""

    DESIGN = "DESIGN"
    CONSTRUCTION = "CONSTRUCTION"
    COMPLETED = "COMPLETED"


class FactSetBy(StrEnum):
    """Owner: AG-03."""

    SYSTEM = "SYSTEM"
    INSPECTOR = "INSPECTOR"


class MatrixVersionStatus(StrEnum):
    """Owner: AG-03."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ReferenceConfidence(StrEnum):
    """Owner: AG-03."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class NormativeDocType(StrEnum):
    """Owner: AG-08."""

    SP = "SP"
    GOST = "GOST"
    FZ = "FZ"
    SANPIN = "SANPIN"
    PP = "PP"
    GPZU = "GPZU"
    LOCAL = "LOCAL"
    OTHER = "OTHER"


class DiscrepancyType(StrEnum):
    """Owner: AG-04."""

    VALUE_DECREASED = "VALUE_DECREASED"
    VALUE_INCREASED = "VALUE_INCREASED"
    VALUE_CHANGED = "VALUE_CHANGED"
    THRESHOLD_BELOW_MIN = "THRESHOLD_BELOW_MIN"
    THRESHOLD_ABOVE_MAX = "THRESHOLD_ABOVE_MAX"
    TOLERANCE_EXCEEDED = "TOLERANCE_EXCEEDED"
    CLASS_DOWNGRADED = "CLASS_DOWNGRADED"
    MATERIAL_SUBSTITUTED = "MATERIAL_SUBSTITUTED"
    ELEMENT_MISSING = "ELEMENT_MISSING"
    ELEMENT_ADDED = "ELEMENT_ADDED"
    FUNCTION_CHANGED = "FUNCTION_CHANGED"
    LAYER_REMOVED = "LAYER_REMOVED"
    LAYER_CHANGED = "LAYER_CHANGED"
    POSITION_SHIFTED = "POSITION_SHIFTED"
    CONFIGURATION_CHANGED = "CONFIGURATION_CHANGED"
    COUNT_CHANGED = "COUNT_CHANGED"
    TOTAL_CHANGED = "TOTAL_CHANGED"
    UNDOCUMENTED_WORK = "UNDOCUMENTED_WORK"


class ComparisonAxis(StrEnum):
    """Owner: AG-04."""

    PD_RD = "PD_RD"
    RD_ID = "RD_ID"
    PD_ID = "PD_ID"
    NORM_PD = "NORM_PD"
    NORM_RD = "NORM_RD"
    NORM_ID = "NORM_ID"


class CompletenessStatus(StrEnum):
    """Owner: AG-04."""

    COMPLETE = "COMPLETE"  # Данные полные
    MISSING_EVIDENCE = "MISSING_EVIDENCE"  # Отсутствуют доказательства
    NOT_APPLICABLE = "NOT_APPLICABLE"  # Неприменимо
    NOT_COMPARABLE = "NOT_COMPARABLE"  # Несопоставимо
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"  # Требуется уточнение


class CompletenessBasis(StrEnum):
    """Owner: AG-04."""

    REGISTRY_MISSING = "REGISTRY_MISSING"
    REGISTRY_ROW_INVALID = "REGISTRY_ROW_INVALID"
    REGISTRY_HASH_MISMATCH = "REGISTRY_HASH_MISMATCH"
    FILE_NOT_LISTED = "FILE_NOT_LISTED"
    OBJECT_MISMATCH = "OBJECT_MISMATCH"
    REVISION_UNRESOLVED = "REVISION_UNRESOLVED"
    APPROVAL_MISSING = "APPROVAL_MISSING"
    SUPERSEDED_ONLY = "SUPERSEDED_ONLY"
    MANDATORY_SOURCE_MISSING = "MANDATORY_SOURCE_MISSING"
    DECLARED_NOT_RECEIVED = "DECLARED_NOT_RECEIVED"
    CURRENT_REVISION_NOT_UPLOADED = "CURRENT_REVISION_NOT_UPLOADED"
    FILE_REJECTED = "FILE_REJECTED"
    SOURCE_UNREADABLE = "SOURCE_UNREADABLE"
    FILE_NOT_PROCESSED = "FILE_NOT_PROCESSED"
    VALUE_ABSTAINED = "VALUE_ABSTAINED"
    UNIT_INCOMPATIBLE = "UNIT_INCOMPATIBLE"
    VALUE_UNPARSEABLE = "VALUE_UNPARSEABLE"
    VALUE_IMPLAUSIBLE = "VALUE_IMPLAUSIBLE"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    SHEETS_NOT_MATCHED = "SHEETS_NOT_MATCHED"
    EVIDENCE_NOT_LOCALIZABLE = "EVIDENCE_NOT_LOCALIZABLE"
    ENGINE_ERROR = "ENGINE_ERROR"
    LOW_CONFIDENCE_SEMANTIC = "LOW_CONFIDENCE_SEMANTIC"
    STAGE_NOT_APPLICABLE = "STAGE_NOT_APPLICABLE"
    PARAM_NOT_APPLICABLE_TO_OBJECT = "PARAM_NOT_APPLICABLE_TO_OBJECT"
    PARAM_DEACTIVATED = "PARAM_DEACTIVATED"


class FindingStatus(StrEnum):
    """Owner: AG-04."""

    CANDIDATE = "CANDIDATE"  # Кандидат в нарушения
    NEGATIVE_VERIFIED = "NEGATIVE_VERIFIED"  # Нарушение не подтверждено
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"  # Нарушение подтверждено
    SUSPICION = "SUSPICION"  # Подозрение ИИ


class DecidedBy(StrEnum):
    """Owner: AG-04."""

    SYSTEM = "SYSTEM"
    INSPECTOR = "INSPECTOR"


class CheckKind(StrEnum):
    """Owner: AG-04."""

    MATRIX = "MATRIX"
    RULE = "RULE"
    SUSPICION_CONVERTED = "SUSPICION_CONVERTED"
    SPLIT_CHILD = "SPLIT_CHILD"


class CheckLifecycle(StrEnum):
    """Owner: AG-05."""

    ACTIVE = "ACTIVE"
    SPLIT = "SPLIT"
    SUPERSEDED = "SUPERSEDED"


class ReviewRequiredReason(StrEnum):
    """Owner: AG-05."""

    SOURCE_SUPERSEDED = "SOURCE_SUPERSEDED"
    VALUE_CHANGED = "VALUE_CHANGED"
    APPROVED_CHANGE_FOUND = "APPROVED_CHANGE_FOUND"
    OUTCOME_CHANGED = "OUTCOME_CHANGED"


class EvidenceRole(StrEnum):
    """Owner: AG-04."""

    EXPECTED = "EXPECTED"  # Эталон (ожидаемое значение)
    ACTUAL = "ACTUAL"  # Факт (фактическое значение)
    SUPPORTING_EXPECTED = "SUPPORTING_EXPECTED"  # Дополнительно к эталону
    SUPPORTING_ACTUAL = "SUPPORTING_ACTUAL"  # Дополнительно к факту
    APPROVED_CHANGE = "APPROVED_CHANGE"  # Согласованное изменение
    NORMATIVE = "NORMATIVE"  # Норматив
    CONTEXT = "CONTEXT"  # Контекст


class FragmentOrigin(StrEnum):
    """Owner: AG-05."""

    SYSTEM = "SYSTEM"
    INSPECTOR = "INSPECTOR"
    SPLIT_COPY = "SPLIT_COPY"


class InspectorStatus(StrEnum):
    """Owner: AG-05."""

    PENDING = "PENDING"  # Ожидает решения
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"  # Подтверждено
    NEGATIVE_VERIFIED = "NEGATIVE_VERIFIED"  # Отклонено
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"  # Требует уточнения


class DecisionType(StrEnum):
    """Owner: AG-05."""

    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
    NEGATIVE_VERIFIED = "NEGATIVE_VERIFIED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    REVERT_TO_PENDING = "REVERT_TO_PENDING"


class DecisionCodeKind(StrEnum):
    """Owner: AG-05."""

    REJECT = "REJECT"
    CONFIRM = "CONFIRM"
    CLARIFY = "CLARIFY"
    REVISION_BASIS = "REVISION_BASIS"
    SUSPICION_DISMISS = "SUSPICION_DISMISS"
    UNFINALIZE = "UNFINALIZE"


class AiVerdict(StrEnum):
    """Owner: AG-05."""

    AGREE = "AGREE"  # ИИ согласен
    UNCERTAIN = "UNCERTAIN"  # ИИ не уверен
    DISAGREE = "DISAGREE"  # ИИ не согласен


class DisputeResolutionStatus(StrEnum):
    """Owner: AG-05."""

    OPEN = "OPEN"
    INSPECTOR_UPHELD = "INSPECTOR_UPHELD"
    AI_UPHELD = "AI_UPHELD"
    KEPT_CLARIFICATION = "KEPT_CLARIFICATION"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class PlannedAction(StrEnum):
    """Owner: AG-05."""

    ISSUE_ORDER = "ISSUE_ORDER"
    REQUEST_EXPLANATION = "REQUEST_EXPLANATION"
    REQUEST_DOCUMENTS = "REQUEST_DOCUMENTS"
    SCHEDULE_INSPECTION = "SCHEDULE_INSPECTION"
    NO_FURTHER_ACTION = "NO_FURTHER_ACTION"


class DiscoveryMethod(StrEnum):
    """Owner: AG-07."""

    LOGICAL_ANALYSIS = "LOGICAL_ANALYSIS"  # Логический анализ
    SEMANTIC_DISSONANCE = "SEMANTIC_DISSONANCE"  # Семантический диссонанс
    NORMATIVE_ANALYSIS = "NORMATIVE_ANALYSIS"  # Нормативный анализ
    ML_PATTERN_ANALYSIS = "ML_PATTERN_ANALYSIS"  # ML-паттерн-анализ
    GRAPHIC_DIFF = "GRAPHIC_DIFF"  # Графическое сравнение


class SuspicionInspectorStatus(StrEnum):
    """Owner: AG-07."""

    PENDING = "PENDING"  # Ожидает решения
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"  # Требует уточнения
    CONVERTED_TO_CANDIDATE = "CONVERTED_TO_CANDIDATE"  # Переведено в кандидаты
    DISMISSED = "DISMISSED"  # Отклонено
    STALE = "STALE"  # Устарело после дозагрузки


class PromotedBy(StrEnum):
    """Owner: AG-07."""

    INSPECTOR = "INSPECTOR"
    SYSTEM = "SYSTEM"


class EvidenceBindStatus(StrEnum):
    """Owner: AG-07."""

    UNBOUND = "UNBOUND"
    PARTIAL = "PARTIAL"
    BOUND = "BOUND"


class RetrainingStatus(StrEnum):
    """Owner: AG-05."""

    NEW = "NEW"
    IN_DRAFT = "IN_DRAFT"
    DISPUTED = "DISPUTED"
    CURATOR_ACCEPTED = "CURATOR_ACCEPTED"
    CURATOR_EXCLUDED = "CURATOR_EXCLUDED"
    RELEASED = "RELEASED"
    USED_IN_TRAINING = "USED_IN_TRAINING"
    REVOKED = "REVOKED"


class GoldLabel(StrEnum):
    """Owner: AG-05."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class DatasetItemStatus(StrEnum):
    """Owner: AG-05."""

    DRAFT = "DRAFT"
    PENDING_CURATION = "PENDING_CURATION"
    INELIGIBLE = "INELIGIBLE"
    DISPUTED = "DISPUTED"
    SUSPENDED = "SUSPENDED"
    ACCEPTED = "ACCEPTED"
    EXCLUDED = "EXCLUDED"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"
    REVOKE_PENDING = "REVOKE_PENDING"


class Split(StrEnum):
    """Owner: AG-10."""

    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    HIDDEN_TEST = "HIDDEN_TEST"


class SourceType(StrEnum):
    """Owner: AG-05."""

    PRODUCTION = "PRODUCTION"
    PILOT = "PILOT"
    SYNTHETIC = "SYNTHETIC"
    IMPORTED = "IMPORTED"


class DatasetVersionStatus(StrEnum):
    """Owner: AG-05."""

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    RELEASED = "RELEASED"
    DEPRECATED = "DEPRECATED"
    REVOKED = "REVOKED"


class ModelApprovalStatus(StrEnum):
    """Owner: AG-05."""

    TRAINING = "TRAINING"
    TRAINED = "TRAINED"
    GATE_FAILED = "GATE_FAILED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPLOYED = "DEPLOYED"
    ROLLED_BACK = "ROLLED_BACK"
    RETIRED = "RETIRED"
    FAILED = "FAILED"


class TrainingJobStatus(StrEnum):
    """Owner: AG-05."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class EvalKind(StrEnum):
    """Owner: AG-10."""

    VALIDATION = "VALIDATION"
    HIDDEN_TEST = "HIDDEN_TEST"
    OCR_BENCH = "OCR_BENCH"
    EXTERNAL_GOLD = "EXTERNAL_GOLD"
    PILOT = "PILOT"
    SYNTHETIC = "SYNTHETIC"
    BATCH = "BATCH"
    SUBMISSION_SCORE = "SUBMISSION_SCORE"


class SyncStatus(StrEnum):
    """Owner: AG-00."""

    NOT_REQUIRED = "NOT_REQUIRED"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    PENDING_SYNC = "PENDING_SYNC"
    SYNCED = "SYNCED"
    SYNC_FAILED = "SYNC_FAILED"
    CANCELLED = "CANCELLED"


class DeliveryAttemptOutcome(StrEnum):
    """Owner: AG-00."""

    SUCCESS = "SUCCESS"
    RETRYABLE_HTTP = "RETRYABLE_HTTP"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    NON_RETRYABLE = "NON_RETRYABLE"
    DUPLICATE_OK = "DUPLICATE_OK"


class RinInboxStatus(StrEnum):
    """Owner: AG-00."""

    NEW = "NEW"
    DOWNLOADED = "DOWNLOADED"
    REJECTED_AV = "REJECTED_AV"
    FAILED_HASH = "FAILED_HASH"
    QUEUED_FOR_PROCESS = "QUEUED_FOR_PROCESS"
    ATTACHED = "ATTACHED"
    BLOCKED_FINALIZED = "BLOCKED_FINALIZED"
    AWAITING_INSPECTOR = "AWAITING_INSPECTOR"
    NEW_CHECK_CREATED = "NEW_CHECK_CREATED"
    DISMISSED = "DISMISSED"


class PrescriptionStatus(StrEnum):
    """Owner: AG-00."""

    ISSUED = "ISSUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXTENDED = "EXTENDED"


class Role(StrEnum):
    """Owner: AG-00."""

    INSPECTOR = "INSPECTOR"  # Инспектор


class AuditCategory(StrEnum):
    """Owner: AG-00."""

    BUSINESS = "BUSINESS"
    SECURITY = "SECURITY"
    SYSTEM = "SYSTEM"
    INTEGRATION = "INTEGRATION"
    ACCESS = "ACCESS"


class RetentionClass(StrEnum):
    """Owner: AG-00."""

    STANDARD = "STANDARD"
    SECURITY = "SECURITY"
    PERMANENT = "PERMANENT"


class IndicatorColor(StrEnum):
    """Owner: AG-08."""

    RED = "RED"  # Красный
    YELLOW = "YELLOW"  # Жёлтый
    GREEN = "GREEN"  # Зелёный
    NONE = "NONE"  # Нет данных


class IssueScope(StrEnum):
    """Owner: AG-10."""

    PACKAGE = "PACKAGE"
    FILE = "FILE"
    PAGE = "PAGE"
    ZONE = "ZONE"
    REGISTRY_ROW = "REGISTRY_ROW"
    REVISION_GROUP = "REVISION_GROUP"
    PARAM = "PARAM"
    JOB = "JOB"
    SYNC = "SYNC"
    SYSTEM = "SYSTEM"


class IssueSeverity(StrEnum):
    """Owner: AG-10."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class IssueStatus(StrEnum):
    """Owner: AG-10."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


class ExportFormat(StrEnum):
    """Owner: AG-04."""

    PDF = "pdf"
    DOCX = "docx"
    XML = "xml"
    JSON = "json"
    GOLD_JSONL = "gold_jsonl"
    GOLD_XLSX = "gold_xlsx"
    GOLD_CSV = "gold_csv"


class NotificationType(StrEnum):
    """Owner: AG-00."""

    PROTOCOL_READY = "PROTOCOL_READY"
    PROTOCOL_UPDATED = "PROTOCOL_UPDATED"
    UPLOAD_REJECTED = "UPLOAD_REJECTED"
    FILE_REJECTED_ASYNC = "FILE_REJECTED_ASYNC"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    NEW_DOCS_AFTER_FINALIZATION = "NEW_DOCS_AFTER_FINALIZATION"
    SYNC_PENDING = "SYNC_PENDING"
    SYNC_FAILED = "SYNC_FAILED"
    PROTOCOL_UNFINALIZED = "PROTOCOL_UNFINALIZED"
    PRESCRIPTION_STATUS_CHANGED = "PRESCRIPTION_STATUS_CHANGED"
    MATRIX_UPDATED = "MATRIX_UPDATED"
    DATASET_DRAFT_ITEMS = "DATASET_DRAFT_ITEMS"
    MODEL_PENDING_APPROVAL = "MODEL_PENDING_APPROVAL"
    WEEKLY_REPORT_READY = "WEEKLY_REPORT_READY"
    ADMIN_ALERT = "ADMIN_ALERT"


class ArtifactKind(StrEnum):
    """Owner: AG-00."""

    RUN_MANIFEST = "RUN_MANIFEST"  # Манифест прогона
    RUN_CONTEXT = "RUN_CONTEXT"  # Контекст команды
    RUN_ARTIFACTS = "RUN_ARTIFACTS"  # Реестр артефактов прогона
    PIPELINE_SUMMARY = "PIPELINE_SUMMARY"  # Итог сквозного прогона
    INVENTORY_INDEX = "INVENTORY_INDEX"  # Индекс инвентаризации
    INVENTORY = "INVENTORY"  # Инвентаризация объекта
    PAGE_TOKENS = "PAGE_TOKENS"  # Токены страницы
    TOKENS_INDEX = "TOKENS_INDEX"  # Индекс распознавания
    RECOGNIZE_SUMMARY = "RECOGNIZE_SUMMARY"  # Сводка распознавания
    LAYOUT = "LAYOUT"  # Разметка листов (штампы, помещения, марки, слои)
    TABLES = "TABLES"  # Типизированные таблицы
    EXTRACTED_VALUES = "EXTRACTED_VALUES"  # Извлечённые значения
    FINDING_GROUPS = "FINDING_GROUPS"  # Группы находок
    FINDINGS = "FINDINGS"  # Атомарные находки
    PROTOCOL_JSON = "PROTOCOL_JSON"  # Протокол (JSON)
    PROTOCOL_DOCX = "PROTOCOL_DOCX"  # Протокол (DOCX)
    PROTOCOL_PDF = "PROTOCOL_PDF"  # Протокол (PDF)
    SUBMISSION = "SUBMISSION"  # Ответ (полный)
    SUBMISSION_STRICT = "SUBMISSION_STRICT"  # Ответ (только поля схемы)
    SUBMISSION_SIDECAR = "SUBMISSION_SIDECAR"  # Сопроводительный файл ответа
    SCORE = "SCORE"  # Локальная оценка


class ArtifactFormat(StrEnum):
    """Owner: AG-00."""

    JSON = "JSON"
    JSONL = "JSONL"
    JSON_GZ = "JSON_GZ"
    CSV = "CSV"
    TXT = "TXT"
    DOCX = "DOCX"
    PDF = "PDF"


class ArtifactScope(StrEnum):
    """Owner: AG-00."""

    RUN = "RUN"  # Один на прогон
    OBJECT = "OBJECT"  # Один на объект
    FILE = "FILE"  # Один на файл
    PAGE = "PAGE"  # Один на страницу


class TagKind(StrEnum):
    """Owner: AG-02B."""

    ROOM_NUMBER = "ROOM_NUMBER"  # Номер помещения
    VENT_SYSTEM = "VENT_SYSTEM"  # Марка системы вентиляции (П1, В2, ПВ3)
    HEATING_SYSTEM = "HEATING_SYSTEM"  # Марка системы отопления / тёплого пола
    AIR_TERMINAL = "AIR_TERMINAL"  # Воздухораспределитель / решётка
    EQUIPMENT = "EQUIPMENT"  # Оборудование (установка, вентилятор, клапан)
    PIPE_RISER = "PIPE_RISER"  # Стояк
    AXIS = "AXIS"  # Координационная ось
    LEVEL_MARK = "LEVEL_MARK"  # Отметка уровня
    SHEET_REF = "SHEET_REF"  # Ссылка на лист / узел
    OTHER = "OTHER"  # Прочее


class TagRoomLink(StrEnum):
    """Owner: AG-02B."""

    INSIDE = "INSIDE"  # Внутри контура помещения
    NEAREST = "NEAREST"  # Ближайший номер помещения
    LEADER = "LEADER"  # По выноске


class SheetMapBasis(StrEnum):
    """Owner: AG-02B."""

    TITLE_BLOCK = "TITLE_BLOCK"  # Лист из штампа
    QR = "QR"  # Лист из QR-кода
    SEQUENCE_SMOOTHED = "SEQUENCE_SMOOTHED"  # Восстановлен по последовательности
    CONTENTS_TABLE = "CONTENTS_TABLE"  # Из ведомости листов / состава проекта
    MANUAL = "MANUAL"  # Указан вручную


class RoomSource(StrEnum):
    """Owner: AG-02B."""

    PLAN_LABEL = "PLAN_LABEL"  # Номер на плане
    EXPLICATION_TABLE = "EXPLICATION_TABLE"  # Экспликация помещений
    SCHEMATIC_LABEL = "SCHEMATIC_LABEL"  # Подпись на схеме
    TEXT_MENTION = "TEXT_MENTION"  # Упоминание в тексте
    MANUAL = "MANUAL"  # Указан вручную


class RevisionCloudSource(StrEnum):
    """Owner: AG-02B."""

    OCG_LAYER = "OCG_LAYER"  # Слой САПР изменения
    VECTOR_SHAPE = "VECTOR_SHAPE"  # Облако изменения по геометрии
    MANUAL = "MANUAL"  # Указано вручную


class TableType(StrEnum):
    """Owner: AG-02C."""

    EXPLICATION = "EXPLICATION"  # Экспликация помещений
    TEP = "TEP"  # Технико-экономические показатели
    SPEC_21110 = "SPEC_21110"  # Спецификация оборудования (ГОСТ 21.110)
    DEVIATION = "DEVIATION"  # Ведомость отклонений / исполнительная схема
    CHANGE_LOG = "CHANGE_LOG"  # Таблица регистрации изменений
    AOSR = "AOSR"  # Акт освидетельствования скрытых работ
    ID_REGISTRY = "ID_REGISTRY"  # Реестр исполнительной документации
    PROJECT_COMPOSITION = "PROJECT_COMPOSITION"  # Состав проекта / ведомость листов


class TableRowKind(StrEnum):
    """Owner: AG-02C."""

    DATA = "DATA"  # Строка данных
    SUBTOTAL = "SUBTOTAL"  # Промежуточный итог
    TOTAL = "TOTAL"  # Итог
    SUBZONE = "SUBZONE"  # «В том числе» (входит в родительскую строку)
    SECTION_HEADER = "SECTION_HEADER"  # Заголовок раздела таблицы
    NOTE = "NOTE"  # Примечание


class TableCheckKind(StrEnum):
    """Owner: AG-02C."""

    SUM_MATCHES_TOTAL = "SUM_MATCHES_TOTAL"  # Сумма строк равна итогу
    SUBZONE_DOUBLE_COUNT = "SUBZONE_DOUBLE_COUNT"  # Подзона «в том числе» учтена дважды
    ROW_COUNT = "ROW_COUNT"  # Число строк
    HEADER_MATCHED = "HEADER_MATCHED"  # Шапка таблицы распознана
    UNIT_CONSISTENT = "UNIT_CONSISTENT"  # Единицы измерения согласованы
    CONTINUATION_JOINED = "CONTINUATION_JOINED"  # Продолжение таблицы склеено


class ProtocolSummaryRow(StrEnum):
    """Owner: AG-04."""

    TOTAL_PARAMS = "TOTAL_PARAMS"  # Всего параметров в Матрице
    CHECKED_OK = "CHECKED_OK"  # Проверено успешно (есть ПД, РД, ИД)
    NOT_CHECKED_NO_ID = "NOT_CHECKED_NO_ID"  # Не проверено (отсутствует ИД)
    NOT_LOADED_TECH_ERRORS = "NOT_LOADED_TECH_ERRORS"  # Не загружены документы (технические ошибки)
    NOT_CHECKED_NO_PD_RD = "NOT_CHECKED_NO_PD_RD"  # Не проверено (отсутствует ПД/РД)
    NOT_CHECKED_REVISION_CONFLICT = "NOT_CHECKED_REVISION_CONFLICT"  # Не проверено (конфликт редакций, требуется уточнение)
    NOT_APPLICABLE = "NOT_APPLICABLE"  # Неприменимо к объекту
    VIOLATIONS_TOTAL = "VIOLATIONS_TOTAL"  # Выявлено нарушений (всего)
    VIOLATIONS_CRITICAL = "VIOLATIONS_CRITICAL"  # ─ Критических (приостановка)
    VIOLATIONS_SUBSTANTIAL = "VIOLATIONS_SUBSTANTIAL"  # ─ Существенных (предписание)
    VIOLATIONS_CONFIRMED = "VIOLATIONS_CONFIRMED"  # ─ из них подтверждено инспектором
    AI_SUSPICIONS = "AI_SUSPICIONS"  # Подозрений ИИ (свободный поиск)


class DeviationDirection(StrEnum):
    """Owner: AG-04."""

    DECREASE = "DECREASE"  # Снижение
    INCREASE = "INCREASE"  # Превышение
    ABSENT = "ABSENT"  # Отсутствие
    CHANGED = "CHANGED"  # Изменение


class DecisionRejectReason(StrEnum):
    """Owner: AG-05."""

    WRONG_REVISION = "WRONG_REVISION"  # Актуальная редакция выбрана неверно
    APPROVED_CHANGE = "APPROVED_CHANGE"  # Согласованное изменение
    OCR_ERROR = "OCR_ERROR"  # Ошибка распознавания (OCR)
    EXTRACTION_ERROR = "EXTRACTION_ERROR"  # Ошибка извлечения значения (ячейка, единица измерения, множитель)
    CV_ERROR = "CV_ERROR"  # Ошибка распознавания графики (линии, условные обозначения, масштаб)
    LINKING_ERROR = "LINKING_ERROR"  # Ошибка привязки (не тот объект / лист / помещение / элемент)
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"  # Расхождение в пределах допуска / нормы
    EQUIVALENT_SOLUTION = "EQUIVALENT_SOLUTION"  # Равнозначное решение (иное обозначение / формулировка)
    METHODOLOGY_DIFFERENCE = "METHODOLOGY_DIFFERENCE"  # Различие методики подсчёта (без изменения решения)
    NOT_APPLICABLE_PARAM = "NOT_APPLICABLE_PARAM"  # Параметр неприменим к объекту / виду работ
    DUPLICATE = "DUPLICATE"  # Дубликат другого finding
    OTHER = "OTHER"  # Иное


class DecisionConfirmBasis(StrEnum):
    """Owner: AG-05."""

    CV_DEVIATION_PD_RD = "CV_DEVIATION_PD_RD"  # Решение РД не соответствует утверждённой ПД; согласованное изменение отсутствует
    CV_MISSING_IN_RD = "CV_MISSING_IN_RD"  # Решение ПД не отражено в РД
    CV_NOT_PER_RD = "CV_NOT_PER_RD"  # Выполненные работы (ИД) не соответствуют РД
    CV_TOLERANCE_EXCEEDED = "CV_TOLERANCE_EXCEEDED"  # Превышение допустимых отклонений по ИД
    CV_UNAPPROVED_CHANGE = "CV_UNAPPROVED_CHANGE"  # Изменение внесено без требуемого согласования / экспертизы
    CV_NORM_VIOLATION = "CV_NORM_VIOLATION"  # Нарушение нормативного требования (СП/ГОСТ)


class DecisionClarifyBasis(StrEnum):
    """Owner: AG-05."""

    REVISION_CONFLICT = "REVISION_CONFLICT"  # Конфликт редакций
    APPROVAL_UNKNOWN = "APPROVAL_UNKNOWN"  # Нет признака утверждения
    AMBIGUOUS_CHAIN = "AMBIGUOUS_CHAIN"  # Неоднозначная связь predecessor/successor
    NO_REGISTRY = "NO_REGISTRY"  # Реестр файлов не представлен
    AWAITING_DOCUMENT = "AWAITING_DOCUMENT"  # Ожидается документ от застройщика
    AWAITING_APPROVAL_CHECK = "AWAITING_APPROVAL_CHECK"  # Требуется проверка согласования изменения
    SOURCE_UNREADABLE = "SOURCE_UNREADABLE"  # Исходный документ нечитаем / листы не сопоставлены
    EXPERT_CONSULTATION = "EXPERT_CONSULTATION"  # Требуется консультация профильного специалиста


class RevisionBasis(StrEnum):
    """Owner: AG-05."""

    REGISTRY_CONFIRMED = "REGISTRY_CONFIRMED"  # Подтверждено реестром
    STAMP_IN_PRODUCTION = "STAMP_IN_PRODUCTION"  # Штамп «В производство работ»
    APPROVAL_LETTER = "APPROVAL_LETTER"  # Письмо о согласовании
    CUSTOMER_CONFIRMATION = "CUSTOMER_CONFIRMATION"  # Подтверждение заказчика
    LATEST_UKEP_SIGNED = "LATEST_UKEP_SIGNED"  # Последняя подписанная УКЭП редакция
    OTHER = "OTHER"  # Иное


class SuspicionDismissReason(StrEnum):
    """Owner: AG-05."""

    NO_EVIDENCE = "NO_EVIDENCE"  # Нет доказательств
    FALSE_HYPOTHESIS = "FALSE_HYPOTHESIS"  # Гипотеза неверна
    DUPLICATE_OF_MATRIX_FINDING = "DUPLICATE_OF_MATRIX_FINDING"  # Дублирует находку по матрице
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # Вне предмета проверки
    OTHER = "OTHER"  # Иное


class UnfinalizeReason(StrEnum):
    """Owner: AG-05."""

    DECISION_ERROR = "DECISION_ERROR"  # Ошибка в решении
    NEW_DOCUMENTS = "NEW_DOCUMENTS"  # Поступили новые документы
    RIN_REJECTED = "RIN_REJECTED"  # Отклонено РиН
    SUPERVISOR_REVIEW = "SUPERVISOR_REVIEW"  # Повторная проверка решений
    OTHER = "OTHER"  # Иное


class CommentSource(StrEnum):
    """Owner: AG-05."""

    TEMPLATE = "TEMPLATE"  # Шаблон
    EDITED = "EDITED"  # Шаблон, отредактирован
    MANUAL = "MANUAL"  # Вручную


class GoldEffect(StrEnum):
    """Owner: AG-05."""

    POSITIVE_DRAFT = "POSITIVE_DRAFT"
    NEGATIVE_DRAFT = "NEGATIVE_DRAFT"
    WITHDRAW = "WITHDRAW"
    NONE = "NONE"


class PermissionScope(StrEnum):
    """Owner: AG-00."""

    ALL = "ALL"  # Все объекты
    ASSIGNED = "ASSIGNED"  # Назначенные объекты
    OWN = "OWN"  # Только собственные


class AuditActorType(StrEnum):
    """Owner: AG-00."""

    USER = "USER"  # Пользователь
    SYSTEM = "SYSTEM"  # Система
    INTEGRATION = "INTEGRATION"  # Внешняя система
    ANONYMOUS = "ANONYMOUS"  # Без входа в систему


class AuditResult(StrEnum):
    """Owner: AG-00."""

    SUCCESS = "SUCCESS"  # Успешно
    FAILURE = "FAILURE"  # Ошибка
    DENIED = "DENIED"  # Отказано в доступе


class AuditObjectType(StrEnum):
    """Owner: AG-00."""

    USER = "USER"  # Пользователь
    SESSION = "SESSION"  # Сессия
    OBJECT = "OBJECT"  # Объект
    FILE = "FILE"  # Файл
    PAGE = "PAGE"  # Страница
    BATCH_RUN = "BATCH_RUN"  # Пакетный прогон
    PROCESS = "PROCESS"  # Проверка
    PROTOCOL = "PROTOCOL"  # Протокол
    FINDING = "FINDING"  # Находка
    SUSPICION = "SUSPICION"  # Подозрение ИИ
    DECISION = "DECISION"  # Решение инспектора
    PARAM = "PARAM"  # Параметр матрицы
    NORMATIVE = "NORMATIVE"  # Норматив
    CONFIG = "CONFIG"  # Настройка


class AuditAction(StrEnum):
    """Owner: AG-00."""

    AUTH_LOGIN_SUCCESS = "AUTH_LOGIN_SUCCESS"  # Вход в систему
    AUTH_LOGIN_FAILED = "AUTH_LOGIN_FAILED"  # Неудачная попытка входа
    AUTH_LOCKED = "AUTH_LOCKED"  # Учётная запись заблокирована
    AUTH_LOGOUT = "AUTH_LOGOUT"  # Выход из системы
    AUTH_REAUTH = "AUTH_REAUTH"  # Подтверждение паролем
    AUTH_PASSWORD_CHANGED = "AUTH_PASSWORD_CHANGED"  # Смена пароля
    SESSION_REVOKED = "SESSION_REVOKED"  # Сессия отозвана
    ACCESS_DENIED = "ACCESS_DENIED"  # Отказ в доступе
    USER_CREATED = "USER_CREATED"  # Пользователь создан
    USER_UPDATED = "USER_UPDATED"  # Пользователь изменён
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"  # Роли пользователя изменены
    USER_DEACTIVATED = "USER_DEACTIVATED"  # Пользователь отключён
    OBJECT_ASSIGNMENT_CHANGED = "OBJECT_ASSIGNMENT_CHANGED"  # Назначение объекта изменено
    CONFIG_CHANGED = "CONFIG_CHANGED"  # Настройка изменена
    PARAM_UPDATED = "PARAM_UPDATED"  # Параметр матрицы изменён
    BATCH_RUN_IMPORTED = "BATCH_RUN_IMPORTED"  # Импорт пакетного прогона
    PROTOCOL_VERSION_CREATED = "PROTOCOL_VERSION_CREATED"  # Создана версия протокола
    PROTOCOL_OPENED = "PROTOCOL_OPENED"  # Протокол открыт
    EVIDENCE_VIEWED = "EVIDENCE_VIEWED"  # Просмотр доказательства
    FINDING_CONFIRMED = "FINDING_CONFIRMED"  # Нарушение подтверждено
    FINDING_REJECTED = "FINDING_REJECTED"  # Нарушение отклонено
    FINDING_CLARIFICATION_REQUESTED = "FINDING_CLARIFICATION_REQUESTED"  # Запрошено уточнение
    FINDING_DECISION_REVERTED = "FINDING_DECISION_REVERTED"  # Решение отменено
    DECISION_OVERRIDE = "DECISION_OVERRIDE"  # Решение заменено
    FINDING_SPLIT = "FINDING_SPLIT"  # Находка разделена
    REVISION_SELECTED = "REVISION_SELECTED"  # Выбрана действующая редакция
    SUSPICION_PROMOTED = "SUSPICION_PROMOTED"  # Подозрение переведено в кандидаты
    SUSPICION_DISMISSED = "SUSPICION_DISMISSED"  # Подозрение отклонено
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"  # Верификация завершена
    PROTOCOL_FINALIZED = "PROTOCOL_FINALIZED"  # Протокол финализирован
    PROTOCOL_UNFINALIZED = "PROTOCOL_UNFINALIZED"  # Финализация отменена
    PROTOCOL_EXPORTED = "PROTOCOL_EXPORTED"  # Протокол выгружен
    RIN_SYNC_REQUESTED = "RIN_SYNC_REQUESTED"  # Отправка протокола в ИАИС «РиН» запрошена
    RIN_SYNC_RESULT = "RIN_SYNC_RESULT"  # Результат обмена с ИАИС «РиН»
    SELFTEST_RUN = "SELFTEST_RUN"  # Запуск самопроверки
    RETENTION_PURGE_EXECUTED = "RETENTION_PURGE_EXECUTED"  # Очистка журнала по срокам хранения
    HTTP_POST = "HTTP_POST"  # Изменение данных (POST)
    HTTP_PUT = "HTTP_PUT"  # Изменение данных (PUT)
    HTTP_PATCH = "HTTP_PATCH"  # Изменение данных (PATCH)
    HTTP_DELETE = "HTTP_DELETE"  # Удаление данных (DELETE)


class ErrorCode(StrEnum):
    """Codes of packages/contracts/errors.yaml."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    MALFORMED_JSON = "MALFORMED_JSON"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    NOT_FOUND = "NOT_FOUND"
    PROCESS_NOT_FOUND = "PROCESS_NOT_FOUND"
    PROCESS_STATE_CONFLICT = "PROCESS_STATE_CONFLICT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    NOT_ACCEPTABLE = "NOT_ACCEPTABLE"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    PRECONDITION_REQUIRED = "PRECONDITION_REQUIRED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    RESULT_NOT_READY = "RESULT_NOT_READY"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RESPONSE_SCHEMA_VIOLATION = "RESPONSE_SCHEMA_VIOLATION"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    MAINTENANCE_MODE = "MAINTENANCE_MODE"
    UPSTREAM_BAD_RESPONSE = "UPSTREAM_BAD_RESPONSE"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    IP_TEMPORARILY_BLOCKED = "IP_TEMPORARILY_BLOCKED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    CSRF_TOKEN_INVALID = "CSRF_TOKEN_INVALID"
    FORBIDDEN = "FORBIDDEN"
    SEPARATION_OF_DUTIES = "SEPARATION_OF_DUTIES"
    SESSION_STORE_UNAVAILABLE = "SESSION_STORE_UNAVAILABLE"
    PASSWORD_POLICY_VIOLATION = "PASSWORD_POLICY_VIOLATION"
    PAGE_NOT_FOUND = "PAGE_NOT_FOUND"
    FILE_NOT_RENDERABLE = "FILE_NOT_RENDERABLE"
    PAGE_RENDERER_UNAVAILABLE = "PAGE_RENDERER_UNAVAILABLE"
    NO_FILES = "NO_FILES"
    NO_ACCEPTED_FILES = "NO_ACCEPTED_FILES"
    PACKAGE_TOO_LARGE = "PACKAGE_TOO_LARGE"
    TOO_MANY_FILES = "TOO_MANY_FILES"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    EMPTY_FILE = "EMPTY_FILE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"
    MACRO_ENABLED_DOCUMENT = "MACRO_ENABLED_DOCUMENT"
    FILENAME_INVALID = "FILENAME_INVALID"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    VIRUS_DETECTED = "VIRUS_DETECTED"
    AV_UNAVAILABLE = "AV_UNAVAILABLE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    FILE_ID_IMMUTABLE = "FILE_ID_IMMUTABLE"
    PROCESS_BUSY = "PROCESS_BUSY"
    PROTOCOL_FINALIZED = "PROTOCOL_FINALIZED"
    MULTIPART_MALFORMED = "MULTIPART_MALFORMED"
    UPLOAD_INCOMPLETE = "UPLOAD_INCOMPLETE"
    FILE_CORRUPTED = "FILE_CORRUPTED"
    FILE_ENCRYPTED = "FILE_ENCRYPTED"
    ARCHIVE_BOMB_SUSPECTED = "ARCHIVE_BOMB_SUSPECTED"
    EMBEDDED_EXECUTABLE = "EMBEDDED_EXECUTABLE"
    TOO_MANY_PAGES = "TOO_MANY_PAGES"
    XML_MALFORMED = "XML_MALFORMED"
    XML_FORBIDDEN_DTD = "XML_FORBIDDEN_DTD"
    XML_ENCODING_INVALID = "XML_ENCODING_INVALID"
    XML_LIMITS_EXCEEDED = "XML_LIMITS_EXCEEDED"
    DUPLICATE_FILE = "DUPLICATE_FILE"
    DUPLICATE_IN_PACKAGE = "DUPLICATE_IN_PACKAGE"
    PDF_REPAIRED = "PDF_REPAIRED"
    PDF_PERMISSIONS_RESTRICTED = "PDF_PERMISSIONS_RESTRICTED"
    PDF_ACTIVE_CONTENT = "PDF_ACTIVE_CONTENT"
    PDF_HAS_REVIEW_MARKUP = "PDF_HAS_REVIEW_MARKUP"
    EXTERNAL_REFERENCES_IGNORED = "EXTERNAL_REFERENCES_IGNORED"
    RENDER_CAPPED = "RENDER_CAPPED"
    LARGE_DOCUMENT = "LARGE_DOCUMENT"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"
    LOW_DPI = "LOW_DPI"
    SKEW_CORRECTED = "SKEW_CORRECTED"
    SKEW_RESIDUAL = "SKEW_RESIDUAL"
    HANDWRITING_ZONES = "HANDWRITING_ZONES"
    SEAL_OVERLAP = "SEAL_OVERLAP"
    OCR_PARTIAL = "OCR_PARTIAL"
    LOW_COVERAGE = "LOW_COVERAGE"
    RENDITION_FAILED = "RENDITION_FAILED"
    DRAFT_NEWER_EXISTS = "DRAFT_NEWER_EXISTS"
    META_OBJECT_MISMATCH = "META_OBJECT_MISMATCH"
    META_CONFLICT = "META_CONFLICT"
    SIGNATURE_MISSING = "SIGNATURE_MISSING"
    REQUISITES_MISSING = "REQUISITES_MISSING"
    REGISTRY_MISSING = "REGISTRY_MISSING"
    REGISTRY_FORMAT_UNSUPPORTED = "REGISTRY_FORMAT_UNSUPPORTED"
    REGISTRY_UNREADABLE = "REGISTRY_UNREADABLE"
    REGISTRY_COLUMN_MISSING = "REGISTRY_COLUMN_MISSING"
    REGISTRY_ROW_INVALID = "REGISTRY_ROW_INVALID"
    REGISTRY_DUPLICATE_FILE_ID = "REGISTRY_DUPLICATE_FILE_ID"
    REGISTRY_FILE_NOT_UPLOADED = "REGISTRY_FILE_NOT_UPLOADED"
    REGISTRY_FILE_NOT_LISTED = "REGISTRY_FILE_NOT_LISTED"
    REGISTRY_HASH_MISMATCH = "REGISTRY_HASH_MISMATCH"
    REGISTRY_AMBIGUOUS_MATCH = "REGISTRY_AMBIGUOUS_MATCH"
    REGISTRY_OBJECT_MISMATCH = "REGISTRY_OBJECT_MISMATCH"
    REGISTRY_PAGE_RANGE_INVALID = "REGISTRY_PAGE_RANGE_INVALID"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    APPROVAL_STATUS_MISSING = "APPROVAL_STATUS_MISSING"
    REVISION_CHAIN_CYCLE = "REVISION_CHAIN_CYCLE"
    REVISION_CHAIN_FORK = "REVISION_CHAIN_FORK"
    REVISION_CHAIN_DANGLING = "REVISION_CHAIN_DANGLING"
    REVISION_DATE_INVERSION = "REVISION_DATE_INVERSION"
    REVISION_LABEL_DUPLICATE = "REVISION_LABEL_DUPLICATE"
    CURRENT_REVISION_NOT_UPLOADED = "CURRENT_REVISION_NOT_UPLOADED"
    SUPERSEDED_REVISION_NOT_ALLOWED = "SUPERSEDED_REVISION_NOT_ALLOWED"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
    PARSE_RESOURCE_LIMIT = "PARSE_RESOURCE_LIMIT"
    WORKER_CRASHED = "WORKER_CRASHED"
    JOB_DEAD_LETTERED = "JOB_DEAD_LETTERED"
    OCR_FAILED = "OCR_FAILED"
    PAGE_UNREADABLE = "PAGE_UNREADABLE"
    OCR_MODEL_MISSING = "OCR_MODEL_MISSING"
    ENGINE_ERROR = "ENGINE_ERROR"
    RECHECK_FAILED = "RECHECK_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
    DB_UNAVAILABLE = "DB_UNAVAILABLE"
    DB_BUSY = "DB_BUSY"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
    CACHE_UNAVAILABLE = "CACHE_UNAVAILABLE"
    ML_API_UNAVAILABLE = "ML_API_UNAVAILABLE"
    RENDERER_UNAVAILABLE = "RENDERER_UNAVAILABLE"
    NOTIFIER_UNAVAILABLE = "NOTIFIER_UNAVAILABLE"
    DISK_SPACE_LOW = "DISK_SPACE_LOW"
    STORAGE_INTEGRITY_VIOLATION = "STORAGE_INTEGRITY_VIOLATION"
    MODEL_ARTIFACT_INTEGRITY_FAILED = "MODEL_ARTIFACT_INTEGRITY_FAILED"
    CONFIG_INVALID = "CONFIG_INVALID"
    PROCESS_STALLED = "PROCESS_STALLED"
    MANDATORY_SOURCE_MISSING = "MANDATORY_SOURCE_MISSING"
    UNIT_INCOMPATIBLE = "UNIT_INCOMPATIBLE"
    VALUE_UNPARSEABLE = "VALUE_UNPARSEABLE"
    SHEETS_NOT_MATCHED = "SHEETS_NOT_MATCHED"
    EVIDENCE_NOT_LOCALIZABLE = "EVIDENCE_NOT_LOCALIZABLE"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    EVIDENCE_CHANGED = "EVIDENCE_CHANGED"
    FINDING_LOCKED_BY_RECHECK = "FINDING_LOCKED_BY_RECHECK"
    VERIFICATION_NOT_ALLOWED_IN_STATUS = "VERIFICATION_NOT_ALLOWED_IN_STATUS"
    REASON_CODE_REQUIRED = "REASON_CODE_REQUIRED"
    COMMENT_REQUIRED = "COMMENT_REQUIRED"
    STATUS_NOT_ALLOWED = "STATUS_NOT_ALLOWED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    FINALIZE_GATE_BLOCKED = "FINALIZE_GATE_BLOCKED"
    UNFINALIZE_FORBIDDEN = "UNFINALIZE_FORBIDDEN"
    UNFINALIZE_REASON_REQUIRED = "UNFINALIZE_REASON_REQUIRED"
    PROTOCOL_NOT_FINALIZED = "PROTOCOL_NOT_FINALIZED"
    EXPORT_FORMAT_UNSUPPORTED = "EXPORT_FORMAT_UNSUPPORTED"
    THRESHOLD_RANGE_INVALID = "THRESHOLD_RANGE_INVALID"
    REGEX_INVALID = "REGEX_INVALID"
    REGEX_UNSAFE = "REGEX_UNSAFE"
    PARAM_CODE_INVALID = "PARAM_CODE_INVALID"
    PARAM_CODE_DUPLICATE = "PARAM_CODE_DUPLICATE"
    HIDDEN_TEST_ACCESS_DENIED = "HIDDEN_TEST_ACCESS_DENIED"
    HIDDEN_TEST_LEAKAGE = "HIDDEN_TEST_LEAKAGE"
    SPLIT_LEAKAGE = "SPLIT_LEAKAGE"
    MODEL_GATE_NOT_PASSED = "MODEL_GATE_NOT_PASSED"
    TEST_SET_HASH_MISMATCH = "TEST_SET_HASH_MISMATCH"
    DATA_ROOT_NOT_FOUND = "DATA_ROOT_NOT_FOUND"
    MANIFEST_UNREADABLE = "MANIFEST_UNREADABLE"
    MANIFEST_ROW_INVALID = "MANIFEST_ROW_INVALID"
    FILE_MISSING_ON_DISK = "FILE_MISSING_ON_DISK"
    EXCLUDED_FILE_REFERENCED = "EXCLUDED_FILE_REFERENCED"
    SUBMISSION_SCHEMA_INVALID = "SUBMISSION_SCHEMA_INVALID"
    CONTRACT_VALIDATION_FAILED = "CONTRACT_VALIDATION_FAILED"
    COMMAND_NOT_IMPLEMENTED = "COMMAND_NOT_IMPLEMENTED"
    PAGE_COUNT_MISMATCH = "PAGE_COUNT_MISMATCH"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    STAGE_UNRESOLVED = "STAGE_UNRESOLVED"
    DWG_TWIN_NOT_FOUND = "DWG_TWIN_NOT_FOUND"
    ARCHIVE_MEMBER_UNSAFE_PATH = "ARCHIVE_MEMBER_UNSAFE_PATH"
    EVIDENCE_FILE_UNKNOWN = "EVIDENCE_FILE_UNKNOWN"
    HIDDEN_TEST_ARTIFACTS_DROPPED = "HIDDEN_TEST_ARTIFACTS_DROPPED"
    PREDICTION_NOT_FOUND = "PREDICTION_NOT_FOUND"
    GOLD_NOT_FOUND = "GOLD_NOT_FOUND"
    HIDDEN_FINAL_NOT_FROZEN = "HIDDEN_FINAL_NOT_FROZEN"


ENUMS: dict[str, type[StrEnum]] = {
    "ViolationLabel": ViolationLabel,
    "ProtocolParamStatus": ProtocolParamStatus,
    "CriticalityLevel": CriticalityLevel,
    "ParameterMappingStatus": ParameterMappingStatus,
    "ComparisonResult": ComparisonResult,
    "LocationType": LocationType,
    "MatrixScope": MatrixScope,
    "DocumentStatus": DocumentStatus,
    "FreeTopic": FreeTopic,
    "SubmissionVariant": SubmissionVariant,
    "ManifestStage": ManifestStage,
    "ManifestSplit": ManifestSplit,
    "ManifestSection": ManifestSection,
    "DatasetRole": DatasetRole,
    "AnnotationStatus": AnnotationStatus,
    "DistributionStatus": DistributionStatus,
    "LabelVisibility": LabelVisibility,
    "GoldStatus": GoldStatus,
    "EvidenceLocalization": EvidenceLocalization,
    "LocalFileStatus": LocalFileStatus,
    "ArchiveMemberRole": ArchiveMemberRole,
    "PageBasis": PageBasis,
    "TextSource": TextSource,
    "ProcessStatus": ProcessStatus,
    "ProcessStage": ProcessStage,
    "RecheckState": RecheckState,
    "ProcessPurpose": ProcessPurpose,
    "ProcessSource": ProcessSource,
    "FileSource": FileSource,
    "ProtocolStatus": ProtocolStatus,
    "ProtocolVersionReason": ProtocolVersionReason,
    "RecheckReason": RecheckReason,
    "IncrementalTrigger": IncrementalTrigger,
    "StageUploadStatus": StageUploadStatus,
    "LoadScenario": LoadScenario,
    "ScenarioBase": ScenarioBase,
    "JobStatus": JobStatus,
    "RunMode": RunMode,
    "RunStatus": RunStatus,
    "EngineStatus": EngineStatus,
    "DocStage": DocStage,
    "ApprovalStatus": ApprovalStatus,
    "SignatureStatus": SignatureStatus,
    "RegistryStatus": RegistryStatus,
    "PackageStatus": PackageStatus,
    "FileIntakeStatus": FileIntakeStatus,
    "FileIntegrityStatus": FileIntegrityStatus,
    "MetaSource": MetaSource,
    "MetaStatus": MetaStatus,
    "SelectionBasis": SelectionBasis,
    "CompletenessItemStatus": CompletenessItemStatus,
    "ChecklistLevel": ChecklistLevel,
    "PageClass": PageClass,
    "QualityFlag": QualityFlag,
    "ZoneSource": ZoneSource,
    "ZoneKind": ZoneKind,
    "ExtractionMethod": ExtractionMethod,
    "ParamExtractionStatus": ParamExtractionStatus,
    "ExtractionRunStatus": ExtractionRunStatus,
    "DataType": DataType,
    "ReviewPriority": ReviewPriority,
    "RiskLevel": RiskLevel,
    "RuleType": RuleType,
    "CandidatePolicy": CandidatePolicy,
    "ViolationType": ViolationType,
    "RuleDirection": RuleDirection,
    "RuleOperator": RuleOperator,
    "DetectKind": DetectKind,
    "AbstainReason": AbstainReason,
    "OrdinalScale": OrdinalScale,
    "ParamExtractionStrategy": ParamExtractionStrategy,
    "ThresholdSource": ThresholdSource,
    "FeasibilityTier": FeasibilityTier,
    "HedgeKind": HedgeKind,
    "TextOrigin": TextOrigin,
    "ObjectPhase": ObjectPhase,
    "FactSetBy": FactSetBy,
    "MatrixVersionStatus": MatrixVersionStatus,
    "ReferenceConfidence": ReferenceConfidence,
    "NormativeDocType": NormativeDocType,
    "DiscrepancyType": DiscrepancyType,
    "ComparisonAxis": ComparisonAxis,
    "CompletenessStatus": CompletenessStatus,
    "CompletenessBasis": CompletenessBasis,
    "FindingStatus": FindingStatus,
    "DecidedBy": DecidedBy,
    "CheckKind": CheckKind,
    "CheckLifecycle": CheckLifecycle,
    "ReviewRequiredReason": ReviewRequiredReason,
    "EvidenceRole": EvidenceRole,
    "FragmentOrigin": FragmentOrigin,
    "InspectorStatus": InspectorStatus,
    "DecisionType": DecisionType,
    "DecisionCodeKind": DecisionCodeKind,
    "AiVerdict": AiVerdict,
    "DisputeResolutionStatus": DisputeResolutionStatus,
    "PlannedAction": PlannedAction,
    "DiscoveryMethod": DiscoveryMethod,
    "SuspicionInspectorStatus": SuspicionInspectorStatus,
    "PromotedBy": PromotedBy,
    "EvidenceBindStatus": EvidenceBindStatus,
    "RetrainingStatus": RetrainingStatus,
    "GoldLabel": GoldLabel,
    "DatasetItemStatus": DatasetItemStatus,
    "Split": Split,
    "SourceType": SourceType,
    "DatasetVersionStatus": DatasetVersionStatus,
    "ModelApprovalStatus": ModelApprovalStatus,
    "TrainingJobStatus": TrainingJobStatus,
    "EvalKind": EvalKind,
    "SyncStatus": SyncStatus,
    "DeliveryAttemptOutcome": DeliveryAttemptOutcome,
    "RinInboxStatus": RinInboxStatus,
    "PrescriptionStatus": PrescriptionStatus,
    "Role": Role,
    "AuditCategory": AuditCategory,
    "RetentionClass": RetentionClass,
    "IndicatorColor": IndicatorColor,
    "IssueScope": IssueScope,
    "IssueSeverity": IssueSeverity,
    "IssueStatus": IssueStatus,
    "ExportFormat": ExportFormat,
    "NotificationType": NotificationType,
    "ArtifactKind": ArtifactKind,
    "ArtifactFormat": ArtifactFormat,
    "ArtifactScope": ArtifactScope,
    "TagKind": TagKind,
    "TagRoomLink": TagRoomLink,
    "SheetMapBasis": SheetMapBasis,
    "RoomSource": RoomSource,
    "RevisionCloudSource": RevisionCloudSource,
    "TableType": TableType,
    "TableRowKind": TableRowKind,
    "TableCheckKind": TableCheckKind,
    "ProtocolSummaryRow": ProtocolSummaryRow,
    "DeviationDirection": DeviationDirection,
    "DecisionRejectReason": DecisionRejectReason,
    "DecisionConfirmBasis": DecisionConfirmBasis,
    "DecisionClarifyBasis": DecisionClarifyBasis,
    "RevisionBasis": RevisionBasis,
    "SuspicionDismissReason": SuspicionDismissReason,
    "UnfinalizeReason": UnfinalizeReason,
    "CommentSource": CommentSource,
    "GoldEffect": GoldEffect,
    "PermissionScope": PermissionScope,
    "AuditActorType": AuditActorType,
    "AuditResult": AuditResult,
    "AuditObjectType": AuditObjectType,
    "AuditAction": AuditAction,
}
OPEN_ENUMS: frozenset[str] = frozenset({"DocumentStatus", "ManifestSection", "DatasetRole", "AnnotationStatus", "DistributionStatus", "LabelVisibility", "GoldStatus", "EvidenceLocalization", "ZoneKind"})
