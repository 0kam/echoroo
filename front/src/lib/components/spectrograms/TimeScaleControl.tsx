import Slider from "@/lib/components/inputs/Slider";

export default function TimeScaleControl({
  value = 1,
  onChange,
  onChangeEnd,
}: {
  value?: number;
  onChange: (value: number) => void;
  onChangeEnd?: (value: number) => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-stone-50 dark:bg-stone-900 border-t border-stone-200 dark:border-stone-700">
      <span className="text-xs text-stone-600 dark:text-stone-400 whitespace-nowrap font-medium">
        Width
      </span>
      <div className="flex-1 max-w-md">
        <Slider
          label="Time Scale"
          value={value}
          onChange={onChange}
          onChangeEnd={onChangeEnd}
          minValue={1.0}
          maxValue={4.0}
          step={0.1}
        />
      </div>
      <span className="text-xs text-stone-600 dark:text-stone-400 font-mono min-w-[32px]">
        {value.toFixed(1)}x
      </span>
    </div>
  );
}
