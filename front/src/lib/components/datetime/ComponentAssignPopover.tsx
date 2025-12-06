"use client";

import { Dialog, Transition } from "@headlessui/react";
import classNames from "classnames";
import { Fragment, useEffect, useRef } from "react";

import { COMPONENT_CONFIGS, COMPONENT_ORDER } from "./constants";
import type { DateTimeComponentType, DateTimeSelection } from "./types";

interface ComponentAssignPopoverProps {
  /** Whether the popover is open */
  isOpen: boolean;
  /** Callback when popover should close */
  onClose: () => void;
  /** Callback when a component type is selected */
  onSelect: (type: DateTimeComponentType) => void;
  /** The selected text */
  selectedText: string;
  /** Existing selections to disable already-used types */
  existingSelections: DateTimeSelection[];
}

/**
 * Dialog for assigning a datetime component type to a selection
 */
export default function ComponentAssignPopover({
  isOpen,
  onClose,
  onSelect,
  selectedText,
  existingSelections,
}: ComponentAssignPopoverProps) {
  const firstButtonRef = useRef<HTMLButtonElement>(null);

  // Focus first available button on open
  useEffect(() => {
    if (isOpen && firstButtonRef.current) {
      // Short delay to ensure transition has started
      const timer = setTimeout(() => {
        firstButtonRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  // Check if a component type is already used
  const isTypeUsed = (type: DateTimeComponentType) => {
    return existingSelections.some((s) => s.type === type);
  };

  // Find first available type for initial focus
  const firstAvailableIndex = COMPONENT_ORDER.findIndex(
    (type) => !isTypeUsed(type),
  );

  return (
    <Transition appear show={isOpen} as={Fragment}>
      <Dialog as="div" className="relative z-50" onClose={onClose}>
        <Transition.Child
          as={Fragment}
          enter="ease-out duration-200"
          enterFrom="opacity-0"
          enterTo="opacity-100"
          leave="ease-in duration-150"
          leaveFrom="opacity-100"
          leaveTo="opacity-0"
        >
          <div className="fixed inset-0 bg-black/25" />
        </Transition.Child>

        <div className="fixed inset-0 overflow-y-auto">
          <div className="flex min-h-full items-center justify-center p-4">
            <Transition.Child
              as={Fragment}
              enter="ease-out duration-200"
              enterFrom="opacity-0 scale-95"
              enterTo="opacity-100 scale-100"
              leave="ease-in duration-150"
              leaveFrom="opacity-100 scale-100"
              leaveTo="opacity-0 scale-95"
            >
              <Dialog.Panel
                className={classNames(
                  "w-full max-w-xs transform overflow-hidden rounded-lg p-4",
                  "bg-white dark:bg-stone-800",
                  "shadow-xl transition-all",
                )}
              >
                {/* Header */}
                <Dialog.Title
                  as="div"
                  className="mb-3"
                >
                  <p className="text-sm font-medium text-stone-900 dark:text-stone-100">
                    Assign Component
                  </p>
                  <p className="text-xs text-stone-500 dark:text-stone-400 mt-0.5">
                    Selected:{" "}
                    <span className="font-mono">&quot;{selectedText}&quot;</span>
                  </p>
                </Dialog.Title>

                {/* Component type buttons */}
                <div className="grid grid-cols-2 gap-2">
                  {COMPONENT_ORDER.map((type, index) => {
                    const config = COMPONENT_CONFIGS[type];
                    const used = isTypeUsed(type);
                    const isFirstAvailable = index === firstAvailableIndex;

                    return (
                      <button
                        key={type}
                        ref={isFirstAvailable ? firstButtonRef : undefined}
                        type="button"
                        onClick={() => {
                          if (!used) {
                            onSelect(type);
                          }
                        }}
                        disabled={used}
                        className={classNames(
                          "flex items-center gap-2 px-3 py-2 rounded-md",
                          "text-sm font-medium transition-colors",
                          "focus:outline-none focus:ring-2 focus:ring-offset-1",
                          used
                            ? [
                                "opacity-40 cursor-not-allowed",
                                "bg-stone-100 dark:bg-stone-700",
                                "text-stone-400 dark:text-stone-500",
                              ]
                            : [config.bgColor, config.textColor, config.hoverBg],
                          !used && `focus:ring-${config.color}-500`,
                        )}
                      >
                        <span
                          className={classNames(
                            "w-5 h-5 rounded-full flex items-center justify-center",
                            "text-xs font-bold text-white",
                            used
                              ? "bg-stone-400 dark:bg-stone-500"
                              : [
                                  type === "year" && "bg-emerald-500",
                                  type === "month" && "bg-blue-500",
                                  type === "day" && "bg-violet-500",
                                  type === "hour" && "bg-amber-500",
                                  type === "minute" && "bg-teal-500",
                                  type === "second" && "bg-rose-500",
                                ],
                          )}
                        >
                          {config.shortLabel}
                        </span>
                        {config.label}
                      </button>
                    );
                  })}
                </div>

                {/* Cancel button */}
                <div className="mt-3 pt-3 border-t border-stone-200 dark:border-stone-700">
                  <button
                    type="button"
                    onClick={onClose}
                    className={classNames(
                      "w-full px-3 py-2 rounded-md",
                      "text-sm text-stone-600 dark:text-stone-400",
                      "hover:bg-stone-100 dark:hover:bg-stone-700",
                      "transition-colors",
                    )}
                  >
                    Cancel
                  </button>
                </div>
              </Dialog.Panel>
            </Transition.Child>
          </div>
        </div>
      </Dialog>
    </Transition>
  );
}
