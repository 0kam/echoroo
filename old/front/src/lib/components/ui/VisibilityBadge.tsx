import classNames from "classnames";

import { LatitudeIcon, UsersIcon } from "@/lib/components/icons";
import type { VisibilityLevel } from "@/lib/schemas";

type VisibilityIcon = typeof LatitudeIcon;

const CONFIG: Record<
  VisibilityLevel,
  {
    label: string;
    className: string;
    Icon: VisibilityIcon;
  }
> = {
  public: {
    label: "Public",
    className: "bg-emerald-100 border-emerald-200 text-emerald-700",
    Icon: LatitudeIcon,
  },
  restricted: {
    label: "Restricted",
    className: "bg-amber-100 border-amber-200 text-amber-700",
    Icon: UsersIcon,
  },
};

export default function VisibilityBadge({
  visibility,
  className,
}: {
  visibility: VisibilityLevel;
  className?: string;
}) {
  const { label, className: style, Icon } = CONFIG[visibility];
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium",
        style,
        className,
      )}
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
      {label}
    </span>
  );
}
