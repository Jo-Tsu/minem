import { useEffect, useRef } from "react";

const closeStack: Array<() => void> = [];
let bodyLockDepth = 0;
let previousBodyOverflow = "";

function visibleDialog() {
  const dialogs = Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"][aria-modal="true"]'));
  return dialogs.filter((dialog) => dialog.getClientRects().length > 0).at(-1) || null;
}

function focusableElements(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'
  )).filter((element) =>
    element.getClientRects().length > 0
    && element.getAttribute("aria-hidden") !== "true"
    && !element.classList.contains("modal-mask")
  );
}

export function useModalBehavior(onClose: () => void, active = true) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (bodyLockDepth === 0) {
      previousBodyOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    bodyLockDepth += 1;

    const closeTop = () => onCloseRef.current();
    closeStack.push(closeTop);
    const focusTimer = window.requestAnimationFrame(() => {
      if (closeStack.at(-1) !== closeTop) return;
      const dialog = visibleDialog();
      if (!dialog || dialog.contains(document.activeElement)) return;
      const target = dialog.querySelector<HTMLElement>("[data-modal-initial-focus]")
        || dialog.querySelector<HTMLElement>("[autofocus]")
        || focusableElements(dialog)[0]
        || dialog;
      if (target === dialog && !dialog.hasAttribute("tabindex")) dialog.setAttribute("tabindex", "-1");
      target.focus();
    });

    const handler = (event: KeyboardEvent) => {
      if (closeStack.at(-1) !== closeTop) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeTop();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = visibleDialog();
      if (!dialog) return;
      const focusable = focusableElements(dialog);
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1)!;
      if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", handler);
    return () => {
      window.cancelAnimationFrame(focusTimer);
      window.removeEventListener("keydown", handler);
      const index = closeStack.lastIndexOf(closeTop);
      if (index >= 0) closeStack.splice(index, 1);
      bodyLockDepth = Math.max(0, bodyLockDepth - 1);
      if (bodyLockDepth === 0) document.body.style.overflow = previousBodyOverflow;
      window.requestAnimationFrame(() => {
        if (previousFocus?.isConnected) previousFocus.focus();
      });
    };
  }, [active]);
}
