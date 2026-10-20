export type DataType = 'text' | 'integer' | 'decimal' | 'date';
export type RuleCode = 'REQUIRED_VALUE_MISSING' | 'INVALID_TYPE' | 'OUT_OF_RANGE' | 'NON_UNIQUE_VALUE' | 'DUPLICATE_ROW';
export interface Page<T> { items: T[]; total: number; offset: number; limit: number }
export interface Column { column_id: string; position: number; original_name: string; display_name: string }
export interface RawRecord { row_index: number; values: string[] }
export interface ColumnProfile { column_id: string; non_missing_count: number; missing_count: number }
export interface TypeSuggestion { column_id: string; suggested_type: DataType | null; sample_size: number; matching_count: number; match_counts: { date: number; integer: number; decimal: number }; reason: 'best_match' | 'leading_zero' | 'fallback_text' | 'empty_sample' }
export interface TypeSuggestions { decimal_separator: '.' | ','; columns: TypeSuggestion[] }
export interface DatasetSummary { dataset_id: string; original_filename: string; file_size_bytes: number; row_count: number; column_count: number; created_at: string; expires_at: string | null; retention_pinned: boolean; run_count: number }
export interface RunListItem { run_id: string; status: RunStatus; created_at: string; started_at: string | null; finished_at: string | null }
export interface Dataset extends DatasetSummary { file_sha256: string; csv: { encoding: 'utf-8' | 'windows-1251'; delimiter: ',' | ';' | '\t' }; ignored_blank_line_count: number; columns: Column[]; profile: ColumnProfile[]; type_suggestions: TypeSuggestions; runs: RunListItem[] }
export interface ColumnRule { column_id: string; required: boolean; unique: boolean; expected_type: DataType; range: { min: string | null; max: string | null } | null }
export interface Configuration { schema_version: '1.0'; decimal_separator: '.' | ','; check_duplicate_rows: boolean; columns: ColumnRule[] }
export interface Summary { total_records: number; problematic_records: number; clean_records: number; total_issues: number; by_rule: { rule_code: RuleCode; issue_count: number; record_count: number }[]; by_column: { column_id: string; issue_count: number; record_count: number }[]; row_level: { issue_count: number; record_count: number }; duplicate_rows: { enabled: boolean; group_count: number; participant_count: number; extra_count: number }; unique_columns: { column_id: string; group_count: number; participant_count: number; extra_count: number }[] }
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed';
export interface Run { run_id: string; dataset_id: string; status: RunStatus; stage: string; created_at: string; started_at: string | null; finished_at: string | null; duration_ms: number | null; expires_at: string | null; retention_pinned: boolean; configuration_snapshot: Configuration; algorithm_version: string; summary: Summary | null; error: { code: string; message: string; details: unknown } | null }
export interface Issue { issue_id: string; row_index: number; column_id: string | null; column_name: string | null; rule_code: RuleCode; message: string; raw_value: string | null; rule_parameters: Record<string, unknown>; duplicate_group_id: string | null }
export interface DuplicateGroup extends Page<RawRecord> { group_id: string; rule_code: 'DUPLICATE_ROW' | 'NON_UNIQUE_VALUE'; column_id: string | null; normalized_key: string | null; participant_count: number; extra_count: number }
export interface RecordWithIssues { run_id: string; row_index: number; values: string[]; issues: Issue[]; violation_count: number }
export interface Capabilities { config_schema_version: string; report_schema_version: string; algorithm_version: string; supported_encodings: string[]; supported_delimiters: string[]; supported_types: DataType[]; defaults: { encoding: string; delimiter: string; decimal_separator: '.' | ',' }; limits: Record<string, number> }
export interface ApiErrorPayload { code: string; message: string; details: unknown; request_id?: string }
