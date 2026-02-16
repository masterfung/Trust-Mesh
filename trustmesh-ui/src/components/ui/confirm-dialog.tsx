"use client";

import { useCallback, useEffect, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "default";
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  loading = false,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Focus confirm button on open
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onCancel]);

  // Close on backdrop click
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onCancel();
    },
    [onCancel]
  );

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        className="relative w-full max-w-md mx-4 bg-card border border-card-border rounded-2xl shadow-2xl shadow-black/40 animate-in fade-in zoom-in-95 duration-200"
      >
        <div className="p-6">
          <h2 id="confirm-title" className="text-lg font-semibold text-foreground">
            {title}
          </h2>
          {description && (
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
              {description}
            </p>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 pb-6">
          <button
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-xl hover:bg-card-hover transition-colors disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            disabled={loading}
            className={`px-4 py-2 text-sm font-semibold rounded-xl transition-all disabled:opacity-50 ${
              variant === "danger"
                ? "bg-danger/90 hover:bg-danger text-white"
                : "bg-accent hover:bg-accent-hover text-accent-fg"
            }`}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Working...
              </span>
            ) : (
              confirmLabel
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
