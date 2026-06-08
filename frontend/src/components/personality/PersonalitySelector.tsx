"use client";

import { Briefcase, RotateCcw, Sparkles } from "lucide-react";
import React from "react";

import type { PersonalitySelection, PersonalitySelectorCatalog, PersonalitySelectorOption } from "@/lib/api";

const PERSONALITY_ATTITUDE = "personality_attitude";
const WORK_ATTITUDE = "work_attitude";

export function PersonalitySelector({
  catalog,
  selection,
  disabled = false,
  onChange,
}: {
  catalog: PersonalitySelectorCatalog | null | undefined;
  selection: PersonalitySelection | null;
  disabled?: boolean;
  onChange: (selection: PersonalitySelection | null) => void;
}) {
  const optionsByDimension = personalityOptionsByDimension(catalog);
  const normalized = normalizePersonalitySelection(selection);
  const personalityOptions = optionsByDimension[PERSONALITY_ATTITUDE] ?? [];
  const workOptions = optionsByDimension[WORK_ATTITUDE] ?? [];
  const personalitySet = new Set(normalized.personality_attitude_refs);
  const workSet = new Set(normalized.work_attitude_refs);
  const hasSelection = personalitySelectionHasRefs(normalized);
  const hasOptions = Boolean(personalityOptions.length || workOptions.length);

  function update(next: Partial<PersonalitySelection>) {
    const merged = normalizePersonalitySelection({
      ...normalized,
      ...next,
    });
    onChange(personalitySelectionHasRefs(merged) ? merged : null);
  }

  function toggleRef(dimension: typeof PERSONALITY_ATTITUDE | typeof WORK_ATTITUDE, promptRef: string) {
    const key = dimension === PERSONALITY_ATTITUDE ? "personality_attitude_refs" : "work_attitude_refs";
    const current = normalized[key];
    const next = current.includes(promptRef)
      ? current.filter((item) => item !== promptRef)
      : [...current, promptRef];
    update({ [key]: next } as Partial<PersonalitySelection>);
  }

  return (
    <div className="personality-selector">
      {!hasOptions ? (
        <div className="personality-selector__empty">
          <Sparkles size={14} />
          <span>{catalog ? "人格库暂无可选项" : "人格库加载中"}</span>
        </div>
      ) : null}
      {hasOptions ? (
        <div className="personality-selector__row">
          <span className="personality-selector__label">
            <Sparkles size={14} />
            性格
          </span>
          <div className="personality-selector__options" role="group" aria-label="选择性格态度">
            <button
              className={!personalitySet.size ? "personality-selector__chip personality-selector__chip--active" : "personality-selector__chip"}
              disabled={disabled}
              onClick={() => update({ personality_attitude_refs: [] })}
              title="默认不加性格态度人格 prompt"
              type="button"
            >
              默认
            </button>
            {personalityOptions.map((option) => (
              <button
                aria-pressed={personalitySet.has(option.value)}
                className={personalitySet.has(option.value) ? "personality-selector__chip personality-selector__chip--active" : "personality-selector__chip"}
                disabled={disabled}
                key={option.value}
                onClick={() => toggleRef(PERSONALITY_ATTITUDE, option.value)}
                title={option.description || option.title || option.value}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {hasOptions ? (
        <div className="personality-selector__row">
          <span className="personality-selector__label">
            <Briefcase size={14} />
            工作
          </span>
          <div className="personality-selector__options" role="group" aria-label="选择工作态度">
            <button
              className={!workSet.size ? "personality-selector__chip personality-selector__chip--active" : "personality-selector__chip"}
              disabled={disabled}
              onClick={() => update({ work_attitude_refs: [] })}
              title="默认不加工作态度人格 prompt"
              type="button"
            >
              默认
            </button>
            {workOptions.map((option) => (
              <button
                aria-pressed={workSet.has(option.value)}
                className={workSet.has(option.value) ? "personality-selector__chip personality-selector__chip--active" : "personality-selector__chip"}
                disabled={disabled}
                key={option.value}
                onClick={() => toggleRef(WORK_ATTITUDE, option.value)}
                title={option.description || option.title || option.value}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
      {hasSelection ? (
        <button
          aria-label="重置人格选择"
          className="personality-selector__reset"
          disabled={disabled}
          onClick={() => onChange(null)}
          title="重置为默认人格"
          type="button"
        >
          <RotateCcw size={13} />
        </button>
      ) : null}
    </div>
  );
}

export function normalizePersonalitySelection(selection: PersonalitySelection | null | undefined): PersonalitySelection {
  return {
    personality_attitude_refs: uniqueStrings(selection?.personality_attitude_refs ?? []),
    work_attitude_refs: uniqueStrings(selection?.work_attitude_refs ?? []),
  };
}

export function personalitySelectionHasRefs(selection: PersonalitySelection | null | undefined) {
  const normalized = normalizePersonalitySelection(selection);
  return Boolean(normalized.personality_attitude_refs.length || normalized.work_attitude_refs.length);
}

function personalityOptionsByDimension(catalog: PersonalitySelectorCatalog | null | undefined) {
  const result: Record<string, PersonalitySelectorOption[]> = {
    [PERSONALITY_ATTITUDE]: [],
    [WORK_ATTITUDE]: [],
  };
  const dimensions = Array.isArray(catalog?.dimensions) ? catalog?.dimensions ?? [] : [];
  for (const dimension of dimensions) {
    const dimensionId = String(dimension.dimension || "").trim();
    if (!dimensionId) continue;
    result[dimensionId] = Array.isArray(dimension.options) ? dimension.options : [];
  }
  const fallback = catalog?.options_by_dimension ?? {};
  for (const [dimensionId, options] of Object.entries(fallback)) {
    if (!result[dimensionId]?.length && Array.isArray(options)) {
      result[dimensionId] = options;
    }
  }
  return result;
}

function uniqueStrings(values: unknown[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean)));
}
