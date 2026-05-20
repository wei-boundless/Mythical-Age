import { contractBindingValue, mergeContractBindingSection } from "./taskGraphContractBindings";
import { TaskGraphObjectSelectField } from "./TaskGraphInspectorPrimitives";

function stringValue(value: unknown) {
  return String(value ?? "").trim();
}

export function contractBindingFieldValue({
  fallback,
  field,
  section,
  target,
}: {
  fallback?: string;
  field: string;
  section: string;
  target: Record<string, unknown>;
}) {
  return contractBindingValue(target, section, field) || stringValue(fallback);
}

export function contractBindingPatch({
  field,
  legacyPatch = {},
  section,
  target,
  value,
}: {
  field: string;
  legacyPatch?: Record<string, unknown>;
  section: string;
  target: Record<string, unknown>;
  value: string;
}): Record<string, unknown> {
  return {
    ...legacyPatch,
    ...mergeContractBindingSection(target, section, { [field]: value }),
  };
}

export function TaskGraphContractBindingField({
  emptyLabel = "未绑定契约",
  fallback,
  field,
  formatOption,
  label,
  legacyPatch = (value) => ({ [field]: value }),
  onChange,
  options,
  section,
  target,
  wide = false,
}: {
  emptyLabel?: string;
  fallback?: string;
  field: string;
  formatOption: (contractId: string) => string;
  label: string;
  legacyPatch?: (value: string) => Record<string, unknown>;
  onChange: (patch: Record<string, unknown>, value: string) => void;
  options: string[];
  section: string;
  target: Record<string, unknown>;
  wide?: boolean;
}) {
  const value = contractBindingFieldValue({ fallback, field, section, target });
  return (
    <TaskGraphObjectSelectField
      emptyLabel={emptyLabel}
      formatOption={formatOption}
      label={label}
      onChange={(nextValue) => onChange(contractBindingPatch({
        field,
        legacyPatch: legacyPatch(nextValue),
        section,
        target,
        value: nextValue,
      }), nextValue)}
      options={options}
      value={value}
      wide={wide}
    />
  );
}
