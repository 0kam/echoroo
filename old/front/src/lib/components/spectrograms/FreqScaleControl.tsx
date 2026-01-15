import Slider from "@/lib/components/inputs/Slider";
import { SCALE_MIN, SCALE_MAX, SCALE_STEP } from "@/lib/constants";

export default function FreqScaleControl({
  value = 1,
  onChange,
  onChangeEnd,
}: {
  value?: number;
  onChange: (value: number) => void;
  onChangeEnd?: (value: number) => void;
}) {
  const handleChange = (val: number | number[]) => {
    const numValue = Array.isArray(val) ? val[0] : val;
    onChange(numValue);
  };

  const handleChangeEnd = onChangeEnd
    ? (val: number | number[]) => {
        const numValue = Array.isArray(val) ? val[0] : val;
        onChangeEnd(numValue);
      }
    : undefined;

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-stone-50 dark:bg-stone-900 border-t border-stone-200 dark:border-stone-700">
      <span className="text-xs text-stone-600 dark:text-stone-400 whitespace-nowrap font-medium">
        Height
      </span>
      <div className="flex-1 max-w-md">
        <Slider
          label="Frequency Scale"
          value={value}
          onChange={handleChange}
          onChangeEnd={handleChangeEnd}
          minValue={SCALE_MIN}
          maxValue={SCALE_MAX}
          step={SCALE_STEP}
        />
      </div>
      <span className="text-xs text-stone-600 dark:text-stone-400 font-mono min-w-[32px]">
        {value.toFixed(1)}x
      </span>
    </div>
  );
}
