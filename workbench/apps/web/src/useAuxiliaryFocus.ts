import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

let locks = 0;
let previousOverflow = "";

function lockScroll() {
  if (!locks++) {
    previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  return () => {
    if (!--locks) document.body.style.overflow = previousOverflow;
  };
}

function currentDialog() {
  const dialogs = [
    ...document.querySelectorAll<HTMLElement>('[role="dialog"]'),
  ].filter((element) => !element.closest("[hidden],[inert]"));
  return dialogs.at(-1);
}

/** A desktop side panel is not modal; only compact panels trap focus/scroll. */
export function useAuxiliaryFocus({
  open,
  modal,
  panel,
  initialFocus,
  onClose,
}: {
  open: boolean;
  modal: boolean;
  panel: RefObject<HTMLElement | null>;
  initialFocus: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const close = useRef(onClose);
  const closing = useRef(false);
  close.current = onClose;
  useLayoutEffect(() => {
    if (!open) return;
    closing.current = false;
    const before = document.activeElement as HTMLElement | null;
    const surface = panel.current;
    initialFocus.current?.focus({ preventScroll: true });
    return () => {
      closing.current = true;
      // React restores selection after DOM mutations. Restore our trigger only
      // after that commit, and never take focus from a newly opened surface.
      queueMicrotask(() => {
        const active = document.activeElement;
        if (
          closing.current &&
          before?.isConnected &&
          (!active || active === document.body || surface?.contains(active))
        )
          before.focus({ preventScroll: true });
      });
    };
  }, [open, panel, initialFocus]);
  useLayoutEffect(() => {
    if (open && modal) return lockScroll();
  }, [open, modal]);
  useEffect(() => {
    if (!open) return;
    function focusables() {
      return [
        ...(panel.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled),summary,[contenteditable="true"],[tabindex="0"]',
        ) ?? []),
      ].filter((element) => {
        const closed = element.closest("details:not([open])");
        return (
          !element.closest("[hidden],[inert]") &&
          (!closed ||
            closed.firstElementChild === element ||
            closed.firstElementChild?.contains(element)) &&
          getComputedStyle(element).display !== "none"
        );
      });
    }
    function isTop() {
      const dialog = currentDialog();
      return modal
        ? dialog === panel.current
        : !dialog || dialog === panel.current;
    }
    function keydown(event: KeyboardEvent) {
      if (closing.current || event.defaultPrevented || !isTop()) return;
      if (
        event.key === "Escape" &&
        (modal || panel.current?.contains(document.activeElement))
      ) {
        event.preventDefault();
        close.current();
      } else if (event.key === "Tab" && modal) {
        const items = focusables();
        const first = items[0],
          last = items.at(-1);
        if (!first) {
          event.preventDefault();
          panel.current?.focus({ preventScroll: true });
        } else if (
          event.shiftKey &&
          (document.activeElement === first ||
            !panel.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          last?.focus({ preventScroll: true });
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            !panel.current?.contains(document.activeElement))
        ) {
          event.preventDefault();
          first.focus({ preventScroll: true });
        }
      }
    }
    function focusin(event: FocusEvent) {
      if (
        !closing.current &&
        modal &&
        isTop() &&
        !panel.current?.contains(event.target as Node)
      )
        (focusables()[0] ?? panel.current)?.focus({ preventScroll: true });
    }
    window.addEventListener("keydown", keydown);
    window.addEventListener("focusin", focusin);
    if (modal && !panel.current?.contains(document.activeElement))
      initialFocus.current?.focus({ preventScroll: true });
    return () => {
      window.removeEventListener("keydown", keydown);
      window.removeEventListener("focusin", focusin);
    };
  }, [open, modal, panel, initialFocus]);
}
