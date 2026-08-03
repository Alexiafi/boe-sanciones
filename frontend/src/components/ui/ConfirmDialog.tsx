"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ReactNode } from "react";
import { Button } from "./Button";

/**
 * Modal confirmation used for anything that echoes back a range/volume
 * before running (backfill) or that sends something external (email). Built
 * on @radix-ui/react-dialog (already a dependency, previously unused) for
 * focus trapping and Escape-to-close for free.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  confirmLabel = "Confirmar",
  onConfirm,
  confirmDisabled,
  danger,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  confirmDisabled?: boolean;
  danger?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-on-surface/40 backdrop-blur-sm" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface-container-lowest/80 p-6 shadow-ambient backdrop-blur-md">
          <Dialog.Title className="text-lg font-semibold tracking-[-0.02em] text-on-surface">{title}</Dialog.Title>
          {description && (
            <Dialog.Description className="mt-2 text-sm text-on-surface-variant">{description}</Dialog.Description>
          )}
          {children && <div className="mt-4">{children}</div>}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="secondary" size="sm">
                Cancelar
              </Button>
            </Dialog.Close>
            <Button variant={danger ? "danger" : "primary"} size="sm" onClick={onConfirm} disabled={confirmDisabled}>
              {confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
