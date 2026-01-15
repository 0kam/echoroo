import classnames from "classnames";
import NextLink from "next/link";
import type { ComponentProps, ReactNode } from "react";

import type { Mode, Variant } from "@/lib/components/common";
import { getButtonClassName } from "@/lib/components/ui/Button";

export default function Link({
  children,
  variant,
  mode,
  padding,
  className,
  ...props
}: {
  children: ReactNode;
  variant?: Variant;
  mode?: Mode;
  padding?: string;
  className?: string;
} & Omit<ComponentProps<typeof NextLink>, "className">) {
  // Only apply button styling if mode is explicitly provided
  const shouldUseButtonStyle = mode !== undefined;

  const baseClass = shouldUseButtonStyle
    ? getButtonClassName({ variant: variant ?? "primary", mode, padding: padding ?? "p-2.5" })
    : undefined;

  return (
    <NextLink {...props} className={classnames(baseClass, className)}>
      {children}
    </NextLink>
  );
}
