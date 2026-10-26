import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import type { ReactNode } from "react";

/** A small centred dialog (forms). The player has its own full-size modal. */
export default function SmallDialog({
  title,
  open,
  onClose,
  children,
}: {
  title: string;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <Dialog open={open} onClose={onClose} className="relative z-50">
      <div className="fixed inset-0 bg-black/50" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <DialogPanel className="w-full max-w-md rounded-lg bg-theme-50 dark:bg-theme-800 text-theme-800 dark:text-theme-100 p-5 shadow-xl">
          <DialogTitle className="text-lg font-semibold mb-3">{title}</DialogTitle>
          {children}
        </DialogPanel>
      </div>
    </Dialog>
  );
}

export const inputClass =
  "w-full rounded border-theme-300 bg-white text-theme-900 dark:bg-theme-700 dark:text-theme-50 dark:border-theme-600 text-sm";
export const buttonClass = "rounded px-3 py-1.5 text-sm font-medium bg-theme-500 text-white hover:bg-theme-600 disabled:opacity-50";
export const plainButtonClass = "rounded px-3 py-1.5 text-sm border border-theme-400";
