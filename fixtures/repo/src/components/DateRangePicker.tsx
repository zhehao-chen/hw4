import { useEffect, useState } from "react";
import { t, type Locale } from "../i18n";
import { addDays, toISODate } from "../util/dates";

export interface DateRange {
  /** YYYY-MM-DD */
  from: string;
  /** YYYY-MM-DD */
  to: string;
}

interface DateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
  locale?: Locale;
}

function thisMonth(today = new Date()): DateRange {
  const first = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), 1));
  return { from: toISODate(first), to: toISODate(today) };
}

function lastDays(days: number, today = new Date()): DateRange {
  return { from: toISODate(addDays(today, -(days - 1))), to: toISODate(today) };
}

export function DateRangePicker({ value, onChange, locale = "en" }: DateRangePickerProps) {
  // Local draft so a half-edited range is not pushed to the parent.
  const [draft, setDraft] = useState<DateRange>(value);

  // Depend on the strings, not the object, so a parent re-render does not reset the draft.
  useEffect(() => {
    setDraft({ from: value.from, to: value.to });
  }, [value.from, value.to]);

  const invalid = draft.from !== "" && draft.to !== "" && draft.from > draft.to;

  const update = (patch: Partial<DateRange>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    if (next.from && next.to && next.from <= next.to) onChange(next);
  };

  const applyPreset = (range: DateRange) => {
    setDraft(range);
    onChange(range);
  };

  return (
    <fieldset className="date-range">
      <label>
        {t("ui.dateRange.from", {}, locale)}
        <input
          type="date"
          value={draft.from}
          max={draft.to || undefined}
          onChange={(e) => update({ from: e.target.value })}
        />
      </label>
      <label>
        {t("ui.dateRange.to", {}, locale)}
        <input
          type="date"
          value={draft.to}
          min={draft.from || undefined}
          onChange={(e) => update({ to: e.target.value })}
        />
      </label>

      <div className="date-range__presets">
        <button type="button" onClick={() => applyPreset(thisMonth())}>
          {t("ui.dateRange.thisMonth", {}, locale)}
        </button>
        <button type="button" onClick={() => applyPreset(lastDays(30))}>
          {t("ui.dateRange.last30", {}, locale)}
        </button>
      </div>

      {invalid && (
        <p className="date-range__error" role="alert">
          {t("ui.dateRange.invalid", {}, locale)}
        </p>
      )}
    </fieldset>
  );
}
